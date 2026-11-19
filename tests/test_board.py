"""棋盘逻辑测试（不涉及 Qt、不涉及概率计算）。"""

import random
import unittest

from minesweeper.core.board import Board
from minesweeper.core.enums import DIRECTIONS, MINE, Mark, Status

from .support import make_board


class BoardInitTest(unittest.TestCase):
    def test_initial_state(self):
        board = Board(9, 10, 12)
        self.assertEqual(board.rows, 9)
        self.assertEqual(board.cols, 10)
        self.assertEqual(board.mines, 12)
        self.assertEqual(board.size, (9, 10))
        self.assertFalse(board.is_generated)
        self.assertEqual(board.mine_matrix, [])
        self.assertEqual(len(board.mark_matrix), 9)
        self.assertEqual(len(board.mark_matrix[0]), 10)
        self.assertTrue(all(mark == Mark.COVERED for row in board.mark_matrix for mark in row))

    def test_remain_mine_and_count_flags(self):
        board = Board(3, 3, 2)
        self.assertEqual(board.count_flags(), 0)
        self.assertEqual(board.remain_mine(), 2)
        board.mark_matrix[0][0] = Mark.FLAG
        self.assertEqual(board.count_flags(), 1)
        self.assertEqual(board.remain_mine(), 1)


class BoardNeighbourTest(unittest.TestCase):
    def test_get_round_keeps_legacy_order(self):
        board = Board(3, 3, 0)
        # 旧版顺序：(0,1),(0,-1),(-1,0),(1,0),(1,1),(1,-1),(-1,1),(-1,-1)
        self.assertEqual(board.get_round(0, 0), [(0, 1), (1, 0), (1, 1)])
        self.assertEqual(
            board.get_round(1, 1),
            [(1, 2), (1, 0), (0, 1), (2, 1), (2, 2), (2, 0), (0, 2), (0, 0)],
        )
        self.assertEqual(len(board.get_round(2, 2)), 3)

    def test_directions_are_the_legacy_eight(self):
        self.assertEqual(
            DIRECTIONS,
            ((0, 1), (0, -1), (-1, 0), (1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)),
        )

    def test_adjacent_helpers(self):
        board = make_board(3, 3, [(0, 0)])
        board.mark_matrix[1][1] = Mark.OPENED  # 数字 1
        self.assertEqual(board.adjacent_numbers(2, 2), [(1, 1)])
        # 雷格本身不会被当成"已展开的数字格"
        self.assertNotIn((0, 0), board.adjacent_numbers(1, 0))
        board.mark_matrix[1][1] = Mark.FLAG
        self.assertEqual(board.adjacent_flags(2, 2), 1)
        self.assertEqual(board.adjacent_flags(1, 1), 0)  # 自己不算邻居


class BoardGenMineTest(unittest.TestCase):
    def test_places_exact_mines_and_keeps_safe_zone(self):
        board = Board(16, 16, 40, rng=random.Random(20240101))
        board.gen_mine((8, 8))
        self.assertTrue(board.is_generated)

        mines = [
            (row, col)
            for row in range(16)
            for col in range(16)
            if board.mine_matrix[row][col] == MINE
        ]
        self.assertEqual(len(mines), 40)

        for row in range(7, 10):
            for col in range(7, 10):
                self.assertNotIn((row, col), mines)

        # 数字必须等于八邻域雷数
        mine_set = set(mines)
        for row in range(16):
            for col in range(16):
                if (row, col) in mine_set:
                    continue
                expected = sum(
                    1
                    for d_row in (-1, 0, 1)
                    for d_col in (-1, 0, 1)
                    if (d_row, d_col) != (0, 0) and (row + d_row, col + d_col) in mine_set
                )
                self.assertEqual(board.mine_matrix[row][col], expected)

    def test_safe_zone_at_corner(self):
        board = Board(9, 9, 10, rng=random.Random(7))
        board.gen_mine((0, 0))
        for row in range(2):
            for col in range(2):
                self.assertNotEqual(board.mine_matrix[row][col], MINE)

    def test_too_many_mines_raises(self):
        board = Board(9, 9, 80)
        with self.assertRaises(ValueError) as ctx:
            board.gen_mine((4, 4))
        self.assertIn("雷数过多", str(ctx.exception))

    def test_custom_rng_is_reproducible(self):
        first = Board(9, 9, 10, rng=random.Random(3))
        second = Board(9, 9, 10, rng=random.Random(3))
        first.gen_mine((4, 4))
        second.gen_mine((4, 4))
        self.assertEqual(first.mine_matrix, second.mine_matrix)


class BoardExpansionTest(unittest.TestCase):
    def test_blank_cell_floods_whole_area(self):
        board = make_board(4, 4, [(3, 3)])
        status, positions = board.expansion(0, 0)
        # 这一片空白把所有非雷格都打开了，因此同时满足胜利条件
        self.assertIn(status, (Status.NORMAL, Status.WIN))
        self.assertEqual(len(positions), 15)
        self.assertEqual(len(set(positions)), 15)
        self.assertTrue(
            all(board.mark_matrix[row][col] == Mark.OPENED for row, col in positions)
        )

    def test_number_cell_opens_only_itself(self):
        board = make_board(2, 2, [(0, 0)])
        status, positions = board.expansion(0, 1)
        self.assertEqual(status, Status.NORMAL)
        self.assertEqual(positions, [(0, 1)])
        self.assertEqual(board.mark_matrix[0][1], Mark.OPENED)

    def test_mine_fails_and_does_not_change_marks(self):
        board = make_board(2, 2, [(0, 0)])
        status, positions = board.expansion(0, 0)
        self.assertEqual(status, Status.FAIL)
        self.assertEqual(positions, [])
        self.assertEqual(board.mark_matrix[0][0], Mark.COVERED)

    def test_opening_last_safe_cell_wins(self):
        board = make_board(2, 2, [(0, 0)])
        self.assertEqual(board.expansion(0, 1)[0], Status.NORMAL)
        self.assertEqual(board.expansion(1, 0)[0], Status.NORMAL)
        status, _ = board.expansion(1, 1)
        self.assertEqual(status, Status.WIN)
        self.assertTrue(board.is_won())

    def test_flood_stops_at_already_opened_area(self):
        """已展开的空白格不再扩散（旧版靠 index_Matrix 达到同样效果）。"""
        board = make_board(4, 4, [(3, 3)])
        board.expansion(0, 0)  # 第一次就把非雷格全打开了（直接获胜）
        status, positions = board.expansion(0, 0)
        self.assertEqual(positions, [(0, 0)])
        self.assertEqual(status, Status.WIN)


class BoardFlagTest(unittest.TestCase):
    def test_cycle_flag_three_states(self):
        board = make_board(2, 2, [(0, 0)])
        self.assertEqual(board.cycle_flag(0, 0), (Mark.FLAG, Status.NORMAL))
        self.assertEqual(board.mark_matrix[0][0], Mark.FLAG)
        self.assertEqual(board.cycle_flag(0, 0), (Mark.QUESTION, Status.NORMAL))
        self.assertEqual(board.cycle_flag(0, 0), (Mark.COVERED, Status.NORMAL))
        self.assertEqual(board.mark_matrix[0][0], Mark.COVERED)

    def test_cycle_flag_on_opened_cell_is_noop(self):
        board = make_board(2, 2, [(0, 0)])
        board.mark_matrix[0][1] = Mark.OPENED
        self.assertEqual(board.cycle_flag(0, 1), (Mark.OPENED, Status.NORMAL))
        self.assertEqual(board.mark_matrix[0][1], Mark.OPENED)

    def test_flagging_the_last_closed_cell_wins(self):
        board = Board(1, 2, 1)
        board.mine_matrix = [[MINE, 1]]
        board.mark_matrix = [[Mark.COVERED, Mark.OPENED]]
        mark, status = board.cycle_flag(0, 0)
        self.assertEqual(mark, Mark.FLAG)
        self.assertEqual(status, Status.WIN)

    def test_mark_mine_sets_flag_and_refreshes_counter(self):
        board = make_board(3, 3, [(0, 0)])
        self.assertEqual(board.mark_mine(0, 0), Status.NORMAL)
        self.assertEqual(board.mark_matrix[0][0], Mark.FLAG)
        self.assertEqual(board.remain_mine(), 0)


class BoardLifecycleTest(unittest.TestCase):
    def test_new_game_clears_mines(self):
        board = make_board(3, 3, [(0, 0)])
        board.new_game()
        self.assertEqual(board.mine_matrix, [])
        self.assertFalse(board.is_generated)
        self.assertTrue(all(mark == Mark.COVERED for row in board.mark_matrix for mark in row))

    def test_reset_keeps_mines(self):
        board = make_board(3, 3, [(0, 0)])
        before = [list(row) for row in board.mine_matrix]
        board.mark_matrix[1][1] = Mark.OPENED
        board.mark_matrix[0][0] = Mark.FLAG
        board.reset()
        self.assertEqual(board.mine_matrix, before)
        self.assertTrue(board.is_generated)
        self.assertTrue(all(mark == Mark.COVERED for row in board.mark_matrix for mark in row))

    def test_random_position_is_inside_board(self):
        board = Board(5, 7, 3, rng=random.Random(11))
        for _ in range(50):
            row, col = board.random_position()
            self.assertTrue(0 <= row < 5)
            self.assertTrue(0 <= col < 7)

    def test_as_text_show_mines(self):
        board = make_board(2, 2, [(0, 0)], opened_at=[(1, 1)])
        text = board.as_text(show_mines=True)
        lines = text.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0][0], "X")  # 未展开的雷
        self.assertEqual(lines[1][1], "1")  # 已展开的数字


if __name__ == "__main__":
    unittest.main()
