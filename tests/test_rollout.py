"""rollout 猜法的单元测试。"""

import random
import unittest

from minesweeper.core.enums import Mark
from minesweeper.solver import frontier, rollout
from tests import support


def _board():
    """4x5 盘，三颗雷，开好的三个数字格构成两个互不相连的约束。"""

    board = support.make_board(
        4,
        5,
        [(0, 0), (3, 4), (1, 2)],
        opened_at=[(1, 1), (2, 3), (0, 4)],
    )
    return board


class WorldBoardTest(unittest.TestCase):
    def test_numbers_match_the_revealed_board(self):
        board = _board()
        system = frontier.build_system(board)
        mined = frontier.sample_mines(system, rng=random.Random(5))
        self.assertIsNotNone(mined)

        world = rollout._world_board(board, mined)
        for row in range(board.rows):
            for col in range(board.cols):
                if board.mark_matrix[row][col] != Mark.OPENED:
                    continue
                self.assertEqual(world.mine_matrix[row][col], board.mine_matrix[row][col])

    def test_revealed_state_is_copied(self):
        board = _board()
        world = rollout._world_board(board, {(0, 0)})
        self.assertEqual(world.mark_matrix, board.mark_matrix)


class SimulateTest(unittest.TestCase):
    def test_hitting_a_mine_is_a_loss(self):
        board = _board()
        self.assertFalse(rollout.simulate(board, {(0, 0), (1, 2), (3, 4)}, (0, 0)))

    def test_opening_the_last_safe_cell_wins(self):
        board = _board()
        support.open_all(board, [(0, 0), (3, 4), (1, 2)])
        for position in [(1, 0), (1, 3), (1, 4)]:
            if board.mark_matrix[position[0]][position[1]] != Mark.COVERED:
                continue
            self.assertTrue(rollout.simulate(board, {(0, 0), (3, 4), (1, 2)}, position))
            break

    def test_simulation_does_not_touch_the_real_board(self):
        board = _board()
        before = [list(row) for row in board.mark_matrix]
        rollout.simulate(board, {(0, 0), (1, 2), (3, 4)}, (1, 0))
        self.assertEqual(board.mark_matrix, before)


class EstimateTest(unittest.TestCase):
    def test_estimate_averages_over_worlds(self):
        board = _board()
        layouts = [{(0, 0), (1, 2), (3, 4)}, {(0, 1), (1, 2), (3, 4)}]
        value = rollout.estimate(board, (0, 0), layouts)
        self.assertAlmostEqual(value, 0.5)

    def test_estimate_without_worlds_is_zero(self):
        self.assertEqual(rollout.estimate(_board(), (0, 0), []), 0.0)


class ChooseOpenTest(unittest.TestCase):
    def test_no_table_means_no_choice(self):
        self.assertIsNone(rollout.choose_open(_board(), {}))

    def test_choice_stays_inside_the_candidate_band(self):
        board = _board()
        table = {(0, 1): 0.05, (2, 2): 0.06, (1, 0): 0.90}
        choice = rollout.choose_open(
            board,
            table,
            samples=3,
            candidates=2,
            band=0.05,
            rng=random.Random(1),
        )
        self.assertIsNotNone(choice)
        position, score = choice
        self.assertIn(position, {(0, 1), (2, 2)})
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()


class GambleTest(unittest.TestCase):
    """"边沿最安全格" vs "最大空区赌一把" 的两候选比较。"""

    def test_blank_cell_returns_a_free_cell_in_the_biggest_region(self):
        board = support.make_board(9, 9, [(0, 0)], opened_at=[(0, 1), (1, 0), (1, 1)])
        system = frontier.build_system(board)
        cell = rollout.blank_cell(board, system, region_min=10)
        self.assertIsNotNone(cell)
        self.assertIn(cell, set(system.free))

    def test_blank_cell_is_none_when_every_region_is_too_small(self):
        board = support.make_board(6, 6, [(0, 0)], opened_at=[(0, 1), (1, 0), (1, 1)])
        system = frontier.build_system(board)
        self.assertIsNone(rollout.blank_cell(board, system, region_min=10 ** 6))

    def test_gamble_is_none_when_the_blank_region_is_not_worth_it(self):
        board = support.make_board(9, 9, [(0, 0)], opened_at=[(0, 1), (1, 0), (1, 1)])
        system = frontier.build_system(board)
        table = frontier.probabilities(system)
        self.assertIsNone(
            rollout.choose_gamble(
                board, table, samples=1, region_min=10 ** 6, rng=random.Random(1)
            )
        )

    def test_gamble_returns_the_blank_only_when_it_simulates_better(self):
        board = support.make_board(9, 9, [(0, 0)], opened_at=[(0, 1), (1, 0), (1, 1)])
        system = frontier.build_system(board)
        table = frontier.probabilities(system)
        cell = rollout.blank_cell(board, system, region_min=10)
        original = rollout.estimate

        def fake(board_arg, position, layouts, config=None, log=None):
            return 0.9 if position == cell else 0.1

        rollout.estimate = fake
        try:
            choice = rollout.choose_gamble(
                board, table, samples=1, region_min=10, rng=random.Random(1)
            )
        finally:
            rollout.estimate = original
        self.assertIsNotNone(choice)
        self.assertEqual(choice[0], cell)

    def test_gamble_is_none_when_the_edge_cell_simulates_better(self):
        board = support.make_board(9, 9, [(0, 0)], opened_at=[(0, 1), (1, 0), (1, 1)])
        system = frontier.build_system(board)
        table = frontier.probabilities(system)
        original = rollout.estimate
        rollout.estimate = lambda *args, **kwargs: 0.5
        try:
            choice = rollout.choose_gamble(
                board, table, samples=1, region_min=10, rng=random.Random(1)
            )
        finally:
            rollout.estimate = original
        self.assertIsNone(choice)
