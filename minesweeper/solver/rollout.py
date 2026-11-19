"""猜哪一格：直接模拟"打开这一格之后能不能赢"。

``lookahead`` 用"周长能连锁清掉多少格"当收益代理，这个代理在中盘会系统性
偏乐观：周长清完了，空白区里还压着几十颗雷，接下来照样要猜。``rollout``
换成最直白的估计——从这一格开始，用同一套策略真的下到终局，赢的概率就是
它的价值。它顺手把"super location"那种"拿一点风险换一大片连锁"的取舍
自动算进去了：连锁带来的收益会体现为后面更少的猜测，而不是一个拍脑袋的
格数。

代价是每一步要跑若干次完整对局（十毫秒量级），所以只在真的要猜的时候用。
"""

from __future__ import annotations

import copy
import logging
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..core.board import Board
from ..core.enums import MINE, Mark, Status
from ..core.geometry import Position, neighbours
from . import frontier
from .probability import ProbabilityTable, TableLike, best_guess

__all__ = ["blank_cell", "choose_gamble", "choose_open", "estimate", "simulate"]

DEFAULT_CANDIDATES = 3
DEFAULT_SAMPLES = 2
DEFAULT_BAND = 0.15
MAX_STEPS = 4000
DEFAULT_REGION_MIN = 20


_NUMBER_CACHE: Dict[Tuple[int, int, int], Tuple[Tuple[int, ...], ...]] = {}
_NUMBER_CACHE_LIMIT = 64


def _numbers(rows: int, cols: int, mined: Set[Position]) -> Tuple[Tuple[int, ...], ...]:
    """雷图 -> 数字盘。同一个候选下所有续局共用一张雷图，值得缓存。"""

    key = (rows, cols, frozenset(mined))  # type: ignore[arg-type]
    cached = _NUMBER_CACHE.get(key)
    if cached is not None:
        return cached
    matrix = [[0] * cols for _ in range(rows)]
    for row, col in mined:
        matrix[row][col] = MINE
    for cell in mined:
        for row, col in neighbours(cell, rows, cols):
            if matrix[row][col] != MINE:
                matrix[row][col] += 1
    frozen = tuple(tuple(row) for row in matrix)
    if len(_NUMBER_CACHE) >= _NUMBER_CACHE_LIMIT:
        _NUMBER_CACHE.clear()
    _NUMBER_CACHE[key] = frozen
    return frozen


def _world_board(board: Board, mined: Set[Position]) -> Board:
    """按给定的雷图复制一张棋盘（保留已翻开/已标雷的状态）。"""

    world = Board(board.rows, board.cols, board.mines)
    world.mine_matrix = [list(row) for row in _numbers(board.rows, board.cols, mined)]
    world.mark_matrix = [list(values) for values in board.mark_matrix]
    return world


def _rollout_config():
    """rollout 内部用的策略：最安全格 + 精确边际，关掉端局和前瞻。

    关掉端局是为了避免"猜法里再套猜法"的递归——这里要的是**同一套基础策略**
    的胜负，端局/前瞻的增益由外层评估体现。
    """

    from .strategy import SolverConfig

    return SolverConfig(
        exact_marginals=True,
        guess_policy="min_prob",
        endgame=False,
        max_iterations=MAX_STEPS,
    )


def simulate(
    board: Board,
    mined: Set[Position],
    cell: Position,
    config=None,
    log: Optional[logging.Logger] = None,
    rng: Optional[random.Random] = None,
) -> bool:
    """在给定雷图上打开 ``cell``，然后按基础策略下到终局，返回是否获胜。"""

    from .strategy import ActionKind, AutoSolver

    world = _world_board(board, mined)
    if world.mine_matrix[cell[0]][cell[1]] == MINE:
        return False
    if world.expansion(*cell)[0] is Status.WIN:
        return True

    solver = AutoSolver(world, config=config or _rollout_config(), log=log, rng=rng)
    for step, action in enumerate(solver.actions()):
        if step >= MAX_STEPS:
            break
        if action.kind is ActionKind.OPEN:
            status, _ = world.expansion(*action.position)
        else:
            status = world.mark_mine(*action.position)
        if status is Status.WIN:
            return True
        if status is Status.FAIL:
            return False
    return world.is_won()


def estimate(
    board: Board,
    cell: Position,
    layouts: Sequence[Set[Position]],
    config=None,
    log: Optional[logging.Logger] = None,
) -> float:
    """在若干张后验雷图上估计"打开这一格"的胜率。"""

    if not layouts:
        return 0.0
    wins = sum(1 for mined in layouts if simulate(board, mined, cell, config=config, log=log))
    return wins / len(layouts)


def choose_open(
    board: Board,
    table: TableLike,
    system=None,
    samples: int = DEFAULT_SAMPLES,
    candidates: int = DEFAULT_CANDIDATES,
    band: float = DEFAULT_BAND,
    rng: Optional[random.Random] = None,
    config=None,
    log: Optional[logging.Logger] = None,
) -> Optional[Tuple[Position, float]]:
    """挑"打开之后胜率最高"的格子，返回 ``(位置, 估计胜率)``。

    候选只取最安全的一小撮（默认"最低概率 + ``band`` 以内"，再截到
    ``candidates`` 个）——安全差距太大的格子，rollout 也救不回来，不必花
    模拟预算。
    """

    if not table:
        return None
    ordered = sorted(table.items(), key=lambda item: (item[1], item[0]))
    floor = ordered[0][1]
    pool = [(position, value) for position, value in ordered if value <= floor + band]
    pool = pool[:candidates]
    if not pool:
        return None

    if system is None:
        system = frontier.build_system(board)
    layouts: List[Set[Position]] = []
    for _ in range(samples):
        mined = frontier.sample_mines(system, rng=rng)
        if mined is not None:
            layouts.append(mined)
    if not layouts:
        return None

    best: Optional[Tuple[Position, float]] = None
    for position, value in pool:
        score = estimate(board, position, layouts, config=config, log=log)
        if best is None or score > best[1]:
            best = (position, score)
    return best


def blank_cell(
    board: Board,
    system=None,
    region_min: int = DEFAULT_REGION_MIN,
    log: Optional[logging.Logger] = None,
) -> Optional[Position]:
    """挑"最大空区里最靠前的一格"，只在空区够大时返回。

    这是 EdLogg 的 super location 的极简版：不挨着任何已翻开格子、因此完全
    不受约束的空白格，赌一次能炸开整整一片，把大片未知变成确定信息。
    """

    from .guess import _unknown_regions

    if system is None:
        system = frontier.build_system(board)
    regions = _unknown_regions(board)
    free = set(system.free)
    best: Optional[Tuple[int, Position]] = None
    for position, size in regions.items():
        if position not in free:
            continue
        if size < region_min:
            continue
        if best is None or size > best[0] or (size == best[0] and position < best[1]):
            best = (size, position)
    if best is None:
        return None
    if log is not None:
        log.debug("空区候选 %s（区域 %d 格）", best[1], best[0])
    return best[1]


def choose_gamble(
    board: Board,
    table: TableLike,
    system=None,
    samples: int = DEFAULT_SAMPLES,
    region_min: int = DEFAULT_REGION_MIN,
    rng: Optional[random.Random] = None,
    config=None,
    log: Optional[logging.Logger] = None,
) -> Optional[Tuple[Position, float]]:
    """比较"最安全的边沿格"和"最大空区的一次赌博"，模拟胜率更高者胜出。

    与小节里的 ``choose_open`` 不同，这里刻意只放两个候选：一个是现在的
    默认选择（最低雷概率），一个是"完全不受约束的空白格"。前者在单步上更
    安全，后者可能一口气炸开一大片、把后面的猜测省掉——用 rollout 直接比
    这两条路的整局胜率，而不是用"能连锁几格"这种代理指标。

    只有当赌博的模拟胜率**严格更高**时才返回，否则返回 ``None`` 让调用方
    走默认的 ``min_prob``（这样在赌博不占优时行为与基线逐格一致）。
    """

    if not table:
        return None
    position_a, _ = min(table.items(), key=lambda item: (item[1], item[0]))

    if system is None:
        system = frontier.build_system(board)
    candidate = blank_cell(board, system, region_min=region_min, log=log)
    if candidate is None or candidate == position_a:
        return None

    layouts: List[Set[Position]] = []
    for _ in range(samples):
        mined = frontier.sample_mines(system, rng=rng)
        if mined is not None:
            layouts.append(mined)
    if not layouts:
        return None

    score_a = estimate(board, position_a, layouts, config=config, log=log)
    score_b = estimate(board, candidate, layouts, config=config, log=log)
    if log is not None:
        log.info(
            "赌博评估：边沿 %s≈%.3f vs 空区 %s≈%.3f",
            position_a,
            score_a,
            candidate,
            score_b,
        )
    if score_b > score_a:
        return candidate, score_b
    return None
