"""复刻 EdLogg 的 *game tree* 选格：把边沿的所有自洽配置当世界，做**完整**递归的期望最大化。

和 :mod:`minesweeper.solver.lookahead` 的区别
--------------------------------------------
``lookahead`` 是"截断深度的近似"：深度一到就用乐观值 1.0 收尾，于是它系统性高估
"清完边沿就赢了"的情况。这里的 ``value`` 一直递归到**边沿被清空**，叶节点用"剩余雷全
在空白区、按密度逐次点开"的概率收尾，所以它算的是"这盘棋真的赢下来的概率"。

状态 = (还活着的世界下标, 已经点开的边沿格)。世界下标只减不增，所以可以 memo。
"""

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .endgame import _component_configurations
from .frontier import ConstraintSystem, _split_components, build_system

Position = Tuple[int, int]
World = frozenset

# 空白区每点一次平均能扫开多少格（用它把"还要点几手"折算成一次乘方）。
BLANK_REGION = 40.0


class _Budget(Exception):
    """搜索超预算（内部用）。"""


def _product(parts: Sequence[Sequence[World]]) -> Iterable[Tuple[World, ...]]:
    if not parts:
        yield ()
        return
    for item in parts[0]:
        for tail in _product(parts[1:]):
            yield (item,) + tail


def weighted_worlds(system, limit: int):
    """返回 ``(worlds, weights, free_count, total_mines)``；边沿太大时返回 ``(None, ...)``。"""

    grouped = _split_components(system.constraints)
    parts = []
    for cells, constraints in grouped:
        configurations = _component_configurations(cells, constraints, limit)
        if not configurations:
            return None, None, 0, 0
        parts.append(configurations)

    free_count = len(system.free)
    total = system.total_mines
    if not parts:
        return None, None, free_count, total

    worlds: List[World] = []
    weights: List[int] = []
    for combo in _product(parts):
        used = sum(len(part) for part in combo)
        rest = total - used
        if rest < 0 or rest > free_count:
            continue
        worlds.append(frozenset().union(*combo))
        weights.append(math.comb(free_count, rest))
        if len(worlds) > limit:
            return None, None, free_count, total
    if not worlds:
        return None, None, free_count, total
    return worlds, weights, free_count, total


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


class _Tree(object):
    def __init__(self, worlds, weights, frontier, free_count, total_mines,
                 node_limit, candidate_limit):
        self.worlds = worlds
        self.weights = weights
        self.frontier = tuple(frontier)
        self.free_count = free_count
        self.total_mines = total_mines
        self.node_limit = node_limit
        self.candidate_limit = candidate_limit
        self.nodes = 0
        self.memo: Dict[Tuple[Tuple[int, ...], Tuple[Position, ...], int], float] = {}

    def _blank_value(self, state) -> float:
        """边沿已清空时的期望：空白区的雷按密度均摊。"""

        if self.free_count <= 0:
            return 1.0
        total_weight = sum(weight for _, weight in state)
        if total_weight <= 0:
            return 0.0
        placed = sum(weight * sum(1 for p in self.worlds[index] if p in self._frontier_set)
                     for index, weight in state)
        placed /= float(total_weight)
        rest = max(0.0, self.total_mines - placed)
        density = min(0.95, rest / float(self.free_count))
        if density <= 0.0:
            return 1.0
        hands = max(1.0, self.free_count / BLANK_REGION)
        return max(0.0, (1.0 - density) ** hands)

    @property
    def _frontier_set(self):
        cached = getattr(self, "_cached_frontier_set", None)
        if cached is None:
            cached = frozenset(self.frontier)
            self._cached_frontier_set = cached
        return cached

    def _candidates(self, state, opened):
        total = sum(weight for _, weight in state)
        if total <= 0:
            return []
        scored = []
        for position in self.frontier:
            if position in opened:
                continue
            safe_weight = sum(w for index, w in state if position not in self.worlds[index])
            if safe_weight <= 0:
                continue
            scored.append((safe_weight / float(total), position))
        scored.sort(reverse=True)
        return [position for _, position in scored[: self.candidate_limit]]

    def value(self, state, opened) -> float:
        key = (tuple(index for index, _ in state), tuple(sorted(opened)), 0)
        cached = self.memo.get(key)
        if cached is not None:
            return cached

        self.nodes += 1
        if self.nodes > self.node_limit:
            raise _Budget()

        if len(state) == 1:
            self.memo[key] = 1.0
            return 1.0

        candidates = self._candidates(state, opened)
        if not candidates:
            result = self._blank_value(state)
            self.memo[key] = result
            return result

        total = sum(weight for _, weight in state)
        best = 0.0
        for position in candidates:
            safe = [(index, w) for index, w in state if position not in self.worlds[index]]
            if not safe:
                continue
            safe_weight = sum(w for _, w in safe)
            groups: Dict[int, List[Tuple[int, int]]] = {}
            for index, weight in safe:
                groups.setdefault(_number_at(self.worlds[index], position), []).append((index, weight))
            expectation = 0.0
            for members in groups.values():
                share = sum(w for _, w in members) / float(safe_weight)
                expectation += share * self.value(tuple(members), opened | {position})
            candidate_value = safe_weight / float(total) * expectation
            if candidate_value > best:
                best = candidate_value
        # 也有可能"往空白区点一下"比清边沿更好——按密度估一个下界参与比较。
        if self.free_count > 0:
            total_weight = sum(weight for _, weight in state)
            placed = sum(weight * sum(1 for p in self.worlds[index] if p in self._frontier_set)
                         for index, weight in state) / float(total_weight)
            rest = max(0.0, self.total_mines - placed)
            density = min(0.95, rest / float(self.free_count))
            blank = (1.0 - density) * self._blank_value(state) ** 0.8
            if blank > best:
                best = blank
        self.memo[key] = best
        return best

    def best_action(self):
        state = tuple((index, self.weights[index]) for index in range(len(self.worlds)))
        opened = frozenset()
        candidates = self._candidates(state, opened)
        if not candidates:
            return None, 0.0
        total = sum(weight for _, weight in state)
        best_value = -1.0
        best_position = None
        for position in candidates:
            safe = [(index, w) for index, w in state if position not in self.worlds[index]]
            if not safe:
                continue
            safe_weight = sum(w for _, w in safe)
            groups: Dict[int, List[Tuple[int, int]]] = {}
            for index, weight in safe:
                groups.setdefault(_number_at(self.worlds[index], position), []).append((index, weight))
            expectation = 0.0
            for members in groups.values():
                share = sum(w for _, w in members) / float(safe_weight)
                expectation += share * self.value(tuple(members), opened | {position})
            candidate_value = safe_weight / float(total) * expectation
            if candidate_value > best_value:
                best_value = candidate_value
                best_position = position
        return best_position, best_value


def solve(
    board,
    system=None,
    world_limit: int = 1000,
    node_limit: int = 20000,
    candidate_limit: int = 10,
):
    """返回 ``(位置, 估计胜率)``；边沿太大、或者算不出时返回 ``None``。"""

    if system is None:
        system = build_system(board)
    if not system.consistent or not system.frontier or system.total_mines <= 0:
        return None

    worlds, weights, free_count, total_mines = weighted_worlds(system, world_limit)
    if not worlds:
        return None

    tree = _Tree(worlds, weights, system.frontier, free_count, total_mines,
                 node_limit, candidate_limit)
    try:
        position, value = tree.best_action()
    except _Budget:
        return None
    if position is None:
        return None
    return position, value


def solve_pinned(
    board,
    system=None,
    world_limit: int = 2000,
    node_limit: int = 20000,
    candidate_limit: int = 8,
):
    """只在"雷数已被钉死"的连通组件里做期望搜索，返回 ``(位置, 价值)`` 或 ``None``。

    这是他 ``UseGameTree`` 早跑分支的对应物：只要某个周长列表的自洽配置雷数唯一
    （``listMinMines == listMaxMines``），就单独对它做深搜；不必等整个棋盘进入残局。
    """

    if system is None:
        system = build_system(board)

    best = None
    for cells, constraints in _split_components(system.constraints):
        configurations = _component_configurations(cells, constraints, world_limit)
        if not configurations:
            continue
        counts = set(len(world) for world in configurations)
        if len(counts) != 1:
            continue
        mines = counts.pop()
        mini = ConstraintSystem(
            constraints=list(constraints),
            frontier=list(cells),
            free=[],
            total_mines=mines,
        )
        result = solve(
            board,
            mini,
            world_limit=world_limit,
            node_limit=node_limit,
            candidate_limit=candidate_limit,
        )
        if result is None:
            continue
        position, value = result
        if best is None or value > best[1]:
            best = (position, value)
    return best

