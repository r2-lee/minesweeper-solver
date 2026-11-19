"""测试辅助工具。"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

#: 无显示环境下跑 Qt 界面测试
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from minesweeper.core.board import Board  # noqa: E402
from minesweeper.core.enums import Mark  # noqa: E402


def make_board(rows, cols, mines_at, opened_at=()):
    """构造一个雷区已知、并按需把部分格子标成"已展开"的棋盘。

    :param rows: 行数
    :param cols: 列数
    :param mines_at: 雷的坐标序列
    :param opened_at: 预先标成已展开的坐标序列
    """
    board = Board(rows, cols, len(mines_at))
    board.mine_matrix = [[0] * cols for _ in range(rows)]
    for row, col in mines_at:
        board.mine_matrix[row][col] = -1
    for row in range(rows):
        for col in range(cols):
            if board.mine_matrix[row][col] != -1:
                board.mine_matrix[row][col] = board._count_adjacent_mines(row, col)
    for row, col in opened_at:
        board.mark_matrix[row][col] = Mark.OPENED
    return board


def open_all(board, mines_at):
    """把所有非雷格标成已展开（用于构造"全部可见"的求解场景）。"""
    mines = set(mines_at)
    for row in range(board.rows):
        for col in range(board.cols):
            if (row, col) not in mines:
                board.mark_matrix[row][col] = Mark.OPENED
    return board
