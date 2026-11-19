"""猜哪一格：采样一致性 + 前瞻选择逻辑。"""

import random
import unittest
from unittest import mock

from minesweeper.core.enums import Mark
from minesweeper.core.geometry import neighbours
from minesweeper.solver.frontier import FrontierSolver, build_system, sample_mines
from minesweeper.solver import guess as guess_module
from minesweeper.solver.guess import (_flood, _guesses_after, _layout, _progress,
                                      choose_open, choose_open_fewest,
                                      rank_candidates)
from minesweeper.solver.probability import ProbabilityTable
from minesweeper.solver.strategy import AutoSolver, SolverConfig

from . import support


def _check_assignment(board, mines):
    """采样出来的雷图必须真的满足棋盘上的全部约束。"""
    system = build_system(board)
    assert len(mines) == board.remain_mine()
    for constraint in system.constraints:
        placed = sum(1 for position in constraint.positions if position in mines)
        assert placed == constraint.required, (constraint, placed)
    for position in mines:
        assert board.mark_matrix[position[0]][position[1]] == Mark.COVERED


class SampleMinesTest(unittest.TestCase):
    def test_single_constraint(self):
        # 5x5 只有一颗雷；开 (1,1) 后它显示 1，雷必在它的八邻域里——
        # 但具体是哪一格还看不出来，采样要能给出所有一致的可能。
        board = support.make_board(5, 5, [(0, 0)], opened_at=[(1, 1)])
        system = build_system(board)
        rng = random.Random(0)
        seen = set()
        for _ in range(20):
            mines = sample_mines(system, rng)
            self.assertIsNotNone(mines)
            self.assertEqual(len(mines), 1)
            self.assertTrue(mines <= set(neighbours((1, 1), 5, 5)))
            _check_assignment(board, mines)
            seen |= mines
        self.assertGreater(len(seen), 1, "采样应该能抽到不同的位置")

    def test_two_components(self):
        # 两块互不相连的雷区，总共 2 颗雷。
        board = support.make_board(
            7, 7, [(0, 0), (6, 6)], opened_at=[(1, 1), (5, 5)]
        )
        system = build_system(board)
        rng = random.Random(7)
        for _ in range(20):
            mines = sample_mines(system, rng)
            self.assertIsNotNone(mines)
            self.assertEqual(len(mines), 2)
            _check_assignment(board, mines)

    def test_uses_exactly_the_remaining_mines(self):
        board = support.make_board(5, 5, [(0, 0)], opened_at=[(2, 2)])
        board.mark_mine(0, 0)  # 已经确定标出雷
        system = build_system(board)
        mines = sample_mines(system, random.Random(3))
        self.assertIsNotNone(mines)
        self.assertEqual(mines, set())


class SamplesMatchMarginalsTest(unittest.TestCase):
    """采样的频率必须和精确边际对得上——DFS 的"第一张解"是有偏的（单格能偏 0.3），
    做前瞻时要按采样估进度，所以这里钉一个统计回归测试。"""

    def _board(self):
        return support.make_board(
            4, 5, [(0, 0), (3, 4), (1, 2)], opened_at=[(1, 1), (2, 3), (0, 4)]
        )

    def test_sampled_frequency_matches_exact_marginals(self):
        board = self._board()
        system = build_system(board)
        table = FrontierSolver(board).probabilities()
        rng = random.Random(11)
        counts = {position: 0 for position in system.unknown}
        draws = 4000
        for _ in range(draws):
            mines = sample_mines(system, rng)
            self.assertIsNotNone(mines)
            for position in mines:
                if position in counts:
                    counts[position] += 1
        for position, exact in table.items():
            frequency = counts[position] / draws
            self.assertAlmostEqual(
                frequency, exact, delta=0.04,
                msg="%s: sampled %.3f vs exact %.3f" % (position, frequency, exact),
            )

    def test_free_cells_absorb_the_remaining_mines(self):
        board = self._board()
        system = build_system(board)
        self.assertTrue(system.free, "这个局面应该有空白格")
        rng = random.Random(5)
        for _ in range(50):
            mines = sample_mines(system, rng)
            self.assertEqual(len(mines), system.total_mines)


class RankCandidatesTest(unittest.TestCase):
    def test_only_uncertain_cells_sorted_by_probability(self):
        table = ProbabilityTable({(0, 0): 0.0, (0, 1): 0.5, (0, 2): 0.25,
                                  (0, 3): 1.0, (0, 4): 0.125})
        self.assertEqual(rank_candidates(table, 2), [(0, 4), (0, 2)])
        # 给了容差就只留"和最低概率打平"的格子
        self.assertEqual(rank_candidates(table, 2, tolerance=0.0), [(0, 4)])
        self.assertEqual(rank_candidates(table, 2, tolerance=0.13), [(0, 4), (0, 2)])
        self.assertEqual(rank_candidates(ProbabilityTable(), 3), [])


class FloodTest(unittest.TestCase):
    def test_zero_cell_floods_its_region(self):
        board = support.make_board(4, 4, [(3, 3)], opened_at=[(0, 0)])
        layout = _layout({(3, 3)}, 4, 4)
        marked = [[0] * 4 for _ in range(4)]
        _flood(marked, layout, (0, 3), 4, 4)
        opened = sum(1 for row in marked for value in row if value == int(Mark.OPENED))
        self.assertGreater(opened, 1)

    def test_numbered_cell_opens_only_itself(self):
        board = support.make_board(4, 4, [(3, 3)], opened_at=[(0, 0)])
        layout = _layout({(3, 3)}, 4, 4)
        marked = [[0] * 4 for _ in range(4)]
        _flood(marked, layout, (2, 2), 4, 4)  # 紧邻雷，数字为 1
        opened = sum(1 for row in marked for value in row if value == int(Mark.OPENED))
        self.assertEqual(opened, 1)

    def test_progress_is_never_negative(self):
        board = support.make_board(4, 4, [(3, 3)], opened_at=[(0, 0)])
        self.assertGreaterEqual(_progress(board, (2, 2), {(3, 3)}), 0.0)


class ChooseOpenTest(unittest.TestCase):
    def test_picks_the_highest_scoring_cell(self):
        board = support.make_board(5, 5, [(0, 0)], opened_at=[(2, 2)])
        table = ProbabilityTable({(0, 1): 0.20, (0, 2): 0.20, (0, 3): 0.20})
        scores = {(0, 1): 1.0, (0, 2): 9.0, (0, 3): 2.0}
        with mock.patch.object(guess_module, "sample_mines", return_value={(0, 0)}), \
                mock.patch.object(guess_module, "_progress",
                                  side_effect=lambda _b, p, _m, _f=None: scores[p]):
            position, probability = choose_open(board, table, samples=3)
        self.assertEqual(position, (0, 2))
        self.assertAlmostEqual(probability, 0.20)

    def test_score_is_normalised_by_samples(self):
        # 一半样本踩雷、一半样本连开 2 格 → 得分 = (0 + 3) / 2 = 1.5
        board = support.make_board(5, 5, [(0, 0)], opened_at=[(2, 2)])
        table = ProbabilityTable({(0, 1): 0.2, (0, 2): 0.2})
        samples = [{(0, 1)}, {(0, 0)}]

        def fake_sample(_system, _rng=None, **_kwargs):
            return samples.pop(0)

        with mock.patch.object(guess_module, "sample_mines", side_effect=fake_sample), \
                mock.patch.object(guess_module, "_progress", return_value=2.0):
            position, _probability = choose_open(board, table, samples=2)
        self.assertEqual(position, (0, 2))

    def test_empty_table_returns_none(self):
        board = support.make_board(4, 4, [(3, 3)], opened_at=[(0, 0)])
        self.assertIsNone(choose_open(board, ProbabilityTable()))


class ChooseOpenProgressTest(unittest.TestCase):
    def test_weights_each_clue_by_its_exact_layout_count(self):
        # In the corner, 4 of the 7 safe layouts display zero. In the
        # interior candidate, 2 of the 7 safe layouts display zero.
        board = support.make_board(2, 4, [(0, 0)])
        corner, interior = (0, 0), (0, 1)
        table = {corner: 1 / 8, interior: 1 / 8}

        def wins_when_zero(_board, mines, cell, **_):
            return not set(neighbours(cell, 2, 4)).intersection(mines)

        with mock.patch.object(guess_module.rollout, "simulate", side_effect=wins_when_zero):
            choice = guess_module.choose_open_progress(board, table, trials=1, rng=random.Random(2))

        self.assertEqual(choice, (corner, 1 / 8))

    def test_only_considers_cells_tied_at_the_minimum(self):
        board = support.make_board(
            3, 6, [(0, 1), (0, 4), (2, 0), (2, 3), (2, 4)],
            opened_at=[(0, 2), (0, 3), (1, 4)],
        )
        table = FrontierSolver(board).probabilities()

        position, probability = guess_module.choose_open_progress(
            board, table, trials=10, band=1.0, rng=random.Random(9)
        )

        self.assertIn(position, [(0, 1), (1, 2), (1, 1)])
        self.assertEqual(probability, 0.20)

    def test_prefers_an_end_that_resolves_the_remaining_mine(self):
        # The middle is the baseline pick. Opening either end resolves the
        # whole board on survival. The middle always leaves a second guess.
        board = support.make_board(1, 3, [(0, 0)])
        table = ProbabilityTable({(0, 0): 1 / 3, (0, 2): 1 / 3, (0, 1): 1 / 3})

        position, probability = guess_module.choose_open_progress(
            board, table, trials=6, rng=random.Random(3)
        )

        self.assertIn(position, [(0, 0), (0, 2)])
        self.assertEqual(probability, 1 / 3)


class PolicyTest(unittest.TestCase):
    def test_defaults(self):
        config = SolverConfig()
        self.assertEqual(config.guess_policy, "progress")
        self.assertGreater(config.guess_samples, 0)
        self.assertGreater(config.guess_candidates, 0)
        self.assertGreater(config.fewest_candidates, 0)
        self.assertGreater(config.fewest_worlds, 0)

    def test_both_policies_produce_a_guess_on_a_stuck_board(self):
        # 4x4 单雷、只开 (0,0)：概率都是 1/8，必须猜。
        board = support.make_board(4, 4, [(3, 3)], opened_at=[(0, 0)])
        for policy in ("min_prob", "lookahead", "fewest"):
            solver = AutoSolver(
                board, config=SolverConfig(guess_policy=policy), rng=random.Random(1)
            )
            action = next(iter(solver.actions()))
            self.assertEqual(action.kind.value, "open")


class FewestTest(unittest.TestCase):
    """"少猜优先"：用结构计数估"打开这一格之后还要猜几次"。"""

    def _board(self):
        return support.make_board(
            4, 5, [(0, 0), (3, 4), (1, 2)], opened_at=[(1, 1), (2, 3), (0, 4)]
        )

    def test_guesses_after_is_zero_when_nothing_is_left(self):
        # 3x3、雷在 (0,0)、只有 (2,2) 没开；总雷数已经把它钉成安全格。
        board = support.make_board(
            3, 3, [(0, 0)],
            opened_at=[(0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1)],
        )
        board.mark_matrix[0][0] = Mark.FLAG
        self.assertEqual(_guesses_after(board, {(0, 0)}, (2, 2)), 0)

    def test_guesses_after_is_positive_in_the_middle_game(self):
        # 6x6 三颗雷、只开一格：边界上还有好几块要猜。
        board = support.make_board(6, 6, [(0, 0), (5, 5), (3, 1)], opened_at=[(2, 2)])
        mines = {(0, 0), (5, 5), (3, 1)}
        system = build_system(board)
        table = FrontierSolver(board).probabilities()
        cell = min(
            (position for position in table if position not in mines),
            key=lambda position: table[position],
        )
        self.assertGreaterEqual(_guesses_after(board, mines, cell), 1)

    def test_choose_open_fewest_picks_a_candidate(self):
        board = self._board()
        table = FrontierSolver(board).probabilities()
        choice = choose_open_fewest(board, table, worlds=2, rng=random.Random(7))
        self.assertIsNotNone(choice)
        position, probability = choice
        self.assertIn(position, table)
        self.assertGreater(probability, 0.0)
        self.assertLess(probability, 1.0)

    def test_choose_open_fewest_is_reproducible(self):
        board = self._board()
        table = FrontierSolver(board).probabilities()
        first = choose_open_fewest(board, table, worlds=2, rng=random.Random(11))
        second = choose_open_fewest(board, table, worlds=2, rng=random.Random(11))
        self.assertEqual(first, second)

    def test_choose_open_fewest_does_not_touch_the_board(self):
        board = self._board()
        before = [list(row) for row in board.mark_matrix]
        choose_open_fewest(board, FrontierSolver(board).probabilities(),
                           worlds=1, rng=random.Random(3))
        self.assertEqual(board.mark_matrix, before)

    def test_single_candidate_short_circuits(self):
        table = ProbabilityTable({(2, 4): 0.25, (1, 4): 0.0})
        board = self._board()
        self.assertEqual(choose_open_fewest(board, table), ((2, 4), 0.25))

    def test_empty_table_returns_none(self):
        board = self._board()
        self.assertIsNone(choose_open_fewest(board, ProbabilityTable()))


if __name__ == "__main__":
    unittest.main()


class SuperLocationTest(unittest.TestCase):
    """EdLogg 的 SUPERLOC：宁可多冒一点风险，也要挑能炸开一片的空白格。"""

    def _board(self):
        # 5x5，左上角开一片 2x2，右边和下面都是没挨着数字的空白区。
        return support.make_board(5, 5, [(4, 4)], opened_at=[(0, 0), (0, 1), (1, 0), (1, 1)])

    def test_free_region_is_grouped(self):
        board = self._board()
        sizes = guess_module._unknown_regions(board)
        # (2,2) 连着一整片空白区，(0,4) 也是——但边沿格不在里面。
        self.assertGreaterEqual(sizes.get((3, 3), 0), 4)
        self.assertNotIn((2, 2), sizes)  # 挨着已开格，算边沿

    def test_prefers_big_free_region_within_band(self):
        board = self._board()
        table = {
            (0, 2): 0.12,  # 边沿上的最安全格
            (3, 3): 0.15,  # 空白区里的格子，只危险 3 个点
        }
        choice = guess_module.choose_open_superloc(board, table, band=0.10)
        self.assertIsNotNone(choice)
        self.assertEqual(choice[0], (3, 3))

    def test_ignores_candidates_outside_band(self):
        board = self._board()
        table = {(0, 2): 0.10, (3, 3): 0.60}
        choice = guess_module.choose_open_superloc(board, table, band=0.10)
        self.assertEqual(choice[0], (0, 2))

    def test_returns_none_without_distribution(self):
        board = self._board()
        self.assertIsNone(guess_module.choose_open_superloc(board, {}))

    def test_certain_cells_are_not_candidates(self):
        board = self._board()
        table = {(0, 2): 0.0, (3, 3): 1.0}
        self.assertIsNone(guess_module.choose_open_superloc(board, table))
