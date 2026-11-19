"""自动计算策略测试。

用假的局部/全局求解器驱动状态机，这样既能覆盖"升阶 / 切全局 / 猜测"三条分支，
又不用真的跑指数级的组合穷举。
"""

import itertools
import unittest

from minesweeper.solver.strategy import (
    Action,
    ActionKind,
    AutoSolver,
    SolverConfig,
)

from .support import make_board


class FakeLocalSolver:
    def __init__(self, table):
        self.table = dict(table)
        self.calls = []

    def probabilities(self, x, y, level=2):
        self.calls.append((x, y, level))
        return dict(self.table)


class FakeWholeSolver:
    def __init__(self, table):
        self.table = dict(table)
        self.calls = 0

    def probabilities(self):
        self.calls += 1
        return dict(self.table)


def _solver(board, local_table=None, whole_table=None, **config_kwargs):
    local = FakeLocalSolver(local_table or {})
    whole = FakeWholeSolver(whole_table or {})
    # 这里的用例都在测"窗口法"（升阶 / 切全局 / 猜测）那条老路径，
    # 所以显式关掉精确边际，免得被默认值影响。
    config_kwargs.setdefault("exact_marginals", False)
    config = SolverConfig(**config_kwargs)
    return AutoSolver(board, config=config, local_solver=local, whole_solver=whole), local, whole


def _take(iterator, count):
    return list(itertools.islice(iterator, count))


class ActionModelTest(unittest.TestCase):
    def test_kind_values(self):
        self.assertEqual(ActionKind.OPEN.value, "open")
        self.assertEqual(ActionKind.FLAG.value, "flag")

    def test_action_equality(self):
        self.assertEqual(
            Action(ActionKind.OPEN, (1, 2)), Action(ActionKind.OPEN, (1, 2))
        )
        self.assertNotEqual(
            Action(ActionKind.OPEN, (1, 2)), Action(ActionKind.FLAG, (1, 2))
        )

    def test_config_defaults_match_legacy_constants(self):
        config = SolverConfig()
        self.assertEqual(config.max_iterations, 1000)
        self.assertEqual(config.max_level, 2)
        self.assertEqual(config.whole_unopened_limit, 28)
        self.assertEqual(config.whole_mines_limit, 14)
        self.assertTrue(config.exact_marginals)
        self.assertTrue(config.guess_fallback)


class DeterministicActionTest(unittest.TestCase):
    def setUp(self):
        # 3x3，雷在 (0,0)，(0,1) 已展开（显示 1）
        self.board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])

    def test_certain_open_is_yielded(self):
        solver, local, _ = _solver(self.board, local_table={(1, 1): 0.0})
        actions = _take(solver.actions(), 1)
        self.assertEqual(actions, [Action(ActionKind.OPEN, (1, 1))])
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(local.calls[0][0], 0)  # 只对数字格 (0,1) 做局部计算

    def test_certain_flag_is_yielded(self):
        solver, _, _ = _solver(self.board, local_table={(0, 0): 1.0})
        actions = _take(solver.actions(), 1)
        self.assertEqual(actions, [Action(ActionKind.FLAG, (0, 0))])

    def test_probability_without_certainty_is_not_an_action(self):
        """0<概率<1 的格子不应产生动作，否则会自动踩雷。"""
        solver, _, _ = _solver(
            self.board,
            local_table={(1, 1): 0.5},
            whole_unopened_limit=0,  # 禁止切全局，逼它走猜测分支
            max_level=1,
        )
        action = _take(solver.actions(), 1)[0]
        self.assertEqual(action.kind, ActionKind.OPEN)
        self.assertEqual(action.position, (1, 1))


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])

    def test_escalates_level_before_guessing(self):
        solver, local, _ = _solver(
            self.board,
            local_table={(1, 1): 0.5},
            whole_unopened_limit=0,  # 禁止切全局，逼它走"升阶 -> 猜测"
        )
        action = _take(solver.actions(), 1)[0]
        self.assertEqual(action, Action(ActionKind.OPEN, (1, 1)))
        self.assertEqual([call[2] for call in local.calls], [1, 2])

    def test_switches_to_whole_board_mode(self):
        solver, _, whole = _solver(
            self.board,
            local_table={},
            whole_table={(2, 2): 0.0},
            max_level=1,
        )
        action = _take(solver.actions(), 1)[0]
        self.assertEqual(action, Action(ActionKind.OPEN, (2, 2)))
        self.assertEqual(whole.calls, 1)

    def test_guesses_the_lowest_probability_cell(self):
        solver, _, _ = _solver(
            self.board,
            local_table={(0, 0): 0.5, (1, 1): 0.25},
            max_level=1,
            whole_unopened_limit=0,
        )
        action = _take(solver.actions(), 1)[0]
        self.assertEqual(action, Action(ActionKind.OPEN, (1, 1)))

    def test_no_candidate_falls_back_to_a_random_open(self):
        """没有任何概率可用时，默认随机挑一个未开格打开（旧版这里会 UnboundLocalError）。"""
        board = make_board(3, 3, [(0, 0)])  # 全未展开，没有任何数字格
        solver, _, _ = _solver(board)
        actions = _take(solver.actions(), 1)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, ActionKind.OPEN)
        self.assertEqual(board.mark_matrix[actions[0].position[0]][actions[0].position[1]], 0)

    def test_fallback_can_be_switched_off(self):
        """guess_fallback=False 时退回旧语义：安静地结束。"""
        board = make_board(3, 3, [(0, 0)])
        solver, _, _ = _solver(board, guess_fallback=False)
        self.assertEqual(list(solver.actions()), [])

    def test_fallback_gives_up_when_nothing_is_left_to_guess(self):
        """所有格子都已展开或已标记时，不再无限猜下去。"""
        board = make_board(
            3, 3, [(0, 0)], opened_at=[(0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
        )
        board.mark_mine(0, 0)
        solver, _, _ = _solver(board)
        self.assertEqual(list(solver.actions()), [])

    def test_max_iterations_bounds_the_generator(self):
        solver, _, _ = _solver(self.board, local_table={(1, 1): 0.0}, max_iterations=2)
        actions = list(solver.actions())
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(action.kind == ActionKind.OPEN for action in actions))


if __name__ == "__main__":
    unittest.main()
