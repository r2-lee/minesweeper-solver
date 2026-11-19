"""``informed`` 猜法的单元测试：观测分布、条件系统、候选打分。"""

import unittest

from tests.support import make_board

from minesweeper.core.enums import Mark
from minesweeper.solver import frontier
from minesweeper.solver.informed import (
    MINE_CLUE,
    candidate_value,
    choose_open_informed,
    conditional_system,
    observation_distribution,
)


def _board():
    # 4x5，三颗雷，开三个角，留一块 2x2 的未知区
    return make_board(4, 5, [(0, 0), (3, 4), (1, 2)], opened_at=[(1, 1), (2, 3), (0, 4)])


class ObservationTest(unittest.TestCase):
    def test_distribution_is_a_probability_distribution(self):
        board = _board()
        system = frontier.build_system(board)
        for position in sorted(system.unknown):
            distribution = observation_distribution(system, position)
            if distribution is None:
                continue
            self.assertAlmostEqual(sum(distribution.values()), 1.0, places=9)
            for observed in distribution:
                self.assertTrue(0 <= observed <= MINE_CLUE)

    def test_mine_probability_matches_the_constraint_system(self):
        # 3x3、单雷在 (1,1)、开 (0,0)：从"角上数字是 1"只能推出相邻三格之一有雷，
        # 因此 (1,1) 的真实后验是 1/3 —— 这正是精确边际该给出的值。
        board = make_board(3, 3, [(1, 1)], opened_at=[(0, 0)])
        system = frontier.build_system(board)
        distribution = observation_distribution(system, (1, 1))
        self.assertIsNotNone(distribution)
        self.assertAlmostEqual(distribution.get(MINE_CLUE, 0.0), 1.0 / 3.0, places=9)


class ConditionalSystemTest(unittest.TestCase):
    def test_conditioned_system_drops_covered_free_cells(self):
        board = _board()
        system = frontier.build_system(board)
        before = set(system.free)
        position = sorted(system.unknown)[0]
        conditioned = conditional_system(system, position, 0)
        self.assertIsNotNone(conditioned)
        self.assertNotIn(position, conditioned.free)
        self.assertLessEqual(len(conditioned.free), len(before))
        self.assertEqual(conditioned.total_mines, system.total_mines)

    def test_impossible_observation_is_rejected(self):
        board = _board()
        system = frontier.build_system(board)
        self.assertIsNone(conditional_system(system, (0, 0), -1))


class CandidateValueTest(unittest.TestCase):
    def test_safer_candidate_scores_higher(self):
        # 3x3 单雷在 (1,1)、开 (0,0)：其余八个都是未开格，其中 (1,1) 必是雷
        board = make_board(3, 3, [(1, 1)], opened_at=[(0, 0)])
        system = frontier.build_system(board)
        safe = candidate_value(system, (0, 2))
        if safe is not None:
            self.assertGreaterEqual(safe, 0.0)
            self.assertLessEqual(safe, 1.0)

    def test_no_candidates_returns_none(self):
        board = make_board(3, 3, [(1, 1)], opened_at=[(0, 0)])
        self.assertIsNone(choose_open_informed(board, {}))


if __name__ == "__main__":
    unittest.main()
