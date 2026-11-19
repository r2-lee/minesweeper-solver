"""``minesweeper.solver.gametree`` 的测试。

覆盖：世界权重、无解时返回 None、期望值的合理范围、预算放弃、不改棋盘。
"""

import math
import unittest

from tests import support

from minesweeper.core.enums import Mark
from minesweeper.solver import gametree
from minesweeper.solver.frontier import build_system


class WeightTest(unittest.TestCase):
    def setUp(self):
        # 3x3，雷在 (0,0)，只开中心 (1,1) -> 边沿 8 格、空白 0 格。
        self.board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])

    def test_weights_match_binomial(self):
        system = build_system(self.board)
        worlds, weights, free_count, total = gametree.weighted_worlds(system, 1000)
        self.assertIsNotNone(worlds)
        # 空白格为 0 时，每个世界权重都是 C(0, 0) = 1。
        expected = sum(math.comb(free_count, total - len(world)) for world in worlds)
        self.assertEqual(sum(weights), expected)
        self.assertEqual(len(worlds), len(weights))
        self.assertEqual(total, system.total_mines)

    def test_layout_matches_opened_numbers(self):
        system = build_system(self.board)
        worlds, _weights, _free, _total = gametree.weighted_worlds(system, 1000)
        for world in worlds:
            self.assertEqual(1, len(world))
            self.assertIn((0, 0), world | {(0, 0)})  # 只有一个雷
            self.assertEqual(1, gametree._number_at(world, (1, 1)))


class SolveTest(unittest.TestCase):
    def test_no_frontier_returns_none(self):
        # 一个数字都没打开 -> 没有任何约束，边沿为空。
        board = support.make_board(3, 3, [(2, 2)])
        self.assertIsNone(gametree.solve(board))

    def test_returns_a_frontier_position(self):
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        position, value = gametree.solve(board)
        self.assertIn(position, set(build_system(board).frontier))
        self.assertGreater(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_value_is_at_most_the_safety_of_each_candidate(self):
        board = support.make_board(4, 4, [(0, 0), (3, 3)], opened_at=[(1, 1), (2, 2)])
        result = gametree.solve(board)
        self.assertIsNotNone(result)
        _position, value = result
        table = __import__("minesweeper.solver.frontier", fromlist=["FrontierSolver"])
        probabilities = table.FrontierSolver(board).probabilities()
        safest = min(probabilities.values()) if probabilities else 0.0
        # 完整搜索最多和最安全格一样好（不会超过 1）。
        self.assertLessEqual(value, max(1.0 - safest + 1e-9, 1.0))

    def test_budget_gives_up(self):
        board = support.make_board(5, 5, [(0, 0), (4, 4)], opened_at=[(1, 1), (2, 3)])
        self.assertIsNone(gametree.solve(board, node_limit=1))

    def test_does_not_modify_the_board(self):
        board = support.make_board(4, 4, [(0, 3)], opened_at=[(1, 1), (2, 2)])
        before = [row[:] for row in board.mark_matrix]
        gametree.solve(board)
        self.assertEqual(before, board.mark_matrix)


class BlankPolicyTest(unittest.TestCase):
    def test_returns_none_without_blank_region(self):
        from minesweeper.solver.guess import choose_open_blank
        from minesweeper.solver.frontier import FrontierSolver

        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        table = FrontierSolver(board).probabilities()
        self.assertIsNone(choose_open_blank(board, table))

    def test_picks_a_blank_cell_when_it_pays_off(self):
        from minesweeper.solver.guess import choose_open_blank
        from minesweeper.solver.frontier import FrontierSolver

        # 打开一整列数字后，右边全是"不挨着已开格"的空白区。
        board = support.make_board(9, 9, [(8, 8)], opened_at=[(0, 4)])
        table = FrontierSolver(board).probabilities()
        choice = choose_open_blank(board, table)
        self.assertIsNotNone(choice)
        position, probability = choice
        tapped = any(
            board.mark_matrix[row][col] == Mark.OPENED
            for row, col in __import__("minesweeper.core.geometry", fromlist=["neighbours"]).neighbours(
                position, 9, 9
            )
        )
        self.assertFalse(tapped, "选中的格子不应该挨着任何已开格")
        self.assertAlmostEqual(probability, table[position])


if __name__ == "__main__":
    unittest.main()
