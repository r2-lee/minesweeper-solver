"""边沿期望搜索（``lookahead``）的测试。

这里只测"结构对不对"：权重是否等于暴力枚举的配置数、深度 1 是否等价于挑最安全的格、
没有边沿/超预算时是否老实返回 ``None``。胜率层面的结论在 README 的对照表里。
"""

import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.solver import lookahead  # noqa: E402
from minesweeper.solver.engine import ReferenceEngine  # noqa: E402
from minesweeper.solver.frontier import build_system  # noqa: E402
from minesweeper.solver.local import LocalSolver  # noqa: E402
from tests import support  # noqa: E402

#: 4x4、3 颗雷挤在左上角，只把 (1,1) 开出来（它的数字是 3）——边沿 8 格、空白 7 格
BOARD = dict(rows=4, cols=4, mines_at=[(0, 0), (0, 1), (1, 0)], opened_at=[(1, 1)])


def build():
    return support.make_board(BOARD["rows"], BOARD["cols"], BOARD["mines_at"],
                              opened_at=BOARD["opened_at"])


class WeightedWorldsTest(unittest.TestCase):
    def test_weights_match_the_closed_form(self):
        system = build_system(build())
        worlds, weights = lookahead._weighted_worlds(system, 10 ** 5)
        self.assertIsNotNone(worlds)
        # 8 个邻居里正好 3 颗雷，空白格一颗都不放 → 每个边沿配置只有 1 种补全
        self.assertEqual(len(worlds), math.comb(8, 3))
        self.assertEqual(set(weights), {1})
        self.assertEqual(sum(weights), math.comb(8, 3))

    def test_no_frontier_returns_nothing(self):
        # (3,3) 挨不着任何雷 → 一条约束都没有 → 没有边沿
        board = support.make_board(4, 4, [(0, 0), (0, 1), (1, 0)], opened_at=[(3, 3)])
        system = build_system(board)
        self.assertEqual(tuple(system.constraints), ())
        worlds, weights = lookahead._weighted_worlds(system, 10 ** 5)
        self.assertIsNone(worlds)
        self.assertIsNone(weights)

    def test_world_limit_is_respected(self):
        system = build_system(build())
        worlds, _ = lookahead._weighted_worlds(system, 3)
        self.assertIsNone(worlds)


class SolveTest(unittest.TestCase):
    def test_depth_one_is_the_safest_cell(self):
        board = build()
        table = LocalSolver(board, ReferenceEngine()).probabilities(1, 1, 1)
        safest = min(table.values())          # 最小"是雷"概率
        position, value = lookahead.solve(board, depth=1, world_limit=10 ** 5)
        self.assertIsNotNone(position)
        # 深度 1 的价值就是"这一步活下来的概率" = 1 - 最安全的雷概率
        self.assertAlmostEqual(value, 1.0 - safest, places=6)
        self.assertAlmostEqual(table[position], safest, places=6)

    def test_depth_two_never_exceeds_depth_one(self):
        board = build()
        _, shallow = lookahead.solve(board, depth=1, world_limit=10 ** 5)
        _, deep = lookahead.solve(board, depth=2, world_limit=10 ** 5)
        self.assertLessEqual(deep, shallow + 1e-9)

    def test_budget_gives_up_cleanly(self):
        board = build()
        self.assertIsNone(
            lookahead.solve(board, depth=8, world_limit=10 ** 5, node_limit=0)
        )

    def test_returns_none_when_everything_is_opened(self):
        board = support.make_board(4, 4, [(0, 0)], opened_at=[(1, 1)])
        support.open_all(board, [(0, 0)])
        self.assertIsNone(lookahead.solve(board))


if __name__ == "__main__":
    unittest.main()
