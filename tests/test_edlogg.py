"""EdLogg 棋盘生成器的移植测试。

``tools/compare_edlogg.py`` 里的 KISS 是从 https://github.com/EdLogg/MineSweeper
的 ``rand.cpp`` 逐位翻译过来的——这里的期望值就是编译出来的那份 C++ 的输出，
改移植实现时若对不上，说明随机流已经跑偏，同盘对照的结果也就没意义了。
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT, os.path.join(_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from compare_edlogg import Kiss, edlogg_layouts  # noqa: E402


class KissTest(unittest.TestCase):
    def test_matches_the_compiled_cpp(self):
        # rand.cpp: RandomSeed(seed) 之后连续 8 次 Random(16)
        expected = {
            1: [7, 7, 5, 12, 8, 2, 6, 14],
            2: [1, 13, 3, 0, 7, 15, 5, 0],
            3: [11, 3, 1, 3, 7, 12, 4, 3],
        }
        for seed, sequence in expected.items():
            rng = Kiss(seed)
            self.assertEqual([rng.next(16) for _ in range(8)], sequence, seed)

    def test_raw_values_match(self):
        rng = Kiss(7)
        self.assertEqual(
            [rng.next(0) for _ in range(3)],
            [2522077467584461183, 2263197139829774782, 1923124806621135857],
        )

    def test_same_seed_gives_same_stream(self):
        left = [Kiss(11).next(99) for _ in range(5)]
        right = [Kiss(11).next(99) for _ in range(5)]
        self.assertEqual(left, right)


class LayoutTest(unittest.TestCase):
    def test_mine_count_and_clear_start(self):
        for layout in edlogg_layouts(1, 16, 30, 99, (3, 3), 3):
            self.assertEqual(sum(sum(row) for row in layout), 99)
            for row in range(2, 5):
                for col in range(2, 5):
                    self.assertEqual(layout[row][col], 0)

    def test_boards_are_reproducible(self):
        first = list(edlogg_layouts(5, 16, 30, 99, (3, 3), 2))
        second = list(edlogg_layouts(5, 16, 30, 99, (3, 3), 2))
        self.assertEqual(first, second)

    def test_consecutive_boards_differ(self):
        first, second = list(edlogg_layouts(5, 16, 30, 99, (3, 3), 2))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
