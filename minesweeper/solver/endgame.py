"""端局精确求解：当"一致雷图"只剩几百张时，直接把胜率算出来再决定猜哪一格。

为什么要单独做这一层
--------------------
`min_prob` 只优化"这一步别死"，但一局棋往往要猜 2~3 次。端局的特点是：未知格没几
个、一致的雷图也没几张，于是可以**精确**地算：

    这一格开下去，活下来的那些雷图各自会看到什么数字？
    看到这些数字之后，剩下的雷图变成哪一小撮？
    那一小撮里，最好的走法还能赢多少？

也就是在"信念集合"（所有仍然自洽的雷图）上做期望最大的搜索。赌一次 50/50 之后如果
剩下的局面还是必须赌，胜率是 0.5×0.5；而端局搜索会自动挑那种"赌对了就全解开"的格子。

门槛
----
* 未知格不超过 ``CELL_LIMIT``：枚举雷图、模拟连锁展开都是按格数展开的；
* 一致雷图不超过 ``WORLD_LIMIT``：再大就不是端局了，逐张枚举本身就贵；
* 搜索节点不超过 ``NODE_LIMIT``：超了宁可退回 ``min_prob``，也别卡住界面。

三条都不满足时 :func:`solve` 返回 ``None``，调用方照旧走启发式。
"""

import itertools
from collections import deque
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from ..core.enums import DIRECTIONS
from .frontier import Constraint, build_system, _split_components

Position = Tuple[int, int]
World = FrozenSet[Position]

#: 未知格上限：再大就不算"端局"了。
CELL_LIMIT = 14
#: 一致雷图上限：逐张枚举的成本在这条线以上开始失控。
WORLD_LIMIT = 128
#: 搜索节点上限：超过就放弃精确解，退回启发式。
NODE_LIMIT = 400


class _Budget(Exception):
    """搜索节点超预算（内部用）。"""


def _neighbours(position: Position, rows: int, cols: int) -> Iterable[Position]:
    row, col = position
    for d_row, d_col in DIRECTIONS:
        n_row, n_col = row + d_row, col + d_col
        if 0 <= n_row < rows and 0 <= n_col < cols:
            yield (n_row, n_col)


def _component_configurations(
    cells: Sequence[Position],
    constraints: Sequence[Constraint],
    limit: int,
) -> Optional[List[World]]:
    """枚举一个组件里所有合法的雷位置组合；超过 ``limit`` 直接返回 ``None``。"""

    cell_index = {cell: index for index, cell in enumerate(cells)}
    touches: List[List[int]] = [[] for _ in cells]
    for constraint_id, constraint in enumerate(constraints):
        for position in constraint.positions:
            touches[cell_index[position]].append(constraint_id)

    placed = [0] * len(constraints)
    undecided = [len(constraint.positions) for constraint in constraints]
    chosen: List[Position] = []
    result: List[World] = []

    def search(index: int) -> bool:
        """返回 False 只表示"超出枚举上限"，不表示"这条分支不可行"。"""

        if len(result) > limit:
            return False
        if index == len(cells):
            for constraint_id, constraint in enumerate(constraints):
                if placed[constraint_id] != constraint.required:
                    return True
            result.append(frozenset(chosen))
            return True

        cell = cells[index]
        for is_mine in (False, True):
            if is_mine:
                chosen.append(cell)
            for constraint_id in touches[index]:
                undecided[constraint_id] -= 1
                if is_mine:
                    placed[constraint_id] += 1

            feasible = True
            for constraint_id in touches[index]:
                required = constraints[constraint_id].required
                if placed[constraint_id] > required or \
                        placed[constraint_id] + undecided[constraint_id] < required:
                    feasible = False
                    break

            ok = True
            if feasible:
                ok = search(index + 1)

            for constraint_id in touches[index]:
                undecided[constraint_id] += 1
                if is_mine:
                    placed[constraint_id] -= 1
            if is_mine:
                chosen.pop()

            if not ok:
                return False
        return True

    if not search(0):
        return None
    return result


def _worlds(system, limit: int) -> Optional[List[World]]:
    """把整个局面展开成"所有自洽的完整雷图"的列表，超过 ``limit`` 返回 ``None``。"""

    grouped = _split_components(system.constraints)
    parts: List[List[World]] = []
    for cells, constraints in grouped:
        configurations = _component_configurations(cells, constraints, limit)
        if configurations is None or not configurations:
            return None
        parts.append(configurations)

    free = list(system.free)
    total = system.total_mines

    # 先数一遍总量，避免白枚举。
    counts = [len(part) for part in parts]
    if not parts:
        return [frozenset(combo) for combo in itertools.combinations(free, total)] \
            if 0 <= total <= len(free) else None

    worlds: List[World] = []
    for combo in itertools.product(*parts):
        used = sum(len(part) for part in combo)
        rest = total - used
        if not 0 <= rest <= len(free):
            continue
        for extra in itertools.combinations(free, rest):
            worlds.append(frozenset().union(*(tuple(combo) + (set(extra),))))
            if len(worlds) > limit:
                return None
    return worlds


def _numbers(world: World) -> Dict[Position, int]:
    """按某张雷图，算出所有非雷格的数字。"""

    numbers: Dict[Position, int] = {}
    for position in world:
        row, col = position
        for n_row, n_col in ((row - 1, col - 1), (row - 1, col), (row - 1, col + 1),
                             (row, col - 1), (row, col + 1),
                             (row + 1, col - 1), (row + 1, col), (row + 1, col + 1)):
            numbers[(n_row, n_col)] = numbers.get((n_row, n_col), 0) + 1
    return numbers


def _reveal(
    world: World,
    numbers: Dict[Position, int],
    position: Position,
    revealed: FrozenSet[Position],
    rows: int,
    cols: int,
) -> Dict[Position, int]:
    """在雷图 ``world`` 上从 ``position`` 展开，返回（此前没见过的）格子与数字。"""

    opened: Dict[Position, int] = {}
    queue = deque([position])
    while queue:
        current = queue.popleft()
        if current in opened or current in revealed or current in world:
            continue
        number = numbers.get(current, 0)
        opened[current] = number
        if number == 0:
            for neighbour in _neighbours(current, rows, cols):
                if neighbour not in opened and neighbour not in revealed and neighbour not in world:
                    queue.append(neighbour)
    return opened


class _Search:
    """在信念集合上做期望最大的搜索。"""

    def __init__(self, board, worlds: List[World], unknown: Sequence[Position],
                 total_mines: int, node_limit: int) -> None:
        self.rows, self.cols = board.rows, board.cols
        self.worlds = worlds
        self.unknown = tuple(unknown)
        self.total_mines = total_mines
        self.node_limit = node_limit
        self.nodes = 0
        self.memo: Dict[Tuple[Tuple[int, ...], FrozenSet[Position]], float] = {}
        self.numbers = [_numbers(world) for world in worlds]
        self.cascades: Dict[Tuple[int, Position], Tuple[Tuple[Position, int], ...]] = {}

    def observation(self, index: int, candidate: Position) -> Tuple[Tuple[Position, int], ...]:
        """在雷图 ``index`` 上开 ``candidate`` 会看到什么（带缓存）。

        缓存不区分"已经开过的格子"：连锁展开穿过一个已开的 0 格时，它当初就已经
        展开过了，所以"整条连锁里新开的格" = 整条连锁 − 已开格。
        """

        key = (index, candidate)
        cached = self.cascades.get(key)
        if cached is None:
            opened = _reveal(self.worlds[index], self.numbers[index], candidate,
                             frozenset(), self.rows, self.cols)
            cached = tuple(sorted(opened.items()))
            self.cascades[key] = cached
        return cached

    def value(self, indices: Tuple[int, ...], revealed: FrozenSet[Position]) -> float:
        key = (indices, revealed)
        cached = self.memo.get(key)
        if cached is not None:
            return cached

        self.nodes += 1
        if self.nodes > self.node_limit:
            raise _Budget()

        representative = self.worlds[indices[0]]
        hidden_safe = [p for p in self.unknown if p not in revealed and p not in representative]
        if not hidden_safe or len(indices) == 1:
            self.memo[key] = 1.0
            return 1.0

        best = 0.0
        for candidate in self.unknown:
            if candidate in revealed:
                continue
            survivors = [index for index in indices if candidate not in self.worlds[index]]
            if not survivors:
                continue
            groups: Dict[Tuple[Tuple[Position, int], ...], List[int]] = {}
            for index in survivors:
                groups.setdefault(self.observation(index, candidate), []).append(index)
            total = 0.0
            for observation, members in groups.items():
                child_revealed = revealed | frozenset(position for position, _ in observation)
                total += len(members) / len(indices) * self.value(tuple(members), child_revealed)
            if total > best:
                best = total
        self.memo[key] = best
        return best

    def best_action(self) -> Optional[Position]:
        indices = tuple(range(len(self.worlds)))
        best_value = -1.0
        best_position: Optional[Position] = None
        revealed: FrozenSet[Position] = frozenset()
        for candidate in self.unknown:
            survivors = [index for index in indices if candidate not in self.worlds[index]]
            if not survivors:
                continue
            groups: Dict[Tuple[Tuple[Position, int], ...], List[int]] = {}
            for index in survivors:
                groups.setdefault(self.observation(index, candidate), []).append(index)
            total = 0.0
            for observation, members in groups.items():
                child_revealed = revealed | frozenset(position for position, _ in observation)
                total += len(members) / len(indices) * self.value(tuple(members), child_revealed)
            if total > best_value:
                best_value = total
                best_position = candidate
        self.best_value = best_value
        return best_position


def solve(board, system=None, cell_limit: int = CELL_LIMIT,
          world_limit: int = WORLD_LIMIT, node_limit: int = NODE_LIMIT):
    """返回 ``(位置, 胜率估计)``，局面太大/太复杂时返回 ``None``。

    只考虑"打开某个未知格"这一种动作：``solve`` 只在没有确定动作、必须猜的时候被调用。
    """

    if system is None:
        system = build_system(board)
    if not system.consistent:
        return None
    unknown = system.unknown
    if not unknown or len(unknown) > cell_limit:
        return None
    total = system.total_mines
    if total < 0 or total > len(unknown):
        return None
    if total == 0:
        return None  # 没有雷，交给确定动作处理

    worlds = _worlds(system, world_limit)
    if not worlds or len(worlds) > world_limit:
        return None

    search = _Search(board, worlds, unknown, total, node_limit)
    try:
        position = search.best_action()
    except _Budget:
        return None
    if position is None:
        return None
    return position, search.best_value
