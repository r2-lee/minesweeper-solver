"""猜哪一格：不只看"这一步别死"，还看"打开之后能连锁解开多少"。

背景
----
遇到必须猜的局面时，最朴素的做法是挑**雷概率最低**的一格（``probability.py``
里的 ``best_guess``）。这只优化了"这一步的存活率"，没有考虑另一件事：开出来
的数字可能一下解开一大片——如果一格 30% 会死、但活下来能连锁确认十几格，
它往往比 25% 但只多一个数字的孤立坑更值得点。

这正是 Minesweeper 求解器文献里反复提到的"一步前瞻"（one-step lookahead）：

* Couëtoux, Milone, Pellegrino, *Monte-Carlo Tree Search for the Game of
  Minesweeper*（INRIA RR-8041, 2012）——第 5 章明确指出"只看一步的贪心
  策略会被前瞻策略压制"，他们的 OH/one-step 版本就是"对每个候选动作估计
  观察后的局面质量"；
* minesweeper.info 的 *Minesweeper Constraint Satisfaction* 一文同样把猜法
  分成"最小概率"和"最小概率 + 打开后信息量"两档。

这里复现的就是那个 one-step 版本：对候选格做一步展开，用**与约束一致的
蒙特卡洛采样**估计"打开它之后立刻能确定多少格"，再按

    score = P(安全) × (1 + 期望新增确定格数)

排序。其中"雷图采样"用 ``frontier.sample_mines``（随机化的最受限优先 DFS），
"打开之后还能确定多少"直接复用精确边际求解器 ``FrontierSolver``。

预算
----
每次猜测最多 ``samples × candidates`` 次精确求解（默认 8×4=32 次），
高级盘一次求解约 2 ms，所以一次猜测约 60~100 ms——只在"必须猜"的那一步
付这个代价（高级盘平均每局 2.5 次）。
"""

import logging
import math
import random
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..core.board import Board
from ..core.enums import Mark
from ..core.geometry import Position, neighbours
from . import rollout
from .frontier import (
    DEFAULT_BUDGET,
    UNIFORM_LIMIT,
    Constraint,
    ConstraintSystem,
    FrontierSolver,
    FrontierTooLarge,
    _split_components,
    build_system,
    count_solutions,
    probabilities,
    sample_mines,
)
from .probability import TableLike, best_guess

#: 默认采样多少张一致雷图。
DEFAULT_SAMPLES = 8
#: 默认只看概率最低的几格（再往后的格几乎不会赢）。
DEFAULT_CANDIDATES = 4
#: Legacy argument default for callers of choose_open_progress.
DEFAULT_BAND = 0.1
#: Budget for continuation draws per candidate, with one per feasible clue as a minimum.
DEFAULT_TRIALS = 4


def _layout(mines: Set[Position], rows: int, cols: int) -> List[List[int]]:
    """按雷的位置算出整盘数字（-1 表示雷）。"""
    layout = [[0] * cols for _ in range(rows)]
    for row, col in mines:
        layout[row][col] = -1
    for row in range(rows):
        for col in range(cols):
            if layout[row][col] == -1:
                continue
            count = 0
            for nrow, ncol in neighbours((row, col), rows, cols):
                if layout[nrow][ncol] == -1:
                    count += 1
            layout[row][col] = count
    return layout


def _flood(marked: List[List[int]], layout: List[List[int]], cell: Position,
           rows: int, cols: int) -> None:
    """在假设棋盘上模拟一次展开（0 连锁到它的数字边界）。"""
    stack = [cell]
    while stack:
        row, col = stack.pop()
        marked[row][col] = int(Mark.OPENED)
        if layout[row][col] != 0:
            continue
        for nrow, ncol in neighbours((row, col), rows, cols):
            if marked[nrow][ncol] == int(Mark.COVERED):
                stack.append((nrow, ncol))


def _progress(
    board: Board,
    cell: Position,
    mines: Set[Position],
    frontier: Optional[Set[Position]] = None,
    rounds: int = 12,
) -> float:
    """假设这一格开着、雷图是 ``mines``，把"确定能开的格"连锁开到不动点，
    返回因此解掉的**边沿格**数量。

    只统计边沿格：远处空白格被打开时也会连锁翻开一大片，但那些格子不提供
    任何约束，开完照样得猜——算成收益会让求解器偏爱远处的坑（实测掉 3~4 个
    点）。连开多轮是因为"开出来的数字"还会带来新的确定格，一轮估算会低估。
    """
    rows, cols = board.rows, board.cols
    layout = _layout(mines, rows, cols)
    hypothesis = Board(rows, cols, board.mines)
    hypothesis.mine_matrix = layout
    hypothesis.mark_matrix = [list(row) for row in board.mark_matrix]
    _flood(hypothesis.mark_matrix, layout, cell, rows, cols)

    total = 0.0
    for _ in range(rounds):
        try:
            table = FrontierSolver(hypothesis).probabilities()
        except Exception:  # 假设棋盘上组件过大等：放弃这一格
            break
        safe = [position for position, value in table.items() if value <= 0.0]
        certain = [position for position, value in table.items() if value >= 1.0]
        if frontier is not None:
            total += 0.5 * sum(1 for position in certain if position in frontier)
        opened = 0
        for position in safe:
            if hypothesis.mark_matrix[position[0]][position[1]] != Mark.COVERED:
                continue
            _flood(hypothesis.mark_matrix, layout, position, rows, cols)
            if frontier is None or position in frontier:
                opened += 1
        total += opened
        if not safe:
            break
    return total


def rank_candidates(table: TableLike, limit: int,
                    tolerance: Optional[float] = None) -> List[Position]:
    """按雷概率从低到高取出最值得考虑的几格。

    ``tolerance`` 给成数字时，只保留"概率和最低者相差不超过这个值"的格子——也就是
    只在这些**风险基本相同**的候选里比信息量。这一点是 A/B 测出来的关键：
    允许拿"多 3 个点死亡风险"去换信息量是亏的（2000 局 45.6% vs 49.4%），
    但在完全打平的格子里挑能连锁的那一个，则是稳赚。
    """
    entries = [(value, position) for position, value in table.items()
               if 0.0 < value < 1.0]
    if not entries:
        return []
    entries.sort(key=lambda item: item[0])
    if tolerance is None:
        return [position for _value, position in entries[:limit]]
    lowest = entries[0][0]
    pool = [position for value, position in entries if value <= lowest + tolerance]
    return pool[:limit]


def choose_open(
    board: Board,
    table: TableLike,
    samples: int = DEFAULT_SAMPLES,
    candidates: int = DEFAULT_CANDIDATES,
    tolerance: Optional[float] = 0.0,
    rng: Optional[random.Random] = None,
    log: Optional[logging.Logger] = None,
) -> Optional[Tuple[Position, float]]:
    """挑一格打开，返回 ``(位置, 该格的雷概率)``；没有候选时返回 ``None``。

    打平时按雷概率低者优先（也就是退回旧行为），保证结果稳定、可复现。
    """
    if rng is None:
        rng = random
    if log is None:
        log = logging.getLogger(__name__)

    pool = rank_candidates(table, max(1, candidates), tolerance)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0], table[pool[0]]

    system = FrontierSolver(board).system()
    if not system.consistent:
        return best_guess([table])

    frontier = set(system.frontier)
    scores = {position: 0.0 for position in pool}
    attempts = 0
    for _ in range(samples):
        mines = sample_mines(system, rng)
        if mines is None:
            continue
        attempts += 1
        for position in pool:
            if position in mines:
                continue  # 踩雷：贡献 0
            scores[position] += 1.0 + _progress(board, position, mines, frontier)

    if not attempts:
        return best_guess([table])

    best = max(pool, key=lambda position: (scores[position], -table[position]))
    log.info(
        "前瞻选择 %s（概率=%.4f，得分=%.2f，候选=%s）",
        best, table[best], scores[best] / attempts,
        {position: round(value / attempts, 2) for position, value in scores.items()},
    )
    return best, table[best]

def _clue_outcomes(
    system: ConstraintSystem, cell: Position, adjacent: Tuple[Position, ...],
) -> List[Tuple[int, ConstraintSystem, int]]:
    """Count layouts for each possible clue, given that the clicked cell is safe.

    The clue here counts mines among the still-covered neighbours. Adding the
    already flagged neighbours shifts every value by the same constant.
    """
    observed = {cell, *adjacent}
    frontier = system.frontier + tuple(position for position in system.free if position in observed)
    free = tuple(position for position in system.free if position not in observed)
    safe = system.constraints + (Constraint((cell,), 0),)
    outcomes = []
    for mines in range(min(len(adjacent), system.total_mines) + 1):
        constraints = safe + (Constraint(adjacent, mines),) if adjacent else safe
        branch = ConstraintSystem(constraints, frontier, free, system.total_mines)
        ways = count_solutions(branch, budget=DEFAULT_BUDGET)
        if ways:
            outcomes.append((mines, branch, ways))
    return outcomes


def _continuation_win_rate(
    board: Board,
    cell: Position,
    adjacent: Tuple[Position, ...],
    outcomes: Sequence[Tuple[int, ConstraintSystem, int]],
    worlds: Sequence[Set[Position]],
    flags: Set[Position],
    trials: int,
    rng: random.Random,
    config,
) -> Optional[float]:
    """Stratify baseline rollouts by the observed clue and use exact weights."""
    if not outcomes:
        return None
    safe_layouts = sum(ways for _, _, ways in outcomes)
    samples_by_clue: Dict[int, List[Set[Position]]] = defaultdict(list)
    for world in worlds:
        if cell not in world:
            samples_by_clue[sum(position in world for position in adjacent)].append(world)

    terms = []
    extra_trials = max(0, trials - len(outcomes))
    for clue, branch, ways in outcomes:
        if ways == 1:
            # With a single layout left, every remaining tile is determined.
            terms.append(ways / safe_layouts)
            continue
        draws = 1 + extra_trials * ways // safe_layouts
        samples = samples_by_clue[clue][:draws]
        if len(samples) < draws and len(branch.frontier) > UNIFORM_LIMIT:
            return None
        while len(samples) < draws:
            sample = sample_mines(branch, rng)
            if sample is None:
                return None
            samples.append(sample)
        wins = sum(rollout.simulate(board, world | flags, cell, config=config, rng=rng)
                   for world in samples)
        terms.append((ways / safe_layouts) * (wins / draws))
    return math.fsum(terms)


def choose_open_progress(
    board: Board,
    table: TableLike,
    trials: int = DEFAULT_TRIALS,
    band: float = DEFAULT_BAND,
    limit: int = 8,
    rng: Optional[random.Random] = None,
    log: Optional[logging.Logger] = None,
    endgame: bool = False,
) -> Optional[Tuple[Position, float]]:
    """Rank equally safe guesses by their estimated chance of winning the game.

    The exact counts weight every feasible clue. The baseline policy plays out
    sampled layouts within each clue, including the actual flood on a zero.
    Equal scores and evaluation limits use the baseline's usual choice.
    The legacy band argument is accepted. Eligibility always uses exact ties.
    """
    baseline = best_guess([table])
    if baseline is None or limit <= 1 or trials <= 0:
        return baseline
    first, risk = baseline
    candidates = [first] + [position for position, value in table.items()
                            if position != first and value == risk][:limit - 1]
    if len(candidates) == 1:
        return baseline

    system = build_system(board)
    if not system.consistent or len(system.frontier) > UNIFORM_LIMIT:
        return baseline

    rng = random if rng is None else rng
    # 续局用"基础策略"（min_prob + 精确边际），默认不嵌套端局搜索：
    # 端局搜索是"猜法里再套猜法"，它让每次续局贵一倍以上，收益要在 A/B 里单独算。
    config = rollout._rollout_config()
    if endgame:
        from dataclasses import replace as _replace

        config = _replace(config, endgame=True)
    unknown = set(system.unknown)
    flags = {
        (row, col) for row, marks in enumerate(board.mark_matrix)
        for col, mark in enumerate(marks) if mark == Mark.FLAG
    }
    try:
        # Reuse common posterior layouts across candidates. A branch gets its
        # own conditional draws when these layouts do not cover it.
        worlds = [sample_mines(system, rng) for _ in range(trials)]
        worlds = [world for world in worlds if world is not None]
        best, best_value = first, -1.0
        for position in candidates:
            adjacent = tuple(near for near in neighbours(position, board.rows, board.cols)
                             if near in unknown)
            outcomes = _clue_outcomes(system, position, adjacent)
            value = _continuation_win_rate(
                board, position, adjacent, outcomes, worlds, flags, trials, rng, config
            )
            if value is None:
                return baseline
            if value > best_value + 1e-12:
                best, best_value = position, value
    except FrontierTooLarge:
        return baseline

    if log is not None:
        log.debug("Progress guess %s, risk %.4f, estimated win %.4f, candidates %d",
                  best, risk, (1.0 - risk) * best_value, len(candidates))
    return best, risk


# ---------------------------------------------------------------------------
# "还要猜几次"（fewest）
# ---------------------------------------------------------------------------
#
# 胜率近似 ``P ≈ q ** n``：``q`` 是每次冒险的平均存活率（实测约 0.775），
# ``n`` 是这一局还要猜几次。既然 ``q`` 已经由"挑最安全的格"压到底了，能动的
# 就只有 ``n``——少猜一次比每一次少冒几个点的险更值钱。
#
# 关键在于 ``n`` 可以**数**出来，不用蒙特卡洛：给定一张一致雷图，打开候选格
# 之后重建约束系统，凡是还剩"开不开都不确定"的格子的边沿组件，就至少要再猜
# 一次；空白区按"一次猜测平均扫开多少格"折算。这个量是结构量，没有采样噪声
# （这正是之前几版前瞻/rollout 失败的地方：它们拿胜负这种 Bernoulli 采样当
# 分数，2000 局尺度下全被噪声吃了）。

#: 把"空白区还剩多少格"折算成"还要猜几次"时，一次猜测平均扫开的格数。
FREE_PER_GUESS = 40.0
#: 实测的"每次冒险的平均存活率"（``0.775 ** 2.76 ≈ 0.49``，与 2000 局实测吻合）。
FEWEST_Q = 0.775
#: ``guess_policy == "fewest"`` 时，每个候选看几张一致雷图。
DEFAULT_FEWEST_WORLDS = 2
#: ``guess_policy == "fewest"`` 时看几个候选（概率最低的几格）。
DEFAULT_FEWEST_CANDIDATES = 4


def _guesses_after(board: Board, mines: Set[Position], cell: Position) -> Optional[int]:
    """假设雷图是 ``mines``、打开 ``cell``，估计**之后还要猜几次**。

    返回 ``None`` 表示这个假设算不动（组件过大、约束矛盾），调用方应跳过。
    """
    rows, cols = board.rows, board.cols
    layout = _layout(mines, rows, cols)
    hypothesis = Board(rows, cols, board.mines)
    hypothesis.mine_matrix = layout
    hypothesis.mark_matrix = [list(row) for row in board.mark_matrix]
    _flood(hypothesis.mark_matrix, layout, cell, rows, cols)

    try:
        system = build_system(hypothesis)
        if not system.consistent:
            return None
        table = probabilities(system)
    except FrontierTooLarge:
        return None
    except Exception:  # 假设棋盘上其它意外：当作算不动
        return None

    guesses = 0
    for cells, _constraints in _split_components(system.constraints):
        for position in cells:
            value = table.get(position)
            if value is None or 0.0 < value < 1.0:
                guesses += 1
                break

    free_unknown = sum(
        1 for position in system.free
        if 0.0 < table.get(position, 0.5) < 1.0
    )
    if free_unknown:
        guesses += int(math.ceil(free_unknown / FREE_PER_GUESS))
    return guesses


def choose_open_fewest(
    board: Board,
    table: TableLike,
    candidates: int = DEFAULT_FEWEST_CANDIDATES,
    band: float = 0.25,
    worlds: int = DEFAULT_FEWEST_WORLDS,
    rng: Optional[random.Random] = None,
    log: Optional[logging.Logger] = None,
) -> Optional[Tuple[Position, float]]:
    """按"打开后还要猜几次"挑格：``score = P(安全) × q ** n_after``。

    ``n_after`` 是打开这一格之后**估计还要猜几次**（见 :func:`_guesses_after`），
    ``q`` 取实测的每次冒险平均存活率。两个候选里选那个能少猜一次的，哪怕它
    这一手的雷概率略高。
    """
    if rng is None:
        rng = random
    if log is None:
        log = logging.getLogger(__name__)

    pool = rank_candidates(table, max(1, candidates), tolerance=band)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0], table[pool[0]]

    system = FrontierSolver(board).system()
    if not system.consistent:
        return best_guess([table])

    scores: Dict[Position, float] = {}
    seen: Dict[Position, int] = {}
    for position in pool:
        survival = 1.0 - table[position]
        total, count = 0.0, 0
        for _ in range(max(1, worlds)):
            mines = sample_mines(system, rng)
            if not mines or position in mines:
                continue  # 这张雷图里这格是雷：只说明"会死"，不影响存活后的期望
            guesses = _guesses_after(board, mines, position)
            if guesses is None:
                continue
            total += FEWEST_Q ** guesses
            count += 1
        if count:
            scores[position] = survival * (total / count)
            seen[position] = count
        else:
            # 一张有效雷图都没取到：退回"这一手安全"的朴素估计
            scores[position] = survival * FEWEST_Q ** 2

    best = max(pool, key=lambda position: (scores[position], -table[position]))
    log.info(
        "少猜优先选择 %s（概率=%.4f，得分=%.3f，候选=%s）",
        best,
        table[best],
        scores[best],
        {position: round(value, 3) for position, value in scores.items()},
    )
    return best, table[best]


# ---------------------------------------------------------------------------
# 超级位置（super location，EdLogg 的 SUPERLOC 规则）
# ---------------------------------------------------------------------------
#
# EdLogg 在"必须猜"的时候会先看**不在边沿上**的空白格：如果这一格属于一片还没
# 打开、又和边沿相邻的空白区，点下去有相当概率连锁炸开一大片，一次就生成十几条
# 新约束，把后面好几次猜测都省掉。他管这叫 super location，代价是这类格子的雷
# 概率通常**不是最低**的（空白区密度 vs 边沿上的 1/8、1/5）。
#
# 我们的 ``min_prob`` 永远只点"当前最安全"的那一格，于是经常一个组件一个组件地
# 磨，整局猜测次数比他多 0.4 次（2.69 vs 2.27）。这里复刻他的取舍：候选只要不比
# 最安全格危险超过 ``band``，就按"开出来能炸开多大一片"排序。

#: 允许为"炸开一片"多冒的雷概率（绝对值）。
DEFAULT_SUPERLOC_BAND = 0.10


def _unknown_regions(board: Board) -> Dict[Position, int]:
    """把"既没打开、也不挨着任何已开格"的空白格按连通性分块，返回 格 -> 块大小。"""
    rows, cols = board.rows, board.cols
    mark = board.mark_matrix
    unknown = {
        (row, col)
        for row in range(rows)
        for col in range(cols)
        if mark[row][col] == Mark.COVERED
    }
    frontier = {
        (row, col)
        for row, col in unknown
        if any(mark[nr][nc] == Mark.OPENED for nr, nc in neighbours((row, col), rows, cols))
    }
    free = unknown - frontier

    sizes: Dict[Position, int] = {}
    seen = set()
    for cell in free:
        if cell in seen:
            continue
        stack = [cell]
        seen.add(cell)
        block = [cell]
        while stack:
            current = stack.pop()
            for nxt in neighbours(current, rows, cols):
                if nxt in free and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
                    block.append(nxt)
        size = len(block)
        for position in block:
            sizes[position] = size
    return sizes


def choose_open_superloc(
    board: Board,
    table: TableLike,
    band: float = DEFAULT_SUPERLOC_BAND,
    log: Optional[logging.Logger] = None,
) -> Optional[Tuple[Position, float]]:
    """EdLogg 的 SUPERLOC：挑"开出来能清掉一片"的空白格，而不是最安全的边沿格。

    他的打分是 ``exposed = 1 - nonPerimeterProb + count * prob``，其中 ``count`` 是
    这一格所在空区里"不挨着边沿"的格数，``prob = openProb[count + 1]`` 是"这一片
    全是空地"的概率——后者随 ``count`` 指数衰减，所以 ``count * prob`` 在 10 格左右
    达到峰值：**太大的空区反而不值**（越远、越可能藏雷），这一点和我们第一版只按
    面积排序完全不同。

    这里照抄这个形状：``score = region * safety ** (region + 1)``。区域大小取
    ``_unknown_regions`` 的连通块大小；边沿格子按区域 1 计，于是它的分数退化成
    ``safety ** 2``——只在没有像样空区可用时才会被选中。
    """
    if log is None:
        log = logging.getLogger(__name__)

    entries = [(value, position) for position, value in table.items() if 0.0 < value < 1.0]
    if not entries:
        return None
    entries.sort(key=lambda item: item[0])
    lowest = entries[0][0]
    pool = [position for value, position in entries if value <= lowest + band]
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0], table[pool[0]]

    sizes = _unknown_regions(board)

    def score(position: Position) -> float:
        safety = 1.0 - table[position]
        region = max(1, min(sizes.get(position, 1), 80))
        return region * safety ** (region + 1)

    best = max(pool, key=lambda position: (score(position), -table[position]))
    log.info(
        "超级位置选择 %s（概率=%.4f，所在空区=%d，候选=%s）",
        best,
        table[best],
        sizes.get(best, 1),
        {position: round(score(position), 3) for position in pool[:8]},
    )
    return best, table[best]

DEFAULT_BLANK_CAP = 8


def choose_open_blank(
    board: Board,
    table: TableLike,
    cap: int = DEFAULT_BLANK_CAP,
    log: Optional[logging.Logger] = None,
) -> Optional[Tuple[Position, float]]:
    """没有确定解时，"往空白区里面点一下"和"点最安全的边沿格"直接比期望收益。

    EdLogg 的 SUPERLOC 只把*不在边沿上*的格子当候选，用
    ``exposed = (1 - nonPerimeterProb) + count * prob`` 排序——也就是"能炸开多少格"
    而不是"有多安全"。这里按同样的形状打分：``safety * (1 + min(block, cap))``，
    再与边沿最安全格的 ``safety``（炸开 1 格）比较，谁大选谁。

    ``block`` 是这一格所在空白连通块的大小。注意它**没有**概率带宽限制：EdLogg 会
    为了多炸一片而接受明显更高的雷概率，这正是 ``min_prob`` 从不做的事。
    """
    if log is None:
        log = logging.getLogger(__name__)

    entries = [(value, position) for position, value in table.items() if 0.0 < value < 1.0]
    if not entries:
        return None
    lowest = min(value for value, _ in entries)
    safest = min((value, position) for value, position in entries)[1]

    sizes = _unknown_regions(board)
    if not sizes:
        return None

    def score(position: Position) -> float:
        safety = 1.0 - table[position]
        return safety * (1.0 + min(sizes.get(position, 1), cap))

    best = max(sizes, key=lambda position: (score(position), -table[position]))
    baseline = (1.0 - lowest)
    if score(best) <= baseline:
        return None
    log.info(
        "空白区试探 %s（概率=%.4f，空区=%d，得分=%.3f vs 边沿=%.3f）",
        best, table[best], sizes[best], score(best), baseline,
    )
    return best, table[best]


# ---------------------------------------------------------------------------
# JSMinesweeper 的另外两层：50/50 检测 与 living tile
# ---------------------------------------------------------------------------
#: 检测"分不开的硬币"时，单个组件最多枚举多少种配置。
COIN_CONFIG_LIMIT = 2_000
#: 边沿大于这个规模就不做硬币检测（中盘枚举太贵，而且中盘的硬币迟早会解开）。
COIN_CELL_LIMIT = 30
#: living tile 估算"打开后会显示几个不同数字"时抽几张雷图。
DEFAULT_LIVING_SAMPLES = 24
#: living tile 只在"最安全格 +5%"的带宽内选，避免拿风险换信息。
DEFAULT_LIVING_BAND = 0.05


def find_coin(
    board: Board,
    system=None,
    limit: int = COIN_CONFIG_LIMIT,
    max_cells: int = COIN_CELL_LIMIT,
):
    """找一对"永远解不开"的硬币格。

    判定标准是**强**的：两格在同一个连通组件里，且该组件的**每一种**合法配置
    里都恰好只有一格是雷（``a XOR b`` 恒真）。这种结构无论后面再翻开多少格
    都分不开，JSMinesweeper 的做法是尽早把它点掉，而不是等到最后再赌。

    返回 ``(a, b)`` 或 ``None``。只对边沿 <= ``max_cells`` 的局面生效。
    """

    from .endgame import _component_configurations

    system = build_system(board) if system is None else system
    if not getattr(system, "consistent", True):
        return None
    if len(system.frontier) > max_cells:
        return None

    for component in system.components():
        cells = list(component.positions)
        if len(cells) < 2:
            continue
        inside = set(cells)
        constraints = [item for item in system.constraints if set(item.positions) <= inside]
        configs = _component_configurations(cells, constraints, limit)
        if not configs:
            continue

        full = (1 << len(configs)) - 1
        masks = []
        for cell in cells:
            mask = 0
            for bit, config in enumerate(configs):
                if cell in config:
                    mask |= 1 << bit
            masks.append(mask)

        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                # 必须**两格各占一半**才是硬币：如果一格恒为雷、另一格恒安全，
                # XOR 也是全 1，但那不是硬币，是"确定格"（点下去必死）。
                if bin(masks[i]).count("1") * 2 != len(configs):
                    continue
                if masks[i] ^ masks[j] != full:
                    continue
                # "永远只有一颗雷"还不够：只有当两边权重相同时才是真 50/50。
                # 否则（比如 0.88 / 0.12）点下去几乎是自杀——早盘那版就是这么崩的。
                try:
                    table = probabilities(system)
                except Exception:  # noqa: BLE001 - 拿不到概率就当作没找到
                    return None
                if abs(table.get(cells[i], 0.0) - 0.5) <= 1e-9 and \
                        abs(table.get(cells[j], 0.0) - 0.5) <= 1e-9:
                    return cells[i], cells[j]
    return None


def choose_open_living(
    board: Board,
    table: TableLike,
    system=None,
    samples: int = DEFAULT_LIVING_SAMPLES,
    band: float = DEFAULT_LIVING_BAND,
    limit: int = 6,
    rng: Optional[random.Random] = None,
    log: Optional[logging.Logger] = None,
):
    """living tile：在同样安全的格子里，优先点"还能揭示新信息"的那一格。

    JSMinesweeper 的定义：未开且可能有多个取值的格是 living，点 non-living 格
    既不会死也不会带来新信息。这里用采样近似——抽 ``samples`` 张一致雷图，统计
    每个候选格"打开后会显示几种不同数字"，种类越多信息量越大；并列时比雷概率。
    """

    if not table:
        return None

    log = log or logging.getLogger(__name__)

    candidates = [(position, value) for position, value in table.items() if 0.0 < value < 1.0]
    if not candidates:
        return None
    lowest = min(value for _, value in candidates)
    candidates = [(position, value) for position, value in candidates if value <= lowest + band]
    candidates.sort(key=lambda item: (item[1], item[0]))
    candidates = candidates[:limit]
    if len(candidates) == 1:
        return candidates[0]

    system = build_system(board) if system is None else system
    worlds = []
    for _ in range(samples):
        mines = sample_mines(system, rng)
        if mines is not None:
            worlds.append(mines)
    if not worlds:
        return None

    layouts = [_layout(mines, board.rows, board.cols) for mines in worlds]
    best = None
    for position, probability in candidates:
        row, col = position
        values = set()
        for mines, layout in zip(worlds, layouts):
            if position in mines:
                continue
            values.add(layout[row][col])
        score = (len(values), -probability)
        if best is None or score > best[0]:
            best = (score, position, probability)

    if best is None:
        return None
    score, position, probability = best
    log.info("living tile 选择 %s（可能显示 %d 种数字，概率=%.4f）", position, score[0], probability)
    return position, probability
