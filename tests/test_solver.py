"""求解层测试：取值映射、窗口裁剪、局部/全局概率、引擎对照。"""

import random
import unittest

from minesweeper.core.enums import Mark
from minesweeper.solver.engine import (
    EngineUnavailable,
    NativeEngine,
    ReferenceEngine,
    engine_class,
    load_engine,
)
from minesweeper.solver.errors import SolverError
from minesweeper.solver.local import LocalSolver
from minesweeper.solver.whole import WholeSolver
from minesweeper.solver.window import (
    board_values,
    build_window,
    cell_value,
    trim_zero_edges,
)

from .support import make_board


class CellValueTest(unittest.TestCase):
    def test_mapping_matches_legacy_elif_chain(self):
        self.assertEqual(cell_value(Mark.COVERED, 0), 0)
        self.assertEqual(cell_value(Mark.COVERED, -1), 0)
        self.assertEqual(cell_value(Mark.QUESTION, 3), 0)
        self.assertEqual(cell_value(Mark.FLAG, 0), -1)
        self.assertEqual(cell_value(Mark.FLAG, -1), -1)
        self.assertEqual(cell_value(Mark.OPENED, 0), -10)
        self.assertEqual(cell_value(Mark.OPENED, 4), 4)
        self.assertEqual(cell_value(Mark.OPENED, -1), -10)

    def test_board_values(self):
        board = make_board(2, 2, [(0, 0)], opened_at=[(1, 1)])
        self.assertEqual(board_values(board), [[0, 0], [0, 1]])


class TrimZeroEdgesTest(unittest.TestCase):
    def test_trims_outer_rings_but_keeps_inner_ring(self):
        matrix = [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ]
        trimmed, offset = trim_zero_edges(matrix)
        self.assertEqual(offset, (1, 1))
        self.assertEqual(trimmed, [[0, 0, 0], [0, 1, 0], [0, 0, 0]])

    def test_does_not_trim_when_edge_has_content(self):
        matrix = [[1, 0], [0, 0]]
        trimmed, offset = trim_zero_edges(matrix)
        self.assertEqual(trimmed, matrix)
        self.assertEqual(offset, (0, 0))

    def test_all_zero_matrix_collapses(self):
        """旧版在这种极端情况下也会裁成空矩阵，保持等价。"""
        trimmed, offset = trim_zero_edges([[0, 0, 0], [0, 0, 0], [0, 0, 0]])
        self.assertEqual(trimmed, [])
        self.assertEqual(offset, (2, 2))

    def test_empty_matrix(self):
        self.assertEqual(trim_zero_edges([]), ([], (0, 0)))


class BuildWindowTest(unittest.TestCase):
    def test_window_fields(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        window = build_window(board, 1, 1, 2)
        self.assertEqual((window.rows, window.cols), (3, 3))
        self.assertEqual((window.row_offset, window.col_offset), (0, 0))
        self.assertEqual(len(window.flat), 9)
        self.assertEqual(window.matrix[0][0], 0)  # 未展开的雷按 0 处理
        self.assertEqual(window.matrix[1][1], 1)
        self.assertEqual(window.strict_positions, [4])
        self.assertEqual(window.unopened_positions, [0, 1, 2, 3, 5, 6, 7, 8])
        self.assertEqual(window.min_mines, 1)  # 中心数字 1 - 已标雷 0
        self.assertEqual(window.max_mines, 1)
        self.assertEqual(window.center, (1, 1))

    def test_absolute_converts_back(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        window = build_window(board, 1, 1, 2)
        self.assertEqual(window.absolute(4), (1, 1))
        self.assertEqual(window.absolute(0), (0, 0))

    def test_min_mines_subtracts_flags(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        board.mark_matrix[0][0] = Mark.FLAG
        window = build_window(board, 0, 1, 2)
        self.assertEqual(window.min_mines, 0)

    def test_level_one_window_is_smaller(self):
        board = make_board(5, 5, [(0, 0)], opened_at=[(2, 2)])
        window = build_window(board, 2, 2, 1)
        self.assertEqual((window.rows, window.cols), (3, 3))
        self.assertEqual((window.row_offset, window.col_offset), (1, 1))

    def test_empty_window_raises(self):
        board = make_board(2, 2, [])
        with self.assertRaises(SolverError):
            build_window(board, 0, 0, 2)


class LocalSolverTest(unittest.TestCase):
    def setUp(self):
        self.engine = ReferenceEngine()

    def test_ambiguous_cell_gets_uniform_probability(self):
        """3x3、雷在(0,0)、只开(1,1)：8 个候选位置各 1/8。"""
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        probabilities = LocalSolver(board, self.engine).probabilities(1, 1, 2)
        self.assertEqual(len(probabilities), 8)
        for position, value in probabilities.items():
            self.assertAlmostEqual(value, 1.0 / 8)
            self.assertNotEqual(position, (1, 1))

    def test_flagged_mine_makes_everything_safe(self):
        """雷已标出后，中心数字的约束只剩 k=0，窗口内的未开格概率为 0。

        注意窗口只有 2x3：旧版 trim_zero_edges 会连着裁掉底部两行全 0
        （"保留最内侧一行" 的规则），这里沿用旧行为，所以只剩 4 个未开格。
        """
        board = make_board(3, 3, [(0, 0)], opened_at=[(0, 1)])
        board.mark_matrix[0][0] = Mark.FLAG
        probabilities = LocalSolver(board, self.engine).probabilities(0, 1, 2)
        self.assertEqual(len(probabilities), 4)
        self.assertEqual(
            set(probabilities),
            {(0, 2), (1, 0), (1, 1), (1, 2)},
        )
        for value in probabilities.values():
            self.assertEqual(value, 0.0)

    def test_zero_configurations_returns_empty(self):
        class _NoSolutionEngine(ReferenceEngine):
            def local_cal(self, *args, **kwargs):
                return 0, []

        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        probabilities = LocalSolver(board, _NoSolutionEngine()).probabilities(1, 1, 2)
        self.assertEqual(probabilities, {})

    def test_count_minus_one_returns_empty(self):
        """原生模块算不了时返回 -1（KI-1）。

        旧版只判 ``count == 0``，会把 -1 当成"有解"继续算
        ``abs(0 / -1) == 0``，于是把窗口左上角当成"必然安全"去展开。
        """
        class _UnsolvableEngine(ReferenceEngine):
            def local_cal(self, *args, **kwargs):
                return -1, [(0, 0)] * 9

        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        probabilities = LocalSolver(board, _UnsolvableEngine()).probabilities(1, 1, 2)
        self.assertEqual(probabilities, {})

    def test_window_accessor(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        window = LocalSolver(board, self.engine).window(1, 1, 2)
        self.assertEqual(window.center, (1, 1))


class WindowBoundsTest(unittest.TestCase):
    """KI-7：窗口上界漏算边界数字格，曾经把真雷报成 0.0。

    复现用的是真实对局里出现过的那种窗口：中心在右下角 (3,3)，裁剪后矩阵
    ``[[1,2,0],[1,0,0],[1,0,1]]``。只有中心 (3,3) 的八邻域完整落在窗口内，
    但 (13,29) 那种边界候选格同样是候选，必须出现在概率表里。
    """

    MINES = [(1, 3), (2, 2)]
    CANDIDATES = {(1, 3), (2, 2), (2, 3), (3, 2)}

    def setUp(self):
        self.engine = ReferenceEngine()
        self.board = make_board(
            4,
            4,
            self.MINES,
            opened_at=[(r, c) for r in range(4) for c in range(4) if (r, c) not in self.CANDIDATES],
        )

    def test_max_mines_includes_digits_the_center_cannot_see(self):
        window = build_window(self.board, 3, 3, 2)
        self.assertEqual(window.min_mines, 1)
        self.assertEqual(window.max_mines, 4)
        self.assertEqual(len(window.unopened_positions), 4)

    def test_boundary_candidate_gets_a_honest_probability(self):
        probabilities = LocalSolver(self.board, self.engine).probabilities(3, 3, 2)
        self.assertEqual(len(probabilities), 4)
        self.assertAlmostEqual(probabilities[(1, 3)], 0.5)
        for position, value in probabilities.items():
            self.assertGreater(value, 0.0, "{} 不该被判成必然安全".format(position))

    def test_window_without_any_digit_carries_no_information(self):
        """窗口里没有数字格时不能推断任何格子安全（旧版会把整窗报成 0.0）。"""
        board = make_board(3, 3, [(0, 0)], opened_at=[(2, 2)])
        probabilities = LocalSolver(board, self.engine).probabilities(2, 2, 1)
        self.assertEqual(probabilities, {})


class WholeSolverTest(unittest.TestCase):
    def test_whole_board_probabilities(self):
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        probabilities = WholeSolver(board, ReferenceEngine()).probabilities()
        self.assertEqual(len(probabilities), 8)
        for value in probabilities.values():
            self.assertAlmostEqual(value, 1.0 / 8)


class ReferenceEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = ReferenceEngine()

    def test_local_cal_count_and_accumulation(self):
        # 1x3：[未开, 1, 未开] -> 恰好 1 个雷且有 2 种放法
        grid = [0, 1, 0]
        count, result = self.engine.local_cal(grid, 1, 3, 1, 1, [1])
        self.assertEqual(count, 2)
        self.assertEqual(result, [(0, -1), (2, -1)])

    def test_local_cal_early_return_when_max_zero(self):
        count, result = self.engine.local_cal([0, 1, 0], 1, 3, 0, 0, [1])
        self.assertEqual(count, -1)
        self.assertEqual(result, [(0, 0), (0, 0)])

    def test_local_cal_early_return_when_min_greater_than_max(self):
        count, _ = self.engine.local_cal([0, 1, 0], 1, 3, 2, 1, [1])
        self.assertEqual(count, -1)

    def test_local_cal_without_unknown_cells(self):
        count, result = self.engine.local_cal([-10, 1, -10], 1, 3, 0, 2, [1])
        self.assertEqual(count, -1)
        self.assertEqual(result, [])

    def test_local_cal_rejects_negative_min(self):
        with self.assertRaises(ValueError):
            self.engine.local_cal([0, 1, 0], 1, 3, -1, 2, [1])

    def test_whole_cal_early_return(self):
        self.assertEqual(self.engine.whole_cal([0, 1, 0], 1, 3, 0)[0], -1)
        self.assertEqual(self.engine.whole_cal([0, 1, 0], 1, 3, 5)[0], 0)

    def test_mat_valid_functions(self):
        grid = [0, 1, 0]
        self.assertTrue(self.engine.local_mat_valid(grid, 1, 3, []))
        self.assertFalse(self.engine.local_mat_valid(grid, 1, 3, [1]))
        # 补上一颗雷就满足数字 1
        solved = [-1, 1, 0]
        self.assertTrue(self.engine.whole_mat_valid(solved, 1, 3))
        self.assertFalse(self.engine.whole_mat_valid([0, 1, 0], 1, 3))


class EngineFactoryTest(unittest.TestCase):
    def test_engine_class_lookup(self):
        self.assertIs(engine_class("reference"), ReferenceEngine)
        self.assertIs(engine_class("native"), NativeEngine)
        with self.assertRaises(ValueError):
            engine_class("nope")

    def test_load_engine_wraps_injected_module(self):
        class _FakeModule:
            def Local_Mat_Cal(self, matrix, rows, cols, min_x, max_x, inner_pos):
                return 3, [(0, -2)]

            def Whole_Mat_Cal(self, matrix, rows, cols, x):
                return 4, [(0, -1)]

            def local_mat_valid(self, grid, rows, cols, inner_pos):
                return True

            def Whole_Mat_Valid(self, grid, rows, cols):
                return False

        engine = load_engine(_FakeModule())
        self.assertIsInstance(engine, NativeEngine)
        self.assertEqual(engine.local_cal([0], 1, 1, 0, 1, []), (3, [(0, -2)]))
        self.assertEqual(engine.whole_cal([0], 1, 1, 1), (4, [(0, -1)]))
        self.assertTrue(engine.local_mat_valid([0], 1, 1, []))
        self.assertFalse(engine.whole_mat_valid([0], 1, 1))


class NativeParityTest(unittest.TestCase):
    """原生模块与参考实现的对照（没有 pyd 时自动跳过）。"""

    def test_random_small_grids_match(self):
        try:
            native = load_engine()
        except EngineUnavailable:
            self.skipTest("Mat_Cal 不可用，请用 runtime\\python.exe 运行")

        reference = ReferenceEngine()
        rng = random.Random(20240101)
        for _ in range(15):
            rows = rng.randint(1, 3)
            cols = rng.randint(1, 4)
            size = rows * cols
            grid = [rng.choice([0, 0, 0, 0, 1, 2, -1]) for _ in range(size)]
            inner = sorted(rng.sample(range(size), rng.randint(0, size)))

            self.assertEqual(
                reference.local_mat_valid(grid, rows, cols, inner),
                native.local_mat_valid(grid, rows, cols, inner),
            )
            self.assertEqual(
                reference.whole_mat_valid(grid, rows, cols),
                native.whole_mat_valid(grid, rows, cols),
            )
            for max_x in (0, 1, 2, 3):
                self.assertEqual(
                    reference.local_cal(grid, rows, cols, 0, max_x, inner),
                    native.local_cal(grid, rows, cols, 0, max_x, inner),
                )
            for x in (0, 1, 2, 3):
                self.assertEqual(
                    reference.whole_cal(grid, rows, cols, x),
                    native.whole_cal(grid, rows, cols, x),
                )


if __name__ == "__main__":
    unittest.main()
