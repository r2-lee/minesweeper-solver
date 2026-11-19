"""几何换算与概率表的小测试。

这两块是求解器的"公共底座"，出错时症状很隐蔽（概率算错但程序不报错），
所以单独拿出来钉住。
"""

import unittest

from tests import support  # noqa: F401 - 初始化 sys.path / QT_QPA_PLATFORM

from minesweeper.core.geometry import (
    flatten,
    iter_positions,
    neighbours,
    shape,
    to_index,
    to_position,
)
from minesweeper.solver.engine import EngineResult, as_result
from minesweeper.solver.probability import ProbabilityTable, best_guess


class GeometryTest(unittest.TestCase):
    def test_index_and_position_are_inverse(self):
        for position in iter_positions(4, 3):
            self.assertEqual(to_position(to_index(position, 3), 3), position)

    def test_iter_positions_is_row_major(self):
        self.assertEqual(
            list(iter_positions(2, 2)), [(0, 0), (0, 1), (1, 0), (1, 1)]
        )

    def test_neighbours_keeps_legacy_direction_order(self):
        # 角落只有三个邻居，顺序必须和旧版 DIRECTIONS 过滤后一致：
        # (0,1) -> (1,0) -> (1,1)
        self.assertEqual(list(neighbours((0, 0), 3, 3)), [(0, 1), (1, 0), (1, 1)])

    def test_interior_has_eight_neighbours_without_self(self):
        result = list(neighbours((1, 1), 3, 3))
        self.assertEqual(len(result), 8)
        self.assertNotIn((1, 1), result)
        self.assertEqual(len(set(result)), 8)

    def test_neighbours_drops_out_of_range(self):
        self.assertEqual(list(neighbours((0, 0), 1, 1)), [])

    def test_shape_and_flatten(self):
        matrix = [[1, 2], [3, 4]]
        self.assertEqual(shape(matrix), (2, 2))
        self.assertEqual(flatten(matrix), [1, 2, 3, 4])
        self.assertEqual(shape([]), (0, 0))
        self.assertEqual(flatten([]), [])


class ProbabilityTableTest(unittest.TestCase):
    def test_filters_split_zero_one_and_middle(self):
        table = ProbabilityTable({(0, 0): 0.0, (0, 1): 1.0, (0, 2): 0.25})
        self.assertEqual(table.safe(), [(0, 0)])
        self.assertEqual(table.mines(), [(0, 1)])
        self.assertEqual(table.uncertain(), [(0, 2)])

    def test_best_guess_ignores_certainties(self):
        table = ProbabilityTable({(0, 0): 0.0, (0, 1): 1.0, (0, 2): 0.4, (0, 3): 0.2})
        self.assertEqual(table.best_guess(), ((0, 3), 0.2))

    def test_best_guess_returns_none_when_everything_is_certain(self):
        table = ProbabilityTable({(0, 0): 0.0, (0, 1): 1.0})
        self.assertIsNone(table.best_guess())

    def test_ties_keep_the_last_candidate(self):
        # 旧版 `if value <= min_prob` 的语义：后出现的同分者胜出。
        tables = [
            ProbabilityTable({(0, 0): 0.5}),
            ProbabilityTable({(1, 0): 0.5}),
        ]
        self.assertEqual(best_guess(tables), ((1, 0), 0.5))

    def test_from_entries_divides_by_configuration_count(self):
        table = ProbabilityTable.from_entries([(0, -3), (4, -1)], 4, lambda i: (i, 0))
        self.assertEqual(table[(0, 0)], 0.75)
        self.assertEqual(table[(4, 0)], 0.25)

    def test_from_entries_rejects_non_positive_count(self):
        self.assertEqual(ProbabilityTable.from_entries([(0, -1)], -1, lambda i: (i, 0)), {})

    def test_from_engine_result_of_unsolvable_is_empty(self):
        result = EngineResult(-1, [(0, 0)] * 4)
        self.assertFalse(result.usable)
        self.assertEqual(ProbabilityTable.from_engine_result(result, lambda i: (i, 0)), {})

    def test_plain_dict_is_still_a_valid_table(self):
        # 策略层只依赖 Mapping 接口，测试替身可以返回普通 dict。
        tables = [{(0, 0): 0.3}]
        self.assertEqual(best_guess(tables), ((0, 0), 0.3))


class EngineResultTest(unittest.TestCase):
    def test_tuple_from_test_double_is_coerced(self):
        result = as_result((3, [(0, -2)]))
        self.assertIsInstance(result, EngineResult)
        self.assertEqual(result.count, 3)
        self.assertTrue(result.usable)

    def test_engine_result_passes_through(self):
        original = EngineResult(2, [(1, -1)])
        self.assertIs(as_result(original), original)

    def test_equality_with_plain_tuple(self):
        # 测试里大量用 (count, entries) 直接比较，NamedTuple 必须保持相等语义。
        self.assertEqual(EngineResult(2, [(0, -1)]), (2, [(0, -1)]))


if __name__ == "__main__":
    unittest.main()
