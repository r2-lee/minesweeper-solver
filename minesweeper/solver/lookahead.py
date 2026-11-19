"""在边沿的"信念集合"上做多步期望搜索，用来决定猜哪一格。

和 :mod:`minesweeper.solver.endgame` 的区别
------------------------------------------
``endgame`` 要把**整盘**展开成雷图（边沿配置 × 空白格组合），所以只有未知格很少时才
用得上；而中盘的未知格动辄 50~90 个，永远进不去。

这里只把**边沿**展开成雷图：每个自洽的边沿配置是一个"世界"，它出现的权重是
``C(空白格数, 余雷数)``——空白格之间完全对称，不需要逐个枚举。于是"未知格 60 个、
边沿 20 个"的中盘也能精确做期望搜索。

搜索方式与 ``endgame`` 一样：对每个候选格，按"开出来看到什么数字"把世界分组，
``value = Σ 组权重/总权重 × 后续价值``；深度 1 就退化成"挑最安全的格"（``min_prob``），
深度 2~3 才能看出"这格看起来安全，但开完还是得赌"。

观测是"这一格的数字"，不模拟连锁展开——连锁会一路开进空白区，那部分由空白格密度
解析地表示，不逐格模拟。这是本模块唯一的近似。
"""

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .frontier import build_system, _split_components
from .endgame import _component_configurations

Position = Tuple[int, int]
World = frozenset


class _Budget(Exception):
    """搜索节点超预算（内部用）。"""


def _weighted_worlds(system, limit: int):
    """枚举边沿的所有自洽配置，并给出各自的权重。"""

    grouped = _split_components(system.constraints)
    parts = []
    for cells, constraints in grouped:
        configurations = _component_configurations(cells, constraints, limit)
        if not configurations:
            return None, None
        parts.append(configurations)

    free_count = len(system.free)
    total = system.total_mines

    if not parts:
        # 边沿是空的：全部未知格都是空白格，交给密度处理。
        return None, None

    worlds: List[World] = []
    weights: List[int] = []
    for combo in _product(parts):
        used = sum(len(part) for part in combo)
        rest = total - used
        if rest < 0 or rest > free_count:
            continue
        worlds.append(frozenset().union(*(tuple(combo) + (frozenset(),))))
        weights.append(math.comb(free_count, rest))
        if len(worlds) > limit:
            return None, None
    if not worlds:
        return None, None
    return worlds, weights


def _product(parts: Sequence[Sequence[World]]) -> Iterable[Tuple[World, ...]]:
    if not parts:
        yield ()
        return
    head, rest = parts[0], parts[1:]
    for item in head:
        for tail in _product(rest):
            yield (item,) + tail


def _number_at(world: World, position: Position) -> int:
    row, col = position
    count = 0
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row == 0 and d_col == 0:
                continue
            if (row + d_row, col + d_col) in world:
                count += 1
    return count


class _Searcher(object):
    """带权重的信念集合搜索。"""

    def __init__(self, worlds, weights, frontier, depth, node_limit, candidate_limit):
        self.worlds = worlds
        self.weights = weights
        self.frontier = tuple(frontier)
        self.depth = depth
        self.node_limit = node_limit
        self.candidate_limit = candidate_limit
        self.nodes = 0
        self.memo: Dict[Tuple[Tuple[int, ...], int], float] = {}

    def _candidates(self, state: Sequence[Tuple[int, int]]) -> List[Position]:
        """还有可能在"安全"分支里的边沿格，按最安全排序后取前几个。"""

        total = sum(weight for _, weight in state)
        scored = []
        for position in self.frontier:
            safe_weight = sum(w for index, w in state if position not in self.worlds[index])
            if safe_weight <= 0:
                continue
            scored.append((safe_weight / float(total), position))
        scored.sort(reverse=True)
        return [position for _, position in scored[: self.candidate_limit]]

    def value(self, state: Tuple[Tuple[int, int], ...], depth: int) -> float:
        key = (tuple(index for index, _ in state), depth)
        cached = self.memo.get(key)
        if cached is not None:
            return cached

        self.nodes += 1
        if self.nodes > self.node_limit:
            raise _Budget()

        if depth <= 0 or len(state) == 1:
            self.memo[key] = 1.0
            return 1.0

        total = sum(weight for _, weight in state)
        best = 0.0
        for position in self._candidates(state):
            safe = [(index, w) for index, w in state if position not in self.worlds[index]]
            if not safe:
                continue
            safe_weight = sum(w for _, w in safe)
            groups: Dict[int, List[Tuple[int, int]]] = {}
            for index, weight in safe:
                number = _number_at(self.worlds[index], position)
                groups.setdefault(number, []).append((index, weight))
            expectation = 0.0
            for members in groups.values():
                share = sum(w for _, w in members) / float(safe_weight)
                expectation += share * self.value(tuple(members), depth - 1)
            candidate_value = safe_weight / float(total) * expectation
            if candidate_value > best:
                best = candidate_value
        self.memo[key] = best
        return best

    def best_action(self) -> Tuple[Optional[Position], float]:
        state = tuple((index, self.weights[index]) for index in range(len(self.worlds)))
        total = sum(weight for _, weight in state)
        best_value = -1.0
        best_position = None
        for position in self._candidates(state):
            safe = [(index, w) for index, w in state if position not in self.worlds[index]]
            if not safe:
                continue
            safe_weight = sum(w for _, w in safe)
            groups: Dict[int, List[Tuple[int, int]]] = {}
            for index, weight in safe:
                number = _number_at(self.worlds[index], position)
                groups.setdefault(number, []).append((index, weight))
            expectation = 0.0
            for members in groups.values():
                share = sum(w for _, w in members) / float(safe_weight)
                expectation += share * self.value(tuple(members), self.depth - 1)
            candidate_value = safe_weight / float(total) * expectation
            if candidate_value > best_value:
                best_value = candidate_value
                best_position = position
        return best_position, best_value


def solve(
    board,
    system=None,
    depth: int = 2,
    world_limit: int = 3000,
    node_limit: int = 2000,
    candidate_limit: int = 12,
):
    """返回 ``(位置, 估计胜率)``；边沿太大/太碎时返回 ``None``。"""

    if system is None:
        system = build_system(board)
    if not system.consistent:
        return None
    if not system.frontier:
        return None
    if system.total_mines <= 0:
        return None

    worlds, weights = _weighted_worlds(system, world_limit)
    if not worlds:
        return None

    searcher = _Searcher(
        worlds, weights, system.frontier, depth, node_limit, candidate_limit
    )
    try:
        position, value = searcher.best_action()
    except _Budget:
        return None
    if position is None:
        return None
    return position, value
