"""全盘精确边际概率：边沿组件分解 + 总雷数卷积。

问题
----
局部窗口法（``local.py``）只看每个数字格周围 5x5 的范围，两个数字格之间的
联合约束、以及"远离边沿的空白格"的信息都被丢掉了，于是概率只是启发式估计，
还可能出现"该格其实必然安全却没有被发现"的漏推理。

做法
----
把当前棋盘抽象成一组**线性约束**：每个已打开的数字格 n 要求它八邻域里
未打开（且未被标雷）的格子里恰好有 ``n - (周围已标雷数)`` 颗雷。

1. 这些约束把"边沿格"（至少出现在一条约束里的未知格）按**连通性**分解成
   若干互不相交的组件；组件之间没有共享格，因此在给定组件内部雷数时相互独立。
2. 对每个组件穷举所有满足其约束的布雷方案，按"组件雷数 k"聚合：
   ``ways[k]`` = 该组件有 k 颗雷的方案数；
   ``cell_ways[格][k]`` = 其中该格是雷的方案数。
3. 用动态规划把各组件按雷数卷积，再乘上"完全不受约束的空白格"的组合数
   ``C(空白格数, 剩余雷数 - 已用雷数)``，得到全盘合法雷图总数 T。
4. 对每个格子，把"该格是雷"的合法雷图数除以 T，就是**精确后验概率**；
   空白格之间完全对称，概率等于 ``(总雷数 - 组件期望雷数) / 空白格数``。

复杂度取决于**最大组件**的规模，而不是全盘未知格数，所以高级盘（240 个未知格）
也能算：常见局面下组件只有几格。组件过大时抛 :class:`FrontierTooLarge`，
由调用方退回到局部窗口法。
"""

import random
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from math import comb
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from ..core.enums import DIRECTIONS, Mark
from ..core.geometry import Position, iter_positions, neighbours
from . import accelerator
from .probability import ProbabilityTable
from .window import board_values

DEFAULT_BUDGET = 400_000

#: 边沿格数不超过这个值时，雷图采样用精确均匀抽样；更大的局面退回有偏的 DFS
#: 采样（一次采样要枚举几十次，大组件太慢）。
UNIFORM_LIMIT = 150
NATIVE_BUDGET = 20_000_000


def default_budget() -> int:
    """节点预算：装了原生加速器时放宽，因为单节点便宜 200 倍以上。"""
    return NATIVE_BUDGET if accelerator.available() else DEFAULT_BUDGET


class FrontierTooLarge(RuntimeError):
    """组件枚举超出预算（说明这个局面不适合精确求解）。"""


@dataclass(frozen=True)
class Constraint:
    """一条约束：``positions`` 这些未知格里恰好有 ``required`` 颗雷。"""

    positions: Tuple[Position, ...]
    required: int

    def __post_init__(self) -> None:
        if self.required < 0 or self.required > len(self.positions):
            raise ValueError("约束无解：required=%d, cells=%d" % (self.required, len(self.positions)))


@dataclass
class Component:
    """一个连通的边沿组件及其枚举结果。"""

    positions: Tuple[Position, ...]
    ways: Dict[int, int]
    cell_ways: Dict[Position, Dict[int, int]]

    @property
    def size(self) -> int:
        return len(self.positions)

    @property
    def mine_counts(self) -> List[int]:
        return sorted(self.ways)

    def configurations(self) -> int:
        return sum(self.ways.values())


@dataclass
class ConstraintSystem:
    """某一时刻棋盘的完整约束模型。"""

    constraints: Tuple[Constraint, ...]
    frontier: Tuple[Position, ...]
    free: Tuple[Position, ...]
    total_mines: int
    consistent: bool = True

    @property
    def unknown(self) -> Tuple[Position, ...]:
        return self.frontier + self.free

    def components(self, budget: Optional[int] = None) -> List[Component]:
        """按连通性切分边沿并逐个枚举。"""
        if budget is None:
            budget = default_budget()
        return [_enumerate_component(cells, constraints, budget)
                for cells, constraints in _split_components(self.constraints)]


def build_system(board, values: Optional[List[List[int]]] = None) -> ConstraintSystem:
    """从棋盘状态提取约束系统。

    ``values`` 可以复用调用方已经算好的 ``board_values(board)``，省一次遍历。

    这里是自动计算最热的函数之一（每走一步都要重建整盘的约束），所以内层循环
    用显式的行列下标而不是 ``neighbours()`` 生成器：生成器的 yield 开销在
    40 局剖析里占了 1.6M 次调用，换掉之后能省下约一成时间。
    """
    if values is None:
        values = board_values(board)
    rows, cols = board.rows, board.cols

    constraints: List[Constraint] = []
    for row in range(rows):
        value_row = values[row]
        for col in range(cols):
            number = value_row[col]
            if number < 1:  # 未开(=0)、标雷(-1)、空白(-10) 都不是数字格
                continue
            unknown: List[Position] = []
            flagged = 0
            for d_row, d_col in DIRECTIONS:
                near = row + d_row
                side = col + d_col
                if near < 0 or near >= rows or side < 0 or side >= cols:
                    continue
                value = values[near][side]
                if value == 0:
                    unknown.append((near, side))
                elif value == -1:
                    flagged += 1
            required = number - flagged
            if required < 0 or required > len(unknown):
                return ConstraintSystem((), (), (), board.remain_mine(), consistent=False)
            if unknown:
                constraints.append(Constraint(tuple(unknown), required))

    frontier: List[Position] = []
    seen = set()
    for constraint in constraints:
        for position in constraint.positions:
            if position not in seen:
                seen.add(position)
                frontier.append(position)

    free: List[Position] = []
    for row in range(rows):
        value_row = values[row]
        for col in range(cols):
            if value_row[col] == 0 and (row, col) not in seen:
                free.append((row, col))

    return ConstraintSystem(tuple(constraints), tuple(frontier), tuple(free), board.remain_mine())


def _split_components(constraints: Sequence[Constraint]) -> List[Tuple[Tuple[Position, ...], List[Constraint]]]:
    """并查集：共享格子的约束属于同一组件。"""
    parent: Dict[Position, Position] = {}

    def find(position: Position) -> Position:
        root = position
        while parent[root] != root:
            root = parent[root]
        while parent[position] != root:  # 路径压缩
            parent[position], position = root, parent[position]
        return root

    def union(left: Position, right: Position) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for constraint in constraints:
        for position in constraint.positions:
            parent.setdefault(position, position)
    for constraint in constraints:
        first = constraint.positions[0]
        for position in constraint.positions[1:]:
            union(first, position)

    groups: Dict[Position, List[Position]] = defaultdict(list)
    for position in parent:
        groups[find(position)].append(position)

    order = {position: index for index, position in enumerate(parent)}
    result: List[Tuple[Tuple[Position, ...], List[Constraint]]] = []
    for cells in groups.values():
        cells.sort(key=order.__getitem__)
        cell_set = set(cells)
        local = [constraint for constraint in constraints
                 if constraint.positions[0] in cell_set]
        result.append((tuple(cells), local))
    return result


def _enumerate_component(cells: Sequence[Position], constraints: Sequence[Constraint],
                         budget: Optional[int] = None) -> Component:
    """穷举一个组件的所有合法布雷方案，按"组件雷数"聚合。

    装了 ``frontier_native`` 时走 C++ 版（结果逐位相同，只是快 200 倍以上），
    否则用下面的纯 Python 参考实现。

    纯 Python 版用"最受限优先"的顺序填格：每次挑剩余未确定格最少的约束里的
    一个格子，这样大部分分支会在中途被约束剪掉。
    """
    if budget is None:
        budget = default_budget()
    if accelerator.available():
        outcome = accelerator.enumerate_component(cells, constraints, budget)
        if outcome is None:
            raise FrontierTooLarge("组件规模 %d，枚举超过 %d 个节点" % (len(cells), budget))
        ways, cell_ways = outcome
        if not ways:
            raise ValueError("组件无解（约束互相矛盾）")
        return Component(positions=tuple(cells), ways=ways, cell_ways=cell_ways)

    count = len(cells)
    index = {position: offset for offset, position in enumerate(cells)}
    local: List[Tuple[Tuple[int, ...], int]] = [
        (tuple(index[position] for position in constraint.positions), constraint.required)
        for constraint in constraints
    ]

    cell_constraints: List[List[int]] = [[] for _ in range(count)]
    for constraint_id, (members, _required) in enumerate(local):
        for offset in members:
            cell_constraints[offset].append(constraint_id)

    assignment = [-1] * count  # -1 未定 / 0 安全 / 1 是雷
    assigned_mines = [0] * len(local)
    assigned_cells = [0] * len(local)
    ways: Dict[int, int] = defaultdict(int)
    cell_ways: Dict[int, Dict[int, int]] = {offset: defaultdict(int) for offset in range(count)}

    nodes = [0]

    def feasible(constraint_id: int) -> bool:
        members, required = local[constraint_id]
        mines = assigned_mines[constraint_id]
        done = assigned_cells[constraint_id]
        if mines > required:
            return False
        if done == len(members) and mines != required:
            return False
        return mines + (len(members) - done) >= required

    def pick() -> int:
        best, best_remaining = -1, None
        for constraint_id, (members, _required) in enumerate(local):
            remaining = 0
            for offset in members:
                if assignment[offset] < 0:
                    remaining += 1
            if not remaining:
                continue
            if best_remaining is None or remaining < best_remaining:
                best_remaining = remaining
                for offset in members:
                    if assignment[offset] < 0:
                        best = offset
                        break
        if best < 0:  # 剩下的格子都不在任何约束里（理论上不该发生）
            for offset in range(count):
                if assignment[offset] < 0:
                    return offset
        return best

    def search(done: int, mines: int) -> None:
        nodes[0] += 1
        if nodes[0] > budget:
            raise FrontierTooLarge("组件规模 %d，枚举超过 %d 个节点" % (count, budget))
        if done == count:
            ways[mines] += 1
            for offset in range(count):
                if assignment[offset] == 1:
                    cell_ways[offset][mines] += 1
            return

        offset = pick()
        for value in (1, 0):
            assignment[offset] = value
            ok = True
            for constraint_id in cell_constraints[offset]:
                assigned_cells[constraint_id] += 1
                assigned_mines[constraint_id] += value
                if not feasible(constraint_id):
                    ok = False
            if ok:
                search(done + 1, mines + value)
            for constraint_id in cell_constraints[offset]:
                assigned_cells[constraint_id] -= 1
                assigned_mines[constraint_id] -= value
            assignment[offset] = -1

    search(0, 0)

    if not ways:
        raise ValueError("组件无解（约束互相矛盾）")

    return Component(
        positions=tuple(cells),
        ways=dict(ways),
        cell_ways={cells[offset]: dict(counter) for offset, counter in cell_ways.items()},
    )


def _convolve(components: Sequence[Component], limit: int) -> Dict[int, int]:
    """按雷数卷积各组件，只保留雷数 <= limit 的部分（更大的对最终和没贡献）。"""
    totals: Dict[int, int] = {0: 1}
    for component in components:
        merged: Dict[int, int] = defaultdict(int)
        for used, ways in totals.items():
            for mines, count in component.ways.items():
                if used + mines <= limit:
                    merged[used + mines] += ways * count
        totals = dict(merged)
    return totals


_comb_cache_impl = lru_cache(maxsize=None)(comb)


def _comb(count: int, take: int) -> int:
    """``comb`` 的记忆化版本：卷积里同一个 ``(free, 剩余雷数)`` 会被反复用。"""
    return _comb_cache_impl(count, take)

def _with_free(totals: Dict[int, int], free_count: int, total_mines: int) -> int:
    """把"空白格的组合数"并进卷积结果，得到合法雷图总数。"""
    result = 0
    for used, ways in totals.items():
        remaining = total_mines - used
        if 0 <= remaining <= free_count:
            result += ways * _comb(free_count, remaining)
    return result


def count_solutions(system: ConstraintSystem, budget: Optional[int] = None) -> int:
    """Return the number of full layouts satisfying the constraints and mine count."""
    total = system.total_mines
    if not system.consistent or not 0 <= total <= len(system.unknown):
        return 0
    try:
        components = system.components(budget)
    except ValueError:
        return 0
    return _with_free(_convolve(components, total), len(system.free), total)


def probabilities(system: ConstraintSystem, budget: Optional[int] = None) -> ProbabilityTable:
    """返回全盘未知格的精确边际概率（0.0 安全 / 1.0 必是雷 / 中间值）。"""
    if budget is None:
        budget = default_budget()
    if not system.consistent:
        return ProbabilityTable()

    frontier, free, total = system.frontier, system.free, system.total_mines
    if total < 0 or total > len(frontier) + len(free):
        return ProbabilityTable()

    if not frontier:
        if not free:
            return ProbabilityTable()
        density = total / float(len(free))
        return ProbabilityTable({position: density for position in free})

    try:
        components = system.components(budget)
    except FrontierTooLarge:
        raise
    except ValueError:  # 某个组件内部矛盾
        return ProbabilityTable()

    totals = _convolve(components, total)
    grand_total = _with_free(totals, len(free), total)
    if grand_total == 0:
        return ProbabilityTable()

    table = ProbabilityTable()
    for index, component in enumerate(components):
        others = _convolve(components[:index] + components[index + 1:], total)
        for position in component.positions:
            numerator = 0
            for mines, count in component.cell_ways[position].items():
                for used, ways in others.items():
                    remaining = total - used - mines
                    if 0 <= remaining <= len(free):
                        numerator += ways * count * _comb(len(free), remaining)
            table[position] = numerator / grand_total

    if free:
        numerator = 0
        for used, ways in totals.items():
            remaining = total - used - 1
            if 0 <= remaining <= len(free) - 1:
                numerator += ways * _comb(len(free) - 1, remaining)
        density = numerator / grand_total
        for position in free:
            table[position] = density

    return table


class IncrementalBuilder:
    """增量维护"数字格 → 约束"，避免每一步都重扫全盘。

    :func:`build_system` 每步都要遍历所有格子、对每个数字格重新数一遍八邻域；在续局里
    这一步每盘要执行几百次。这里保存上一次的 ``mark_matrix`` 快照，只有和快照不同的
    格子以及它们的邻居（也就是约束可能变了的数字格）才重算。

    语义与 :func:`build_system` 完全一致：约束按 (行, 列) 升序输出，frontier/free 的
    顺序也一致，所以调用方可以无感替换（有回归测试逐表比对）。
    """

    __slots__ = ("board", "rows", "cols", "_constraints", "_marks", "_broken")

    def __init__(self, board) -> None:
        self.board = board
        self.rows = board.rows
        self.cols = board.cols
        self._constraints: Dict[Position, Constraint] = {}
        self._broken = False
        values = board_values(board)
        for row in range(self.rows):
            for col in range(self.cols):
                if values[row][col] >= 1:
                    self._refresh(values, row, col)
        self._marks = [list(row) for row in board.mark_matrix]

    def _refresh(self, values: List[List[int]], row: int, col: int) -> None:
        """重算单个数字格的约束；它不再是数字格时直接删除。"""
        key = (row, col)
        number = values[row][col]
        if number < 1:
            self._constraints.pop(key, None)
            return
        unknown: List[Position] = []
        flagged = 0
        for d_row, d_col in DIRECTIONS:
            near = row + d_row
            side = col + d_col
            if near < 0 or near >= self.rows or side < 0 or side >= self.cols:
                continue
            value = values[near][side]
            if value == 0:
                unknown.append((near, side))
            elif value == -1:
                flagged += 1
        required = number - flagged
        if required < 0 or required > len(unknown):
            # 盘面自相矛盾（例如真人乱标雷），交给全量构建去报 inconsistent。
            self._broken = True
            self._constraints.pop(key, None)
            return
        if unknown:
            self._constraints[key] = Constraint(tuple(unknown), required)
        else:
            self._constraints.pop(key, None)

    def system(self, values: Optional[List[List[int]]] = None) -> ConstraintSystem:
        if values is None:
            values = board_values(self.board)
        marks = self.board.mark_matrix
        changed: List[Position] = []
        for row in range(self.rows):
            current = marks[row]
            snapshot = self._marks[row]
            if current != snapshot:
                for col in range(self.cols):
                    if current[col] != snapshot[col]:
                        changed.append((row, col))
        if changed:
            targets = set(changed)
            for row, col in changed:
                for d_row, d_col in DIRECTIONS:
                    near = row + d_row
                    side = col + d_col
                    if 0 <= near < self.rows and 0 <= side < self.cols:
                        targets.add((near, side))
            for row, col in targets:
                self._refresh(values, row, col)
            for row in range(self.rows):
                self._marks[row] = list(marks[row])

        if self._broken:
            return build_system(self.board, values)

        constraints = [self._constraints[key] for key in sorted(self._constraints)]
        frontier: List[Position] = []
        seen = set()
        for constraint in constraints:
            for position in constraint.positions:
                if position not in seen:
                    seen.add(position)
                    frontier.append(position)
        free: List[Position] = []
        for row in range(self.rows):
            value_row = values[row]
            for col in range(self.cols):
                if value_row[col] == 0 and (row, col) not in seen:
                    free.append((row, col))
        return ConstraintSystem(
            tuple(constraints), tuple(frontier), tuple(free), self.board.remain_mine()
        )


class FrontierSolver:
    """把 :func:`probabilities` 包成和 ``LocalSolver``/``WholeSolver`` 一样的接口。"""

    name = "frontier"

    def __init__(self, board, budget: Optional[int] = None) -> None:
        self.board = board
        self.budget = default_budget() if budget is None else budget
        self.incremental = True
        self._builder = None

    def probabilities(self, values: Optional[List[List[int]]] = None) -> ProbabilityTable:
        """``values`` 传进来可以省掉一次整盘 ``board_values``（调用方通常已经算过）。"""
        return probabilities(self.system(values), self.budget)

    def system(self, values: Optional[List[List[int]]] = None) -> ConstraintSystem:
        if not self.incremental:
            return build_system(self.board, values)
        builder = self._builder
        if builder is None or builder.board is not self.board:
            builder = self._builder = IncrementalBuilder(self.board)
        return builder.system(values)


class _Found(Exception):
    """内部用：随机采样一旦找到一致雷图就立刻展开调用栈。"""


def _sample_once(
    frontier: Sequence[Position],
    constraints: Sequence[Constraint],
    free: Sequence[Position],
    total: int,
    rng: random.Random,
    node_limit: int,
) -> Optional[Set[Position]]:
    count = len(frontier)
    index = {position: offset for offset, position in enumerate(frontier)}
    local = [
        (tuple(index[position] for position in constraint.positions), constraint.required)
        for constraint in constraints
    ]
    cell_constraints: List[List[int]] = [[] for _ in range(count)]
    for constraint_id, (members, _required) in enumerate(local):
        for offset in members:
            cell_constraints[offset].append(constraint_id)

    assignment = [-1] * count  # -1 未定 / 0 安全 / 1 是雷
    assigned_mines = [0] * len(local)
    assigned_cells = [0] * len(local)
    nodes = [0]
    found: List[Set[Position]] = []

    def feasible(constraint_id: int) -> bool:
        members, required = local[constraint_id]
        mines = assigned_mines[constraint_id]
        done = assigned_cells[constraint_id]
        if mines > required:
            return False
        if done == len(members) and mines != required:
            return False
        return mines + (len(members) - done) >= required

    def pick() -> int:
        best, best_remaining = -1, None
        for constraint_id, (members, _required) in enumerate(local):
            remaining = 0
            for offset in members:
                if assignment[offset] < 0:
                    remaining += 1
            if not remaining:
                continue
            if best_remaining is None or remaining < best_remaining:
                best_remaining = remaining
                for offset in members:
                    if assignment[offset] < 0:
                        best = offset
                        break
        if best < 0:
            for offset in range(count):
                if assignment[offset] < 0:
                    return offset
        return best

    def search(done: int, mines: int) -> None:
        nodes[0] += 1
        if nodes[0] > node_limit:
            raise _Found
        if mines > total:
            return
        if done == count:
            remaining = total - mines
            if 0 <= remaining <= len(free):
                mines_set = {frontier[offset] for offset in range(count)
                             if assignment[offset] == 1}
                mines_set.update(rng.sample(list(free), remaining))
                found.append(mines_set)
                raise _Found
            return

        offset = pick()
        values = [1, 0]
        rng.shuffle(values)
        left = count - done - 1
        for value in values:
            if mines + value > total:
                continue
            if mines + value + left + len(free) < total:  # 剩下的格子全放也不够
                continue
            assignment[offset] = value
            ok = True
            for constraint_id in cell_constraints[offset]:
                assigned_cells[constraint_id] += 1
                assigned_mines[constraint_id] += value
                if not feasible(constraint_id):
                    ok = False
            if ok:
                search(done + 1, mines + value)
            for constraint_id in cell_constraints[offset]:
                assigned_cells[constraint_id] -= 1
                assigned_mines[constraint_id] -= value
            assignment[offset] = -1

    try:
        search(0, 0)
    except _Found:
        pass
    return found[0] if found else None


def _ways_k(cells: Sequence[Position], constraints: Sequence[Constraint], mines: int) -> int:
    """某个（带附加约束的）组件里"恰好 ``mines`` 颗雷"的方案数。"""
    try:
        component = _enumerate_component(cells, constraints)
    except ValueError:          # 这组附加约束下无解
        return 0
    return component.ways.get(mines, 0)


def _polynomial(cells: Sequence[Position], constraints: Sequence[Constraint],
                limit: int) -> List[int]:
    """组件的生成函数 ``W(z)=Σ ways[k] z^k``（只保留到 ``limit`` 次）。"""
    component = _enumerate_component(cells, constraints)
    return [component.ways.get(k, 0) for k in range(limit + 1)]


def _poly_mul(left: Sequence[int], right: Sequence[int], limit: int) -> List[int]:
    result = [0] * (limit + 1)
    for i, a in enumerate(left):
        if not a:
            continue
        for j, b in enumerate(right):
            if i + j > limit:
                break
            if b:
                result[i + j] += a * b
    return result


def _binomials(count: int, limit: int) -> List[int]:
    """``[C(count, 0), C(count, 1), ..., C(count, limit)]``。"""
    row = [0] * (limit + 1)
    row[0] = 1
    for j in range(1, min(count, limit) + 1):
        row[j] = row[j - 1] * (count - j + 1) // j
    return row


def _sample_component(cells: Sequence[Position], constraints: Sequence[Constraint],
                      mines: int, rng: random.Random) -> Optional[Set[Position]]:
    """在一个组件里**均匀**抽一张"恰好 ``mines`` 颗雷"的合法雷图。

    逐个格子决定是不是雷：先数出"还剩多少满足条件的方案"，再数出"这一格是雷
    的方案数"，按比例抽。装了原生加速器时每次计数是微秒级，所以这个分布是
    精确均匀的——DFS 找到的"第一张解"是有偏的（实测单格频率能偏 0.3）。
    """
    pinned: List[Constraint] = []
    chosen: Set[Position] = set()
    remaining = _ways_k(cells, constraints, mines)
    if remaining == 0:
        return None
    for cell in cells:
        with_mine = _ways_k(cells, list(constraints) + pinned + [Constraint((cell,), 1)], mines)
        if rng.randrange(remaining) < with_mine:
            chosen.add(cell)
            pinned.append(Constraint((cell,), 1))
            remaining = with_mine
        else:
            pinned.append(Constraint((cell,), 0))
            remaining -= with_mine
        if remaining == 0 and len(chosen) < mines:
            return None
    if len(chosen) != mines:
        return None
    return chosen


def sample_mines(
    system: ConstraintSystem,
    rng: Optional[random.Random] = None,
    node_limit: int = 20_000,
    attempts: int = 6,
) -> Optional[Set[Position]]:
    """随机抽一张与约束一致的雷图（返回"哪些格是雷"的集合）。

    用途是给"猜哪一格"做蒙特卡洛：不看这一步会不会死，而看打开之后还能
    连锁确定多少格。采样用随机化的"最受限优先"DFS——每个约束只看自己的
    剩余需求，所以一次采样大致对应"按后验概率抽一张盘"。

    抽不出来（节点超限 / 约束互相矛盾）时返回 ``None``，调用方要能退回
    "最小概率格"。
    """
    if not system.consistent:
        return None
    if rng is None:
        rng = random
    frontier, free, total = system.frontier, system.free, system.total_mines
    if total < 0 or total > len(frontier) + len(free):
        return None
    if not frontier:
        if total > len(free):
            return None
        return set(rng.sample(list(free), total))
    if len(frontier) <= UNIFORM_LIMIT:
        components = _split_components(system.constraints)
        polynomials = [_polynomial(cells, constraints, total) for cells, constraints in components]
        suffix: List[List[int]] = [None] * (len(polynomials) + 1)
        suffix[len(polynomials)] = _binomials(len(free), total)
        for index in range(len(polynomials) - 1, -1, -1):
            suffix[index] = _poly_mul(polynomials[index], suffix[index + 1], total)
        if suffix[0][total] == 0:
            return None

        used = 0
        chosen: Set[Position] = set()
        for index, (cells, constraints) in enumerate(components):
            weights = []
            for mines in range(total - used + 1):
                ways = polynomials[index][mines]
                weights.append(ways * suffix[index + 1][total - used - mines] if ways else 0)
            total_weight = sum(weights)
            if total_weight == 0:
                return None
            draw = rng.randrange(total_weight)
            for mines, weight in enumerate(weights):
                if draw < weight:
                    break
                draw -= weight
            part = _sample_component(cells, constraints, mines, rng)
            if part is None:
                return None
            chosen |= part
            used += mines
        rest = total - used
        if not 0 <= rest <= len(free):
            return None
        chosen |= set(rng.sample(list(free), rest))
        return chosen

    for _ in range(attempts):
        result = _sample_once(frontier, system.constraints, free, total, rng, node_limit)
        if result is not None:
            return result
    return None

