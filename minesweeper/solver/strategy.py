"""自动计算策略：把概率表变成"该点哪一格"的动作流。

两套搜索模式
------------
``SolverConfig.exact_marginals = True``（精确模式，推荐）
    每轮用 :class:`~minesweeper.solver.frontier.FrontierSolver` 把**整个边沿**
    做组件分解 + 总雷数卷积，得到全盘每个未知格的精确概率。0/1 就是逻辑必然，
    中间值是真正的后验概率；某个组件太大算不动时自动退回窗口模式。

``exact_marginals = False``（旧版窗口模式，保留用于 A/B 对比）
    1. 先看小窗口（``level = 1``，3x3）；
    2. 没有 0/1 的确定结论就升到大窗口（``level = 2``，5x5）；
    3. 还不行、而且剩下的未知格和雷都不多时，切换到整盘枚举；
    4. 仍然不行就猜：从所有概率表里挑概率最低的一格打开；
       连一张非空概率表都没有时，才随机挑一个未知格（``guess_fallback``）。

三个阈值都在 :class:`SolverConfig` 里，测试可以单独调。

为什么是"生成器"
----------------
调用方（界面、胜率工具）是**边消费边改棋盘**的：拿一个动作、执行、再来要下一个。
所以这里必须懒求值——每轮重新读棋盘快照，而不是一次性算完整局的计划。
这同时解释了 :meth:`AutoSolver._certain_actions` 里那个"先查当前标记再输出"的
检查：相邻的两个数字格会把同一批格子各算一遍，第二遍必须跳过已经执行的。

与旧版的差异（细节见 ``docs/KNOWN_ISSUES.md``）：

* 概率表只输出真正未展开的格子，不再把已展开格当成"确定安全"；
* 完全没有候选时默认随机猜一格（旧版在这里抛 ``UnboundLocalError``）。
"""

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from ..core.board import Board
from ..core.enums import Mark
from ..core.geometry import Position, neighbours
from .engine import Engine, resolve_engine
from .adaptive import choose_open_adaptive
from .guess import (
    DEFAULT_BAND,
    DEFAULT_CANDIDATES,
    DEFAULT_FEWEST_CANDIDATES,
    DEFAULT_FEWEST_WORLDS,
    DEFAULT_SAMPLES,
    DEFAULT_SUPERLOC_BAND,
    DEFAULT_TRIALS,
    choose_open,
    choose_open_blank,
    choose_open_fewest,
    choose_open_progress,
    choose_open_living,
    choose_open_superloc,
    find_coin,
)
from .endgame import solve as endgame_solve
from .gametree import solve as gametree_solve
from .gametree import solve_pinned as gametree_solve_pinned
from .lookahead import solve as search_solve
from .frontier import FrontierSolver, FrontierTooLarge
from .informed import choose_open_informed
from .local import LocalSolver
from .probability import ProbabilityTable, TableLike, best_guess
from .rollout import (
    DEFAULT_BAND as ROLLOUT_BAND,
    DEFAULT_CANDIDATES as ROLLOUT_CANDIDATES,
    DEFAULT_SAMPLES as ROLLOUT_SAMPLES,
)
from .rollout import choose_open as choose_open_rollout
from .rollout import choose_gamble
from .whole import WholeSolver
from .window import board_values, local_centers, unknown_positions


class ActionKind(Enum):
    """自动计算给出的两种动作。"""

    OPEN = "open"
    FLAG = "flag"


@dataclass(frozen=True)
class Action:
    """一步自动计算动作。"""

    kind: ActionKind
    position: Position

    def __str__(self) -> str:  # pragma: no cover - 调试用
        verb = "展开" if self.kind is ActionKind.OPEN else "标雷"
        return "{}{}".format(verb, self.position)


@dataclass(frozen=True)
class SolverConfig:
    """策略参数。默认值与旧版硬编码的常量一致。"""

    #: 最多迭代多少轮（旧版 ``range(1000)``）
    max_iterations: int = 1000
    #: 窗口半径上限（旧版写死 ``L < 2`` 就升到 2）
    max_level: int = 2
    #: 允许切换整盘计算的未知格上限（旧版 ``n < 28``）
    whole_unopened_limit: int = 28
    #: 允许切换整盘计算的剩余雷数上限（旧版 ``k < 14``）
    whole_mines_limit: int = 14
    #: 一张概率表都没有时，是否随机挑一格试运气。
    #: 设成 ``False`` 就退回旧语义：安静地停下（自动计算跑不完一局）。
    guess_fallback: bool = True
    #: 用边沿组件分解得到的**全盘精确边际**代替窗口启发式。
    #: 关掉就退回旧的"局部窗口 + 阈值整盘"行为（A/B 对比用）。
    exact_marginals: bool = True
    #: 必须猜的时候怎么选格子：
    #: ``"min_prob"`` = 只挑雷概率最低的格子（默认）；
    #: ``"fewest"`` = 少猜优先：在概率接近的候选里挑"打开后还要猜的次数最少"的；
    #: ``"lookahead"`` = 一步前瞻：在风险相同的候选里挑"打开后能连锁确定更多格"的；
    #: ``"progress"`` = 按翻牌结果加权估算续局胜率，只比较最低雷概率并列格。
    #: ``"rollout"`` = 对候选做蒙特卡洛模拟下到终局；
    #: ``"search"`` = 边沿信念期望最大搜索（EdLogg 的 game tree）。
    #: 实测（高级 16x30/99、首点中心、同盘 10,000 局、精确边际 + 原生加速器）：
    #: ``min_prob`` 50.52%（283.2 步），``progress`` **51.19%**（283.5 步，配对 McNemar
    #: +67 局 / z = 2.42），其余十种（lookahead / rollout / search / informed /
    #: adaptive / deep / gametree / fewest / superloc / coin / living）都 ≤ 基线。
    #: 所以默认用 ``progress``——这是 Hill 的"同风险候选重排"的等价实现，
    #: 也是本项目最终选定的猜法（见 docs/ALGORITHM_LOG.md 的 PERF-19/20）。
    guess_policy: str = "progress"
    #: 前瞻时采样多少张一致雷图、看几个候选格。
    guess_samples: int = DEFAULT_SAMPLES
    guess_candidates: int = DEFAULT_CANDIDATES
    #: 只在"雷概率与最低者相差不超过这个值"的候选里比信息量。
    #: 0 = 只比完全打平的格子（默认，绝不拿更高风险换信息）。
    guess_tolerance: float = 0.0
    #: progress 每个并列候选的续局采样预算。
    guess_trials: int = DEFAULT_TRIALS
    #: 兼容旧配置。progress 的候选范围固定为最低雷概率并列格。
    guess_band: float = DEFAULT_BAND
    #: progress 的续局里是否嵌套端局精确搜索（关掉快一倍以上，A/B 见 PERF-16）。
    progress_endgame: bool = False
    #: ``guess_policy == "adaptive"``：按需加深的规模上限与改点门槛（见 adaptive.py）。
    adaptive_worlds: int = 256
    adaptive_cells: int = 20
    adaptive_nodes: int = 400
    adaptive_margin: float = 0.005

    #: ``guess_policy == "informed"`` 时：看几个候选、允许比最安全格多冒多少雷概率
    informed_candidates: int = 5
    informed_band: float = 0.02
    #: ``guess_policy == "rollout"`` 时的模拟参数:几个候选、每个候选模拟几局。
    rollout_samples: int = 3
    rollout_candidates: int = 4
    rollout_band: float = 0.25
    #: ``guess_policy == "gamble"`` 时:每个候选模拟几局、空区至少多大才值得赌。
    gamble_samples: int = 2
    gamble_region_min: int = 20
    #: ``guess_policy == "fewest"`` 时：看几个候选、每个候选看几张一致雷图。
    fewest_candidates: int = DEFAULT_FEWEST_CANDIDATES
    fewest_worlds: int = DEFAULT_FEWEST_WORLDS
    #: "fewest" 候选带宽：只在这个概率差以内的候选间比"还要猜几次"。
    fewest_band: float = 0.25
    #: ``guess_policy == "superloc"`` 时：允许比最安全格多冒的雷概率（EdLogg 的 SUPERLOC）
    superloc_band: float = DEFAULT_SUPERLOC_BAND
    #: ``guess_policy == "living"`` 时：抽几张雷图估算"这格能显示几种数字"、候选带宽
    living_samples: int = 24
    living_band: float = 0.05
    #: ``guess_policy == "coin"`` 时：边沿不超过多少格才做"分不开的硬币"检测
    coin_cells: int = 30
    #: ``guess_policy == "search"`` 时的搜索深度与预算
    guess_depth: int = 2
    guess_worlds: int = 800
    guess_nodes: int = 2000
    #: ``guess_policy == "gametree"`` 时的世界数、节点预算与候选数
    gametree_worlds: int = 1000
    gametree_nodes: int = 20000
    gametree_candidates: int = 10
    #: 端局精确求解：未知格少、一致雷图少时，直接算“每一格开下去的胜率”再选。
    endgame: bool = True
    endgame_cells: int = 20
    endgame_worlds: int = 512
    endgame_nodes: int = 2000


@dataclass(frozen=True)
class _SearchState:
    """跨轮次保留的搜索状态。"""

    level: int = 1
    whole_mode: bool = False


@dataclass(frozen=True)
class _Step:
    """一轮没算出确定动作时，下一步该怎么办。

    ``action`` 是要执行的猜测；``action is None`` 时要么已经换挡（``state``
    变了，下一轮重算），要么该停（``stop``）。
    """

    state: _SearchState
    action: Optional[Action] = None
    stop: bool = False


class AutoSolver:
    """把棋盘状态喂给概率计算，产出"展开/标雷"动作流。

    用法::

        for action in AutoSolver(board).actions():
            if action.kind is ActionKind.OPEN:
                board.expansion(*action.position)
            else:
                board.mark_mine(*action.position)

    注意：``actions()`` 是生成器，**挂起期间棋盘状态会变**（调用方每执行一步
    就改棋盘），所以它每轮都重新取快照，不能提前把所有结果算完。
    """

    def __init__(
        self,
        board: Board,
        engine: Optional[Engine] = None,
        config: Optional[SolverConfig] = None,
        local_solver: Optional[LocalSolver] = None,
        whole_solver: Optional[WholeSolver] = None,
        frontier_solver: Optional[FrontierSolver] = None,
        log: Optional[logging.Logger] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.board = board
        self.config = config or SolverConfig()
        self.log = log or logging.getLogger(__name__)
        self.rng = rng if rng is not None else random

        # 引擎/窗口求解器都是**惰性**的：精确模式完全用不到 Mat_Cal，
        # 所以在没有原生模块的机器（比如 Linux）上也能跑胜率测量。
        self._engine = engine
        self._local_solver = local_solver
        self._whole_solver = whole_solver
        self._frontier_solver = (
            frontier_solver if frontier_solver is not None else FrontierSolver(board)
        )

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            # auto：优先原生 Mat_Cal，没有就退回纯 Python 参考实现。
            # 精确模式在正常路径上根本不会碰这里，只有"组件太大退回窗口法"
            # 才会用到——所以在没有 Mat_Cal 的机器上也不能直接崩。
            self._engine = resolve_engine("auto")
        return self._engine

    @property
    def local_solver(self) -> LocalSolver:
        if self._local_solver is None:
            self._local_solver = LocalSolver(self.board, self.engine)
        return self._local_solver

    @property
    def whole_solver(self) -> WholeSolver:
        if self._whole_solver is None:
            self._whole_solver = WholeSolver(self.board, self.engine)
        return self._whole_solver

    @property
    def frontier_solver(self) -> FrontierSolver:
        return self._frontier_solver

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def actions(self) -> Iterator[Action]:
        """产出动作，直到解完、判断失败或者用完迭代次数。"""
        state = _SearchState()
        for _ in range(self.config.max_iterations):
            values = board_values(self.board)

            if self.config.guess_policy == "coin" and self._unknown_count() <= self.config.coin_cells:
                coin = find_coin(self.board, max_cells=self.config.coin_cells)
                if coin is not None:
                    self.log.info("分不开的 50/50：先点掉 %s", coin[0])
                    yield Action(ActionKind.OPEN, coin[0])
                    state = _SearchState(level=1, whole_mode=state.whole_mode)
                    continue

            tables, exact = self._tables(values, state)

            produced = False
            for action in self._certain_actions(tables):
                produced = True
                yield action

            if produced:
                # 有确定动作就把窗口收回到最小：局部窗口越大越慢，
                # 而且大窗口只是"看得多"，不会让确定结论变得更确定。
                # 注意只收窗口、不退出整盘模式——旧版就是这样，退出会让
                # 后续轮次的概率表来源变化，走子和胜率都会跟着变。
                state = _SearchState(level=1, whole_mode=state.whole_mode)
                continue

            step = self._when_stuck(values, tables, state, exact)
            state = step.state
            if step.action is not None:
                yield step.action
            elif step.stop:
                return

    # ------------------------------------------------------------------
    # 一轮里的三个步骤
    # ------------------------------------------------------------------
    def _tables(
        self, values: List[List[int]], state: _SearchState
    ) -> Tuple[List[TableLike], bool]:
        """本轮要看的概率表，以及是否用了精确边际。

        精确模式下一张表就覆盖了全盘所有未知格（含远离边沿的空白格），
        所以既不需要升阶，也不需要"整盘模式"这种阈值判断。
        """
        if self.config.exact_marginals:
            try:
                table = self.frontier_solver.probabilities(values)
            except FrontierTooLarge:
                # 组件太大（罕见）：退回窗口启发式，别让整局卡住。
                self.log.warning("边沿组件过大，退回窗口法")
            else:
                self.log.debug("精确边际计算: %d 个未知格", len(table))
                return [table], True

        if state.whole_mode:
            self.log.debug("整盘计算, level=%d", state.level)
            return [self.whole_solver.probabilities()], False

        self.log.debug("局部计算, level=%d", state.level)
        return [
            self.local_solver.probabilities(row, col, state.level)
            for row, col in local_centers(values)
        ], False

    def _certain_actions(self, tables: Iterable[TableLike]) -> Iterator[Action]:
        """把概率表里的 0/1 变成动作。

        注意这里是**懒**的：每输出一个动作，调用方就会去改棋盘，所以
        "这一格是不是已经处理过"必须在输出前一刻检查，不能提前把整批筛好。
        """
        for table in tables:
            for position, value in table.items():
                if self._already_resolved(position):
                    continue
                if value <= 0.0:
                    yield Action(ActionKind.OPEN, position)
                elif value >= 1.0:
                    yield Action(ActionKind.FLAG, position)

    def _when_stuck(
        self,
        values: List[List[int]],
        tables: List[TableLike],
        state: _SearchState,
        exact: bool = False,
    ) -> _Step:
        """没有确定动作时：升阶 -> 整盘 -> 猜（顺序与旧版一致）。

        精确模式下没有"升阶"和"整盘"这两步可走——那张表已经是最全的信息了，
        剩下的只有猜。
        """
        config = self.config

        if not exact and state.level < config.max_level:
            next_level = state.level + 1
            self.log.info("本轮没有确定动作，升阶到 level=%d", next_level)
            return _Step(_SearchState(next_level, state.whole_mode))

        if not exact and not state.whole_mode:
            unknown = len(unknown_positions(values))
            remain = self.board.remain_mine()
            self.log.info(
                "升阶后仍无解，评估整盘计算: 未知格=%d, 剩余雷=%d", unknown, remain
            )
            if (
                unknown < config.whole_unopened_limit
                and remain < config.whole_mines_limit
            ):
                return _Step(_SearchState(state.level, True))
            return self._guess(values, tables, state)

        if not exact:
            self.log.info("整盘计算也没有确定动作")
        return self._guess(values, tables, state, exact=exact)

    def _guess(
        self,
        values: List[List[int]],
        tables: List[TableLike],
        state: _SearchState,
        exact: bool = False,
    ) -> _Step:
        """挑一格打开：优先"最不可能是雷"的，实在没有信息才随机。

        精确模式且 ``guess_policy == "lookahead"`` 时，再往前走一步：
        在概率最低的几格里挑"打开后能连锁确定最多格"的那一格（见 guess.py）。
        """
        if exact and self.config.endgame:
            choice = endgame_solve(
                self.board,
                cell_limit=self.config.endgame_cells,
                world_limit=self.config.endgame_worlds,
                node_limit=self.config.endgame_nodes,
            )
            if choice is not None:
                position, value = choice
                self.log.info("端局精确求解：打开 %s（胜率≈%.3f）", position, value)
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "plan":
            from .planner import plan_open

            choice = plan_open(self.board, rng=self.rng, log=self.log)
            if choice is not None:
                position, value = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "gametree":
            choice = gametree_solve(
                self.board,
                world_limit=self.config.gametree_worlds,
                node_limit=self.config.gametree_nodes,
                candidate_limit=self.config.gametree_candidates,
            )
            if choice is not None:
                position, value = choice
                self.log.info("博弈树求解：打开 %s（胜率≈%.3f）", position, value)
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "pinned":
            choice = gametree_solve_pinned(
                self.board,
                world_limit=self.config.gametree_worlds,
                node_limit=self.config.gametree_nodes,
                candidate_limit=self.config.gametree_candidates,
            )
            if choice is not None:
                position, value = choice
                self.log.info("钉死组件搜索：打开 %s（胜率≈%.3f）", position, value)
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "blank":
            choice = choose_open_blank(self.board, tables[0], log=self.log) if tables else None
            if choice is not None:
                position, probability = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "superloc" and tables:
            choice = choose_open_superloc(
                self.board,
                tables[0],
                band=self.config.superloc_band,
                log=self.log,
            )
            if choice is not None:
                position, probability = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "fewest" and tables:
            choice = choose_open_fewest(
                self.board,
                tables[0],
                candidates=self.config.fewest_candidates,
                band=self.config.fewest_band,
                worlds=self.config.fewest_worlds,
                rng=self.rng,
                log=self.log,
            )
            if choice is not None:
                position, probability = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "gamble" and tables:
            choice = choose_gamble(
                self.board,
                tables[0],
                samples=self.config.gamble_samples,
                region_min=self.config.gamble_region_min,
                rng=self.rng,
                log=self.log,
            )
            if choice is not None:
                position, score = choice
                self.log.info("赌一把空区：打开 %s（估计胜率≈%.3f）", position, score)
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "rollout" and tables:
            choice = choose_open_rollout(
                self.board,
                tables[0],
                samples=self.config.rollout_samples,
                candidates=self.config.rollout_candidates,
                band=self.config.rollout_band,
                rng=self.rng,
                log=self.log,
            )
            if choice is not None:
                position, score = choice
                self.log.info("模拟评估：打开 %s（估计胜率≈%.3f）", position, score)
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "search":
            choice = search_solve(
                self.board,
                depth=self.config.guess_depth,
                world_limit=self.config.guess_worlds,
                node_limit=self.config.guess_nodes,
            )
            if choice is not None:
                position, value = choice
                self.log.info("边沿期望搜索：打开 %s（估计胜率≈%.3f）", position, value)
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "adaptive" and tables:
            choice = choose_open_adaptive(
                self.board,
                tables[0],
                worlds=self.config.adaptive_worlds,
                cells=self.config.adaptive_cells,
                nodes=self.config.adaptive_nodes,
                margin=self.config.adaptive_margin,
                log=self.log,
            )
            if choice is not None:
                position, _value = choice
                return _Step(state, Action(ActionKind.OPEN, position))
        if exact and self.config.guess_policy == "informed" and tables:
            choice = choose_open_informed(
                self.board,
                tables[0],
                candidates=self.config.informed_candidates,
                band=self.config.informed_band,
                log=self.log,
            )
            if choice is not None:
                position, value = choice
                self.log.info("信息评估：打开 %s（估计胜率≈%.4f）", position, value)
                return _Step(state, Action(ActionKind.OPEN, position))
        if exact and self.config.guess_policy == "progress" and tables:
            choice = choose_open_progress(
                self.board,
                tables[0],
                trials=self.config.guess_trials,
                band=self.config.guess_band,
                limit=max(2, self.config.guess_candidates * 2),
                rng=self.rng,
                log=self.log,
                endgame=self.config.progress_endgame,
            )
            if choice is not None:
                position, probability = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "lookahead" and tables:
            choice = choose_open(
                self.board,
                tables[0],
                samples=self.config.guess_samples,
                candidates=self.config.guess_candidates,
                tolerance=self.config.guess_tolerance,
                rng=self.rng,
                log=self.log,
            )
            if choice is not None:
                position, probability = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "living" and tables:
            choice = choose_open_living(
                self.board,
                tables[0],
                samples=self.config.living_samples,
                band=self.config.living_band,
                rng=self.rng,
                log=self.log,
            )
            if choice is not None:
                position, probability = choice
                return _Step(state, Action(ActionKind.OPEN, position))

        if exact and self.config.guess_policy == "deep":
            choice = self._deepest_tie(tables)
            if choice is not None:
                position, probability = choice
                self.log.info("最安全且有最多未知邻格 %s (概率=%.4f)", position, probability)
                return _Step(state, Action(ActionKind.OPEN, position))

        choice = best_guess(tables)
        if choice is not None:
            position, probability = choice
            self.log.info("无法确定，猜测位置 %s (概率=%.4f)", position, probability)
            return _Step(state, Action(ActionKind.OPEN, position))

        if not self.config.guess_fallback:
            # 旧版在这里会抛 UnboundLocalError（openPos 从未赋值），见 DEV-1。
            self.log.warning("没有任何候选位置，自动计算停止")
            return _Step(state, stop=True)

        free = unknown_positions(values)
        if not free:
            self.log.warning("没有可猜测的格子，自动计算停止")
            return _Step(state, stop=True)

        position = self.rng.choice(free)
        self.log.info("没有概率可用，随机猜 %s", position)
        return _Step(state, Action(ActionKind.OPEN, position))

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def _deepest_tie(self, tables: List[TableLike]):
        """在"概率并列最低"的格子里挑**未知邻格最多**的那一个。

        并列时随便挑一格会白白丢掉连锁：空白区里每格的雷概率都一样（同一密度），
        但点中间那格能一次扫开一大片，点边上那格可能只翻开一格。所以并列时按
        "未知邻格数"排序——这是不用做任何搜索就能拿到的信息增益。
        """
        best = None
        tied: List[Position] = []
        for table in tables:
            for position, value in table.items():
                if value <= 0.0 or value >= 1.0:
                    continue
                if best is None or value < best - 1e-9:
                    best = value
                    tied = [position]
                elif value <= best + 1e-9:
                    tied.append(position)
        if best is None:
            return None
        if len(tied) == 1:
            return tied[0], best

        rows, cols = self.board.rows, self.board.cols
        mark = self.board.mark_matrix

        def score(position: Position) -> int:
            return sum(
                1
                for neighbour in neighbours(position, rows, cols)
                if mark[neighbour[0]][neighbour[1]] == Mark.COVERED
            )

        position = max(tied, key=lambda item: (score(item), -item[0], -item[1]))
        return position, best

    def _unknown_count(self) -> int:
        """还有多少格没被翻开（含已标雷的格）。

        ``coin`` 策略用它当便宜的闸门：中盘边沿几十格时枚举组件太贵，
        而且中盘的硬币迟早会被后续信息解开，只有残局才值得"提前点掉"。
        """

        return sum(row.count(Mark.COVERED) for row in self.board.mark_matrix)

    def _already_resolved(self, position: Position) -> bool:
        """这一格是不是已经被处理过（已展开或已标雷）。"""
        mark = self.board.mark_matrix[position[0]][position[1]]
        return mark == Mark.OPENED or mark == Mark.FLAG

