"""边沿组件分解 + 总雷数卷积（精确边际）的测试。

验证方式有两层：

1. 小棋盘上用**暴力枚举**（``itertools.combinations`` 遍历所有可能布雷）
   当预言机，逐个格子比对概率；
2. 手工构造的边沿形状（单约束、双约束共享格、两个不连通组件）上验证
   组件分解与总雷数卷积的语义。
"""

import itertools
import unittest

from minesweeper.core.board import Board
from minesweeper.core.enums import Mark
from minesweeper.core.geometry import iter_positions, neighbours
from minesweeper.solver.engine import ReferenceEngine
from minesweeper.solver.frontier import (
    Constraint,
    ConstraintSystem,
    FrontierSolver,
    FrontierTooLarge,
    build_system,
    probabilities,
)
from minesweeper.solver.strategy import Action, ActionKind, AutoSolver, SolverConfig
from minesweeper.solver.window import board_values

from .support import make_board


def brute_force(board):
    """遍历所有合法布雷，返回 ``{位置: 概率}``（无解时返回空表）。"""
    values = board_values(board)
    unknown = [p for p in iter_positions(board.rows, board.cols) if values[p[0]][p[1]] == 0]
    total = board.remain_mine()
    checks = []
    for position in iter_positions(board.rows, board.cols):
        number = values[position[0]][position[1]]
        if number < 1:
            continue
        cells = [q for q in neighbours(position, board.rows, board.cols)
                 if values[q[0]][q[1]] == 0]
        flagged = sum(1 for q in neighbours(position, board.rows, board.cols)
                      if values[q[0]][q[1]] == -1)
        checks.append((set(cells), number - flagged))

    mine_counts = {position: 0 for position in unknown}
    good = 0
    for combo in itertools.combinations(unknown, total):
        chosen = set(combo)
        if all(len(cells & chosen) == required for cells, required in checks):
            good += 1
            for position in combo:
                mine_counts[position] += 1
    if not good:
        return {}
    return {position: count / float(good) for position, count in mine_counts.items()}


class BruteForceParityTest(unittest.TestCase):
    """与暴力枚举逐格对比。"""

    def assert_matches_brute_force(self, board):
        expected = brute_force(board)
        system = build_system(board)
        got = probabilities(system) if system.consistent else {}
        self.assertEqual(set(expected), set(got))
        for position, value in expected.items():
            self.assertAlmostEqual(got[position], value, places=12, msg=str(position))

    def test_opened_number_in_the_middle(self):
        # 3x3、雷 (0,0)，中间 (1,1) 已开（显示 1）：8 个未知格各 1/8
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        self.assert_matches_brute_force(board)
        table = FrontierSolver(board).probabilities()
        self.assertEqual(len(table), 8)
        for value in table.values():
            self.assertAlmostEqual(value, 0.125)

    def test_two_constraints_sharing_a_cell(self):
        board = make_board(4, 4, [(0, 0), (2, 0)], opened_at=[(0, 1), (1, 1), (2, 1)])
        self.assert_matches_brute_force(board)

    def test_disjoint_components(self):
        board = make_board(
            6, 6, [(0, 0), (5, 5)], opened_at=[(0, 1), (1, 0), (5, 4), (4, 5)]
        )
        self.assert_matches_brute_force(board)

    def test_flagged_cells_are_subtracted(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        board.mark_matrix[0][0] = Mark.FLAG  # 已经标出一颗雷
        self.assert_matches_brute_force(board)

    def test_matches_whole_solver_on_small_board(self):
        """小棋盘上应与"整盘穷举"给出同样的数字（两条独立实现互证）。"""
        from minesweeper.solver.whole import WholeSolver

        board = make_board(4, 4, [(1, 1), (2, 3)], opened_at=[(0, 0), (0, 1), (1, 0)])
        whole = WholeSolver(board, ReferenceEngine()).probabilities()
        exact = FrontierSolver(board).probabilities()
        for position, value in whole.items():
            if position in exact:
                self.assertAlmostEqual(exact[position], value, places=10)


class ConstraintModelTest(unittest.TestCase):
    def test_constraint_counts_unknown_neighbours(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        system = build_system(board)
        self.assertTrue(system.consistent)
        self.assertEqual(len(system.constraints), 1)
        constraint = system.constraints[0]
        self.assertEqual(set(constraint.positions),
                         {(0, 0), (0, 2), (1, 0), (1, 1), (1, 2)})
        self.assertEqual(constraint.required, 1)

    def test_free_cells_are_the_ones_without_any_constraint(self):
        board = make_board(4, 4, [(0, 0)], opened_at=[(0, 1)])
        system = build_system(board)
        free = set(system.free)
        self.assertIn((3, 3), free)
        self.assertNotIn((1, 1), free)  # (1,1) 属于 (0,1) 的邻域
        self.assertEqual(len(free) + len(system.frontier) + len(
            [p for p in iter_positions(4, 4) if board_values(board)[p[0]][p[1]] != 0]
        ), 16)

    def test_inconsistent_when_flags_exceed_the_number(self):
        board = make_board(3, 3, [(0, 0), (0, 2)], opened_at=[(0, 1)])
        board.mark_matrix[0][0] = Mark.FLAG
        board.mark_matrix[0][2] = Mark.FLAG
        # (0,1) 显示 2，周围却标了两颗雷 → required 变成 0，仍然自洽；
        # 换成数字 1 的格子超标记才会矛盾：
        board2 = make_board(3, 3, [(0, 0), (0, 2)], opened_at=[(1, 1)])
        self.assertTrue(build_system(board2).consistent)

    def test_required_negative_is_inconsistent(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        board.mark_matrix[0][0] = Mark.FLAG
        board.mark_matrix[1][1] = Mark.FLAG
        board.mark_matrix[1][0] = Mark.FLAG
        system = build_system(board)
        self.assertFalse(system.consistent)
        self.assertEqual(dict(probabilities(system)), {})

    def test_component_split(self):
        # 两个数字格离得很远 → 两条互不相干的约束
        board = make_board(
            8, 8, [(0, 0), (7, 7)], opened_at=[(0, 1), (7, 6)]
        )
        system = build_system(board)
        components = system.components()
        self.assertEqual(len(components), 2)

    def test_budget_guard(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        system = build_system(board)
        with self.assertRaises(FrontierTooLarge):
            probabilities(system, budget=10)


class TotalMineConvolutionTest(unittest.TestCase):
    def test_remaining_mines_flow_into_free_cells(self):
        """一颗雷被约束在边沿，另一颗只能在空白区 → 空白格概率由余数决定。"""
        # 5x5、两颗雷 (0,0)、(4,4)；只开 (0,1)：它显示 1，邻域里必有一颗雷；
        # 另一颗必然落在剩下的空白格里。
        board = make_board(5, 5, [(0, 0), (4, 4)], opened_at=[(0, 1)])
        table = FrontierSolver(board).probabilities()
        system = build_system(board)
        self.assertEqual(system.total_mines, 2)
        free = set(system.free)
        self.assertTrue(free)
        expected_density = None
        for position in free:
            if expected_density is None:
                expected_density = table[position]
            self.assertAlmostEqual(table[position], expected_density)
        # 空白格概率必须低于边沿格（边沿被"钉住"了一颗雷）
        frontier_values = [table[p] for p in system.frontier]
        self.assertGreater(min(frontier_values), expected_density)

    def test_all_mines_accounted_for_inside_frontier(self):
        """总雷数刚好等于边沿需求时，空白格概率必须是 0。"""
        # 3x3、一颗雷 (0,0)，开 (0,1)：唯一一颗雷在邻域里 → 其它格子全安全
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        table = FrontierSolver(board).probabilities()
        system = build_system(board)
        for position in system.free:
            self.assertEqual(table[position], 0.0)


class ExactStrategyTest(unittest.TestCase):
    def test_exact_mode_uses_frontier_table(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        solver = AutoSolver(board, config=SolverConfig(exact_marginals=True))
        action = next(solver.actions())
        self.assertEqual(action.kind, ActionKind.OPEN)
        # 3x3 全盘精确：唯一那颗雷就在 (0,0)，其余全安全
        self.assertNotEqual(action.position, (0, 0))

    def test_exact_mode_falls_back_to_windows_on_oversized_component(self):
        class Exploding:
            def probabilities(self, values=None):
                raise FrontierTooLarge("too big")

        class StubLocal:
            def __init__(self):
                self.calls = []

            def probabilities(self, x, y, level=2):
                self.calls.append((x, y, level))
                return {(1, 1): 0.0}

        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        local = StubLocal()
        solver = AutoSolver(
            board,
            config=SolverConfig(exact_marginals=True),
            local_solver=local,
            whole_solver=StubLocal(),
            frontier_solver=Exploding(),
        )
        action = next(solver.actions())
        self.assertEqual(action, Action(ActionKind.OPEN, (1, 1)))
        self.assertTrue(local.calls)

    def test_window_mode_still_available(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        solver = AutoSolver(board, config=SolverConfig(exact_marginals=False))
        actions = list(itertools.islice(solver.actions(), 1))
        self.assertEqual(len(actions), 1)


if __name__ == "__main__":
    unittest.main()

class ReachableExactnessTest(unittest.TestCase):
    """对照暴力枚举：在可达局面下，精确边际必须逐格相等。

    构造方式是"矩形未知块 + 其余全开"，并且要求所有 0 数字的已开格
    八邻域里没有未知格（否则该局面在真实对局中不可能出现：0 格会把
    邻居一起翻开）。
    """

    def _state(self, rng, rows=5, cols=5):
        cells = [(r, c) for r in range(rows) for c in range(cols)]
        r0 = rng.randint(0, rows - 3)
        c0 = rng.randint(0, cols - 3)
        h = rng.randint(2, 3)
        w = rng.randint(2, 3)
        unknown = [(r, c) for r in range(r0, r0 + h) for c in range(c0, c0 + w)]
        covered = set(unknown)
        mines = rng.randint(1, min(3, len(unknown) - 1))
        mine_set = set(rng.sample(unknown, mines))
        numbers = {}
        for p in cells:
            if p in covered:
                continue
            numbers[p] = sum(
                1
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if (dr, dc) != (0, 0) and (p[0] + dr, p[1] + dc) in mine_set
            )
        for p, number in numbers.items():
            if number == 0 and any(
                (p[0] + dr, p[1] + dc) in covered
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
            ):
                return None
        return unknown, numbers, mines

    def test_marginals_match_brute_force_on_reachable_states(self):
        import itertools
        import random

        from minesweeper.solver import frontier

        rng = random.Random(2024)
        checked = 0
        while checked < 25:
            state = self._state(rng)
            if state is None:
                continue
            unknown, numbers, mines = state
            covered = set(unknown)
            constraints = []
            touched = set()
            for p, number in numbers.items():
                if number <= 0:
                    continue
                positions = tuple(
                    (p[0] + dr, p[1] + dc)
                    for dr in (-1, 0, 1)
                    for dc in (-1, 0, 1)
                    if (dr, dc) != (0, 0) and (p[0] + dr, p[1] + dc) in covered
                )
                if positions:
                    constraints.append(frontier.Constraint(positions, number))
                    touched.update(positions)
            system = frontier.ConstraintSystem(
                tuple(constraints),
                tuple(p for p in unknown if p in touched),
                tuple(p for p in unknown if p not in touched),
                mines,
            )
            table = frontier.probabilities(system)
            self.assertTrue(table, "exact marginals must not be empty")

            layouts = []
            for combo in itertools.combinations(unknown, mines):
                layout = set(combo)
                if all(
                    sum(
                        1
                        for dr in (-1, 0, 1)
                        for dc in (-1, 0, 1)
                        if (dr, dc) != (0, 0) and (p[0] + dr, p[1] + dc) in layout
                    )
                    == number
                    for p, number in numbers.items()
                ):
                    layouts.append(layout)
            self.assertTrue(layouts, "the true layout is always consistent")

            for p in unknown:
                expected = sum(1 for layout in layouts if p in layout) / len(layouts)
                self.assertAlmostEqual(table[p], expected, places=9, msg=str(p))
            checked += 1
