"""``find_coin``（分不开的 50/50）与 ``choose_open_living``（living tile）的测试。"""

import random
import unittest
from unittest import mock

from minesweeper.core.enums import Mark
from minesweeper.solver import guess as guess_module
from minesweeper.solver.guess import choose_open_living, find_coin
from minesweeper.solver.strategy import AutoSolver, SolverConfig

from .support import make_board


class FindCoinTest(unittest.TestCase):
    def test_detects_a_two_cell_coin(self):
        # 1x3：只有 (0,1) 开着且是 1，两颗未知格里恰好一颗是雷 → 分不开的硬币。
        board = make_board(1, 3, [(0, 0)], opened_at=[(0, 1)])
        coin = find_coin(board)
        self.assertIsNotNone(coin)
        self.assertEqual({coin[0], coin[1]}, {(0, 0), (0, 2)})

    def test_returns_none_without_constraints(self):
        board = make_board(4, 4, [(0, 0)])
        self.assertIsNone(find_coin(board))

    def test_respects_cell_limit(self):
        board = make_board(1, 3, [(0, 0)], opened_at=[(0, 1)])
        self.assertIsNone(find_coin(board, max_cells=1))

    def test_does_not_call_opened_cells_coins(self):
        board = make_board(1, 3, [(0, 0)], opened_at=[(0, 1)])
        coin = find_coin(board)
        for position in coin:
            self.assertNotEqual(board.mark_matrix[position[0]][position[1]], Mark.OPENED)


class ChooseOpenLivingTest(unittest.TestCase):
    def test_prefers_the_cell_that_can_show_more_values(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(2, 1)])
        table = {(0, 1): 0.10, (1, 1): 0.11}
        worlds = [{(0, 0)}, {(2, 2)}]
        with mock.patch.object(guess_module, "sample_mines", side_effect=worlds):
            choice = choose_open_living(board, table, samples=2)
        self.assertIsNotNone(choice)
        # (0, 1) 在两张雷图里显示 1/0（两种），(1, 1) 两张都显示 1（一种）。
        self.assertEqual(choice[0], (0, 1))

    def test_returns_none_for_certain_cells_only(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(2, 1)])
        self.assertIsNone(choose_open_living(board, {(0, 0): 1.0}))

    def test_returns_none_without_worlds(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(2, 1)])
        table = {(0, 1): 0.10, (1, 1): 0.11}
        with mock.patch.object(guess_module, "sample_mines", return_value=None):
            self.assertIsNone(choose_open_living(board, table, samples=2))

    def test_single_candidate_shortcuts(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(2, 1)])
        choice = choose_open_living(board, {(0, 1): 0.2})
        self.assertEqual(choice, ((0, 1), 0.2))


class CoinPolicyTest(unittest.TestCase):
    def test_coin_policy_opens_the_coin_first(self):
        board = make_board(1, 3, [(0, 0)], opened_at=[(0, 1)])
        solver = AutoSolver(board, config=SolverConfig(guess_policy="coin"))
        action = next(solver.actions())
        self.assertIn(action.position, {(0, 0), (0, 2)})

    def test_default_policy_is_still_min_prob(self):
        self.assertEqual(SolverConfig().guess_policy, "progress")


if __name__ == "__main__":
    unittest.main()
