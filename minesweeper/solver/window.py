"""棋盘 -> 求解器输入：取值编码、局部窗口、候选中心。

这一层负责回答三个问题，纯函数、不依赖 Qt：

1. **每个格子现在算什么东西**（:func:`cell_value`）——把"标记 + 真实雷信息"
   映射成原生模块认识的整数编码；
2. **以某个数字格为中心，该看哪一小块**（:func:`build_window`）——切窗口、
   裁掉没用的全 0 边、算出"必须精确满足的数字格"和"候选格"，以及本窗口内
   雷数的上下界；
3. **哪些数字格值得算**（:func:`local_centers`）。

取值编码
--------
=====  =====================================================
取值    含义
=====  =====================================================
``0``   未展开 / 问号（对求解器来说都是"未知"）
``-1``  已标记为雷
``1..8``已展开的数字格
``-10`` 已展开的空白格
=====  =====================================================

.. note::

   局部窗口"必须精确满足"的数字格，只包含**八邻域完整落在窗口内**的那些。
   窗口边界上的数字格看不到窗口外，只能用来做“雷数上界”（KI-7 的教训：
   上界漏算它们会把真雷算成 0 概率）。
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..core.board import Board
from ..core.enums import Mark
from ..core.geometry import Matrix, Position, neighbours, shape
from .errors import SolverError

#: 局部窗口的边界（左闭右开），由 :func:`build_window` 内部使用
_Bounds = Tuple[int, int, int, int]


# ----------------------------------------------------------------------
# 取值编码
# ----------------------------------------------------------------------
def cell_value(mark: int, mine: int) -> int:
    """把一个格子的 ``(标记, 真实雷信息)`` 映射成求解器取值。

    规则照抄旧版 ``get_CalMat`` 的 elif 链（顺序有意义，别随手重排）：

    ==================  ===========================  ======
    格子状态             条件                          取值
    ==================  ===========================  ======
    未展开 / 问号        mark in (0, 2)                 0
    已标雷               mark == 1                     -1
    已展开的空白格       mark == -10 and mine == 0     -10
    已展开的数字格       mark == -10 and mine > 0     mine
    已展开的雷格         mark == -10 and mine == -1    -10（落到最后的 else）
    ==================  ===========================  ======
    """
    if mark == Mark.COVERED or mark == Mark.QUESTION:
        return 0
    if mark == Mark.FLAG:
        return -1
    if mark == Mark.OPENED and mine == 0:
        return -10
    if mark == Mark.OPENED and mine > 0:
        return mine
    return -10


def board_values(board: Board) -> Matrix:
    """整盘的取值矩阵（行主序）。"""
    return [
        [cell_value(board.mark_matrix[row][col], board.mine_matrix[row][col])
         for col in range(board.cols)]
        for row in range(board.rows)
    ]


def unknown_positions(values: Matrix) -> List[Position]:
    """所有未知格（取值 0）的坐标，行优先。"""
    rows, cols = shape(values)
    return [
        (row, col)
        for row in range(rows)
        for col in range(cols)
        if values[row][col] == 0
    ]


def local_centers(values: Matrix) -> List[Position]:
    """值得做局部计算的数字格：八邻域里还有未知格。

    没有未知格邻居的数字格算出来的表是空的（旧版也把这种中心过滤掉了），
    先筛掉可以省掉大量无意义的窗口构造。
    """
    rows, cols = shape(values)
    centers: List[Position] = []
    for row, col in _positions(values):
        if values[row][col] <= 0:
            continue
        if any(values[n_row][n_col] == 0 for n_row, n_col in neighbours((row, col), rows, cols)):
            centers.append((row, col))
    return centers


def _positions(values: Matrix):
    rows, cols = shape(values)
    for row in range(rows):
        for col in range(cols):
            yield row, col


# ----------------------------------------------------------------------
# 边角裁剪
# ----------------------------------------------------------------------
def trim_zero_edges(matrix: Sequence[Sequence[int]]) -> Tuple[List[List[int]], Tuple[int, int]]:
    """裁掉四边全 0 的边界，但**保留最内侧一行全 0**。

    保留一行的原因：贴着数字格的那一圈 0 是真实候选格，全裁掉会让窗口里的
    约束变成"看不见的雷旁边有数字"，反而算不出东西。

    :return: ``(新矩阵, 新矩阵左上角在原矩阵里的 (row, col))``
    """
    rows, cols = shape(matrix)
    if rows == 0 or cols == 0:
        return list(matrix), (0, 0)

    top = 0
    while top < rows and all(value == 0 for value in matrix[top]):
        top += 1
    bottom = 0
    while bottom < rows and all(value == 0 for value in matrix[rows - 1 - bottom]):
        bottom += 1
    left = 0
    while left < cols and all(matrix[row][left] == 0 for row in range(rows)):
        left += 1
    right = 0
    while right < cols and all(matrix[row][cols - 1 - right] == 0 for row in range(rows)):
        right += 1

    # 连着两行（列）全 0 时只留最内侧那一行：旧版如此，见 KNOWN_ISSUES KI-6。
    top_trim = top - 1 if top >= 2 else 0
    bottom_trim = bottom - 1 if bottom >= 2 else 0
    left_trim = left - 1 if left >= 2 else 0
    right_trim = right - 1 if right >= 2 else 0

    trimmed = [
        list(matrix[row][left_trim : cols - right_trim])
        for row in range(top_trim, rows - bottom_trim)
    ]
    return trimmed, (top_trim, left_trim)


# ----------------------------------------------------------------------
# 局部窗口
# ----------------------------------------------------------------------
@dataclass
class LocalWindow:
    """一次局部计算需要的全部输入。

    ``strict_positions`` 和 ``unopened_positions`` 都是窗口内的一维下标
    （``row * cols + col``，``cols`` 是**窗口**宽度），和原生模块的参数含义一致；
    要换成棋盘坐标用 :meth:`absolute`。
    """

    matrix: Matrix
    row_offset: int
    col_offset: int
    strict_positions: List[int]
    unopened_positions: List[int]
    min_mines: int
    max_mines: int
    level: int
    center: Position

    # -- 几何 ----------------------------------------------------------
    @property
    def rows(self) -> int:
        return len(self.matrix)

    @property
    def cols(self) -> int:
        return len(self.matrix[0]) if self.matrix else 0

    @property
    def flat(self) -> List[int]:
        """行主序展平，直接喂给引擎。"""
        return [value for row in self.matrix for value in row]

    def absolute(self, flat_index: int) -> Position:
        """窗口内一维下标 -> 棋盘绝对坐标。"""
        return (
            flat_index // self.cols + self.row_offset,
            flat_index % self.cols + self.col_offset,
        )

    def relative(self, position: Position) -> Optional[int]:
        """棋盘坐标 -> 窗口内一维下标；不在窗口里则返回 ``None``。"""
        row, col = position[0] - self.row_offset, position[1] - self.col_offset
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return row * self.cols + col
        return None

    def contains(self, position: Position) -> bool:
        return self.relative(position) is not None

    # -- 语义 ----------------------------------------------------------
    @property
    def has_digits(self) -> bool:
        """窗口里有没有数字格（没有任何数字格 = 没有任何约束）。"""
        return any(value > 0 for row in self.matrix for value in row)

    def check(self) -> Optional[str]:
        """窗口能不能算：能算返回 ``None``，不能算返回原因（便于日志和测试）。"""
        if self.min_mines < 0:
            return "已标雷数多于中心数字（棋盘状态自相矛盾）"
        if self.min_mines > self.max_mines:
            return "最少雷数大于最多雷数"
        if not self.unopened_positions:
            return "窗口里没有未展开格"
        if not self.has_digits:
            return "窗口里没有数字格，没有任何约束"
        return None

    def __str__(self) -> str:  # pragma: no cover - 调试用
        body = "\n".join(
            " ".join("{:>4}".format(value) for value in row) for row in self.matrix
        )
        return (
            "LocalWindow(level={}, center={}, offset={}, min={}, max={})\n{}".format(
                self.level,
                self.center,
                (self.row_offset, self.col_offset),
                self.min_mines,
                self.max_mines,
                body,
            )
        )


def _in_window(coord: int, start: int, stop: int, size: int) -> bool:
    """坐标 ``coord`` 的八邻域是否完全落在 ``[start, stop)`` 里。

    棋盘外不算越界（那里没有格子），所以坐标先夹到 ``[0, size - 1]``。
    旧版把上界写成 ``rows + 1`` 再比较 ``< end``，导致窗口贴边时最后一行/列
    被判成"邻域不完整"而整列漏算（KI-4）。
    """
    if stop <= start:
        return False
    return start <= max(coord - 1, 0) and min(coord + 1, size - 1) <= stop - 1


def _bounds(board: Board, x: int, y: int, level: int) -> _Bounds:
    """以 (x, y) 为中心、半径 level 的窗口边界（已夹到棋盘内）。"""
    return (
        max(x - level, 0),
        min(x + 1 + level, board.rows),
        max(y - level, 0),
        min(y + 1 + level, board.cols),
    )


def _read_values(board: Board, bounds: _Bounds) -> Matrix:
    row_start, row_stop, col_start, col_stop = bounds
    return [
        [
            cell_value(board.mark_matrix[row][col], board.mine_matrix[row][col])
            for col in range(col_start, col_stop)
        ]
        for row in range(row_start, row_stop)
    ]


def _fully_visible(board: Board, bounds: _Bounds) -> List[Position]:
    """八邻域完整落在窗口内的格子（绝对坐标）。

    只有这些格子的"周围雷数"能被窗口内的信息完整验证，才能当精确约束用。
    """
    row_start, row_stop, col_start, col_stop = bounds
    visible: List[Position] = []
    for row in range(row_start, row_stop):
        for col in range(col_start, col_stop):
            if _in_window(row, row_start, row_stop, board.rows) and _in_window(
                col, col_start, col_stop, board.cols
            ):
                visible.append((row, col))
    return visible


def _mine_bounds(
    board: Board, trimmed: Matrix, center: Position, candidate_count: int
) -> Tuple[int, int]:
    """窗口内雷数的下界和上界。

    * 下界：中心数字减去周围已标雷数（可以为负 —— 说明棋盘状态自相矛盾，
      由 :meth:`LocalWindow.check` 拒绝）；
    * 上界（KI-7）：窗口边界上的数字格看不到窗口外，它旁边的雷可能就在窗口里，
      所以不能只累加"完全可见"的数字格。两条依据：

      - 与某个数字格相邻的雷，每颗至少被一个数字格数一次，而每个数字格最多
        数到自己的值 -> 这类雷不超过矩阵里所有数字之和；
      - 完全不挨数字格的候选格不受任何约束，最多全部放满。
    """
    rows, cols = shape(trimmed)
    digit_sum = 0
    isolated = 0
    for row in range(rows):
        for col in range(cols):
            value = trimmed[row][col]
            if value > 0:
                digit_sum += value
            elif value == 0:
                has_digit_neighbour = any(
                    0 <= row + d_row < rows
                    and 0 <= col + d_col < cols
                    and trimmed[row + d_row][col + d_col] > 0
                    for d_row in (-1, 0, 1)
                    for d_col in (-1, 0, 1)
                )
                if not has_digit_neighbour:
                    isolated += 1

    x, y = center
    min_mines = board.mine_matrix[x][y] - board.adjacent_flags(x, y)
    return min_mines, min(candidate_count, digit_sum + isolated)


def build_window(board: Board, x: int, y: int, level: int) -> LocalWindow:
    """构造以 (x, y) 为中心、半径 ``level`` 的局部窗口。

    :raises SolverError: 窗口为空（中心不是已展开的格子，或者棋盘还没布雷）
    """
    bounds = _bounds(board, x, y, level)
    values = _read_values(board, bounds)
    if not values or not values[0]:
        raise SolverError(
            "局部窗口为空：中心 ({}, {}) 似乎不是已展开的格子".format(x, y)
        )

    visible = _fully_visible(board, bounds)
    trimmed, (top_trim, left_trim) = trim_zero_edges(values)
    if not trimmed or not trimmed[0]:
        raise SolverError("裁剪后局部窗口为空：中心 ({}, {})".format(x, y))

    row_offset = bounds[0] + top_trim
    col_offset = bounds[2] + left_trim
    rows, cols = shape(trimmed)

    # 绝对坐标 -> 窗口内一维下标；落在裁剪范围外的（被裁掉的边）直接丢弃。
    def relative(row: int, col: int) -> Optional[int]:
        r, c = row - row_offset, col - col_offset
        if 0 <= r < rows and 0 <= c < cols:
            return r * cols + c
        return None

    strict_positions = [
        index
        for index in (relative(row, col) for row, col in visible)
        if index is not None and trimmed[index // cols][index % cols] > 0
    ]
    # 候选格是矩阵里**所有**取值为 0 的格子：原生模块枚举的正是这些，
    # 只取"完全可见"的会漏掉窗口边界上的候选格，概率表就少了几项。
    unopened_positions = [
        row * cols + col
        for row in range(rows)
        for col in range(cols)
        if trimmed[row][col] == 0
    ]

    min_mines, max_mines = _mine_bounds(
        board, trimmed, (x, y), len(unopened_positions)
    )
    return LocalWindow(
        matrix=trimmed,
        row_offset=row_offset,
        col_offset=col_offset,
        strict_positions=strict_positions,
        unopened_positions=unopened_positions,
        min_mines=min_mines,
        max_mines=max_mines,
        level=level,
        center=(x, y),
    )
