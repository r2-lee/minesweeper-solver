"""坐标与矩阵的小工具。

求解器里一直在三种表示之间换算：

* 棋盘绝对坐标 ``(row, col)``；
* 一维下标 ``row * cols + col``（原生模块 ``Mat_Cal`` 用的是这个）；
* 局部窗口内的相对坐标。

旧版把这些式子散落在几十处（``i // ay``、``i % ay``、``i * Width + j`` ……），
最容易出的错是"按整盘列数取模"和"按窗口宽度取模"混用。这里统一收口，
以后新增算法只调这些函数，不再手写下标公式。
"""

from typing import Iterator, List, Sequence, Tuple

from .enums import DIRECTIONS

#: 棋盘坐标，(行, 列)，行从上往下、列从左往右，均为 0 基。
Position = Tuple[int, int]

#: 行主序的二维整数矩阵。
Matrix = List[List[int]]


def to_index(position: Position, cols: int) -> int:
    """绝对坐标 -> 一维下标（``cols`` 是**整个矩阵**的列数）。"""
    row, col = position
    return row * cols + col


def to_position(index: int, cols: int) -> Position:
    """一维下标 -> 绝对坐标（``cols`` 是**整个矩阵**的列数）。"""
    return index // cols, index % cols


def iter_positions(rows: int, cols: int) -> Iterator[Position]:
    """按行优先顺序遍历棋盘上的每一格。"""
    for row in range(rows):
        for col in range(cols):
            yield row, col


def neighbours(position: Position, rows: int, cols: int) -> Iterator[Position]:
    """八邻域坐标，顺序与 :data:`minesweeper.core.enums.DIRECTIONS` 一致。

    自动丢弃越界坐标，所以贴边格子得到的邻居数会少于 8。
    """
    row, col = position
    for d_row, d_col in DIRECTIONS:
        n_row, n_col = row + d_row, col + d_col
        if 0 <= n_row < rows and 0 <= n_col < cols:
            yield n_row, n_col


def shape(matrix: Sequence[Sequence[int]]) -> Tuple[int, int]:
    """``(行数, 列数)``；空矩阵返回 ``(0, 0)``。"""
    if not matrix:
        return 0, 0
    return len(matrix), len(matrix[0])


def flatten(matrix: Sequence[Sequence[int]]) -> List[int]:
    """行主序展平成一维列表。"""
    return [value for row in matrix for value in row]
