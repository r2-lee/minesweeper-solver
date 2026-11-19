"""按"信息价值"给并列候选打分（精确条件计数，不采样）。

思路：一个候选格的整局价值

    V(c) = Σ_k P(c 安全且翻出 k) · Q(条件于 k 的续局价值)

`P(c 安全且翻出 k)` 用 :mod:`frontier` 的组件枚举 + 总雷数卷积**精确**算出
（不需要蒙特卡洛），`Q` 用"这一支里是否出现确定格 / 下一手最安全能有多少存活率"
这个便宜代理。这比 ``guess.choose_open_progress`` 的采样估计准，也是 Hill 的
``SecondarySafetyEvaluator`` 在做的事，只是他采样、我们数精确值。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from ..core.enums import DIRECTIONS, Mark
from ..core.geometry import Position
from . import frontier as _frontier
from .frontier import Constraint, ConstraintSystem, FrontierTooLarge, ProbabilityTable

MINE_CLUE = 9  # 踩雷的"观测值"

DEFAULT_CANDIDATES = 5
DEFAULT_BAND = 0.02
# 本模块内部枚举一律用**小**预算：它是在"每个候选 × 每个观测分支"里被反复调用的，
# 一旦沿用原生加速器的 2000 万节点默认预算，单个决策可能跑几秒（实测会在少数局上
# 拖出上百秒的尾巴）。算不完就退回最安全格，这个取舍对胜负没有影响。
DEFAULT_NODES = 200_000
DEFAULT_TIME_LIMIT = 0.05  # 秒；单个决策允许花在评估候选上的总时间
DEFAULT_BRANCHES = 6  # 每个候选最多展开几个观测分支（按概率从大到小）
BRANCH_MASS = 0.01  # 概率低于这个值的观测分支直接丢掉


def _unknown_neighbours(system: ConstraintSystem, position: Position) -> Tuple[Position, ...]:
    row, col = position
    unknown = set(system.unknown)
    cells: List[Position] = []
    for d_row, d_col in DIRECTIONS:
        near = (row + d_row, col + d_col)
        if near in unknown:
            cells.append(near)
    return tuple(cells)


def _component_of(system: ConstraintSystem, position: Position):
    """返回 (组件格, 组件约束, 其余组件枚举结果) —— 只处理边沿格。"""
    split = _frontier._split_components(system.constraints)
    for cells, constraints in split:
        if position in cells:
            return cells, constraints, split
    return None


def _free_observation(
    system: ConstraintSystem,
    position: Position,
    budget: Optional[int] = None,
) -> Optional[Dict[int, float]]:
    """空白格的近似观测：邻格各自独立（边沿用边际概率、空白用密度）。"""
    if budget is None:
        budget = DEFAULT_NODES
    try:
        marginals = _frontier.probabilities(system, budget)
    except (FrontierTooLarge, ValueError):
        return None
    if not marginals:
        return None
    density = marginals.get(position, 0.0)
    if not 0.0 <= density <= 1.0:
        return None
    risks = [marginals.get(cell, 0.0) for cell in _unknown_neighbours(system, position)]
    distribution: Dict[int, float] = {}
    safety = 1.0 - density
    if safety > 0.0:
        for count, probability in _bernoulli(risks):
            distribution[count] = distribution.get(count, 0.0) + safety * probability
    if density > 0.0:
        distribution[MINE_CLUE] = distribution.get(MINE_CLUE, 0.0) + density
    return distribution or None


def observation_distribution(
    system: ConstraintSystem,
    position: Position,
    budget: Optional[int] = None,
) -> Optional[Dict[int, float]]:
    """``{观测值: 概率}``，观测值 0..8 = 翻出的数字，``MINE_CLUE`` = 踩雷。

    只支持边沿格（空白格的观测要么是 0、要么靠采样，交给调用方走别的路径）。
    返回 None 表示算不了（超预算 / 不是边沿格 / 约束矛盾）。
    """
    if budget is None:
        budget = DEFAULT_NODES
    if not system.consistent or position not in system.unknown:
        return None

    if position in system.free:
        return _free_observation(system, position, budget)

    found = _component_of(system, position)
    if found is None:
        return None
    cells, constraints, split = found

    from .endgame import _component_configurations  # 复用组件枚举（返回配置集合）

    try:
        configs = _component_configurations(cells, constraints, budget)
    except (ValueError, _frontier.FrontierTooLarge):
        return None
    if not configs:
        return None

    try:
        components = system.components(budget)
    except (FrontierTooLarge, ValueError):
        return None

    target = cells
    others = [component for component in components if component.positions != target]
    free = system.free
    total = system.total_mines
    totals = _frontier._convolve(others, total)
    grand_total = _frontier._with_free(totals, len(free), total)
    if grand_total <= 0:
        return None

    neighbours = _unknown_neighbours(system, position)
    near = set(neighbours)
    free_near = [cell for cell in free if cell in near]
    other_near = [cell for cell in near if cell not in set(cells) and cell not in set(free_near)]
    # 极少见：邻居落在别的组件里。用边际概率当作独立伯努利近似（对所有候选一视同仁）。
    marginals = _frontier.probabilities(system, budget)
    other_risks = [marginals.get(cell, 0.0) for cell in other_near]

    distribution: Dict[int, float] = {}

    def add(observed: int, weight: float) -> None:
        if weight:
            distribution[observed] = distribution.get(observed, 0.0) + weight

    for config in configs:
        mines_in = len(config)
        base = 0
        for used, ways in totals.items():
            remaining = total - used - mines_in
            if 0 <= remaining <= len(free):
                base += ways * _frontier._comb(len(free), remaining)
        if not base:
            continue

        if position in config:
            add(MINE_CLUE, base)
            continue

        inside = len(near & set(config))
        # 空白邻居里有多少颗雷是超几何分布；再叠加"别的组件邻居"的独立近似。
        for used, ways in totals.items():
            remaining = total - used - mines_in
            if not 0 <= remaining <= len(free):
                continue
            weight = ways * _frontier._comb(len(free), remaining)
            head = _frontier._comb(len(free) - len(free_near), 0)  # 占位，下面按超几何展开
            del head
            for taken in range(0, min(len(free_near), remaining) + 1):
                rest = remaining - taken
                if rest > len(free) - len(free_near):
                    continue
                share = (
                    _frontier._comb(len(free_near), taken)
                    * _frontier._comb(len(free) - len(free_near), rest)
                )
                if not share:
                    continue
                for extra, risk in _bernoulli(other_risks):
                    add(inside + taken + extra, weight * share / _frontier._comb(len(free), remaining) * risk)

    total_probability = sum(distribution.values())
    if total_probability <= 0:
        return None
    return {key: value / total_probability for key, value in distribution.items()}


def _bernoulli(risks: List[float]):
    """把若干独立伯努利展开成 (雷数, 概率) 列表；没邻居时就是 [(0, 1.0)]。"""
    outcomes = [(0, 1.0)]
    for risk in risks:
        nxt = []
        for count, probability in outcomes:
            nxt.append((count, probability * (1.0 - risk)))
            nxt.append((count + 1, probability * risk))
        outcomes = nxt
    return [(count, probability) for count, probability in outcomes if probability > 1e-12]


def conditional_system(
    system: ConstraintSystem,
    position: Position,
    observed: int,
    budget: Optional[int] = None,
) -> Optional[ConstraintSystem]:
    """在"该格安全且翻出 observed"的条件下重建约束系统。"""
    neighbours = _unknown_neighbours(system, position)
    if observed < 0 or observed > len(neighbours):
        return None
    extra = [Constraint((position,), 0)]
    if neighbours:
        extra.append(Constraint(neighbours, observed))
    constraints = tuple(system.constraints) + tuple(extra)
    frontier_cells: List[Position] = []
    seen = set()
    for constraint in constraints:
        for cell in constraint.positions:
            if cell not in seen:
                seen.add(cell)
                frontier_cells.append(cell)
    free = tuple(cell for cell in system.free if cell not in seen)
    return ConstraintSystem(constraints, tuple(frontier_cells), free, system.total_mines)


def candidate_value(
    system: ConstraintSystem,
    position: Position,
    budget: Optional[int] = None,
) -> Optional[float]:
    """候选的期望续局价值：Σ_k P(k) · Q(k)；算不了返回 None。"""
    distribution = observation_distribution(system, position, budget)
    if not distribution:
        return None
    # 只展开最可能的那几个观测分支：低概率分支贡献 <1%，却要把整套卷积再跑一遍。
    branches = sorted(
        ((observed, probability) for observed, probability in distribution.items()
         if observed != MINE_CLUE and probability >= BRANCH_MASS),
        key=lambda item: -item[1],
    )[:DEFAULT_BRANCHES]
    if not branches:
        return None
    value = 0.0
    for observed, probability in branches:
        conditioned = conditional_system(system, position, observed)
        if conditioned is None:
            continue
        try:
            table = _frontier.probabilities(conditioned, budget)
        except (FrontierTooLarge, ValueError):
            continue
        if not table:
            continue
        # Q 用"条件局面里下一手最安全的存活率"。原先这里还有一个
        # ``has_certainty -> 1.0`` 的捷径，是把"出现了 0/1"直接当成赢：它会把
        # 只标出几颗雷、下一手照样得赌的局面也算成满分，实测让 informed 的
        # 增益从 +0.7 点掉到 +0.17 点。去掉之后 Q 就只依赖真实的下一手风险。
        next_survival = 1.0 - min(table.values())
        value += probability * next_survival
    return value


def choose_open_informed(
    board,
    table: ProbabilityTable,
    system: Optional[ConstraintSystem] = None,
    candidates: int = DEFAULT_CANDIDATES,
    band: float = DEFAULT_BAND,
    budget: Optional[int] = None,
    time_limit: float = DEFAULT_TIME_LIMIT,
    log=None,
) -> Optional[Tuple[Position, float]]:
    """在"最低概率 + band"的候选里挑条件期望最高的一格。"""
    if budget is None:
        budget = DEFAULT_NODES
    if not table:
        return None
    if system is None:
        system = _frontier.build_system(board)
    if not system.consistent:
        return None

    lowest = min(table.values())
    pool = [
        (position, probability)
        for position, probability in table.items()
        if probability <= lowest + band and probability < 1.0
    ]
    pool.sort(key=lambda item: (item[1], item[0]))
    pool = pool[:candidates]
    if not pool:
        return None

    deadline = time.perf_counter() + time_limit
    best: Optional[Tuple[Position, float]] = None
    scored: List[Tuple[Position, float]] = []
    for position, _probability in pool:
        if time.perf_counter() > deadline:
            break
        value = candidate_value(system, position, budget)
        if value is None:
            continue
        scored.append((position, value))
        if best is None or value > best[1] + 1e-12:
            best = (position, value)

    baseline = pool[0][0]
    if best is not None and log is not None:
        log.debug(
            "信息评估：基线 %s，选中 %s（%d 个候选，%.4f）",
            baseline,
            best[0],
            len(scored),
            best[1],
        )
    return best
