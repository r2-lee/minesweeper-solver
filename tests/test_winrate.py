"""胜率回归测试。

完整的三档测量在 ``tools/winrate.py``（高级 16x30/99 跑 100 局约 35 秒），
这里只跑能在几秒内结束的小样本，防止两类致命回归：

* "算不了"被当成"0 概率"（KI-1）——下面直接把概率表的 0/1 和真实雷图比对；
* 策略退化成只能开确定格、或者干脆卡死不动——用固定种子的胜率下限兜住。
"""

import logging
import random
import unittest

from minesweeper.core.board import Board
from minesweeper.core.enums import Mark, Status
from minesweeper.solver.benchmark import game_seeds, play_game, run
from minesweeper.solver.engine import load_engine
from minesweeper.solver.local import LocalSolver
from minesweeper.solver.strategy import ActionKind, AutoSolver

ENGINE = None
ENGINE_ERROR = None


def setUpModule():
    global ENGINE, ENGINE_ERROR
    # 策略层会把"没有可猜测的格子"之类的诊断信息 WARNING 出来，跑测试时静音。
    logging.disable(logging.WARNING)
    try:
        ENGINE = load_engine()
    except Exception as error:  # pragma: no cover - 只有没带 .pyd 的环境会走到
        ENGINE_ERROR = error


def tearDownModule():
    logging.disable(logging.NOTSET)


class EngineMixin(object):
    def setUp(self):
        if ENGINE is None:  # pragma: no cover
            self.skipTest("原生 Mat_Cal 不可用: {}".format(ENGINE_ERROR))
        self.engine = ENGINE


class BenchmarkTest(EngineMixin, unittest.TestCase):
    def test_play_game_returns_known_outcome(self):
        board_rng, solver_rng = game_seeds(2026, 0)
        won, steps, reason = play_game(
            self.engine, 9, 9, 10, board_rng, solver_rng
        )
        self.assertIn(reason, ("win", "boom", "dead-end", "timeout"))
        self.assertGreater(steps, 0)
        self.assertEqual(won, reason == "win")

    def test_game_seeds_are_reproducible(self):
        first = Board(9, 9, 10, rng=game_seeds(7, 3)[0])
        second = Board(9, 9, 10, rng=game_seeds(7, 3)[0])
        first.gen_mine((4, 4))
        second.gen_mine((4, 4))
        self.assertEqual(first.mine_matrix, second.mine_matrix)


class CertaintyTest(EngineMixin, unittest.TestCase):
    """"必然是雷/必然安全"必须和真实雷图一致（KI-1 回归）。

    修复前：原生模块返回 ``count == -1``（算不了）时，旧代码只判 ``count == 0``，
    于是把它当成"有解"，``abs(0 / -1) == 0``，窗口里的格子全被标成"必然安全"，
    自动计算会径直踩雷。这里边算边和真实雷图对照，出现一次就失败。
    """

    def test_certain_probabilities_match_the_truth(self):
        for seed in (0, 1):
            board = Board(9, 9, 10, rng=random.Random(seed))
            first = board.random_position()
            board.gen_mine(first)
            board.expansion(*first)
            local = LocalSolver(board, self.engine)
            solver = AutoSolver(board, engine=self.engine, rng=random.Random(seed + 99))

            for index, action in enumerate(solver.actions()):
                if index >= 40:
                    break
                if action.kind is ActionKind.OPEN:
                    status, _ = board.expansion(*action.position)
                    if status is Status.FAIL:
                        break
                else:
                    board.mark_mine(*action.position)
                self._check_certainties(board, local, seed)

    def _check_certainties(self, board, local, seed):
        for row in range(board.rows):
            for col in range(board.cols):
                if board.mark_matrix[row][col] != Mark.OPENED:
                    continue
                if board.mine_matrix[row][col] <= 0:
                    continue  # 只看数字格，空白格没有约束
                for position, value in local.probabilities(row, col, 2).items():
                    truth = board.mine_matrix[position[0]][position[1]] == -1
                    if value == 0.0:
                        self.assertFalse(
                            truth,
                            "种子 {} 把雷 {} 算成了必然安全".format(seed, position),
                        )
                    elif value == 1.0:
                        self.assertTrue(
                            truth,
                            "种子 {} 把安全格 {} 算成了必然有雷".format(seed, position),
                        )


class WinRateTest(EngineMixin, unittest.TestCase):
    """固定种子的小样本胜率下限。

    数字来自 ``tools/winrate.py --seed 2026``：初级 100 局 93%、中级 84%、
    高级 43%。这里取更小的样本，阈值留了余量（实测 18/20 与 5/10）。
    """

    def test_beginner_win_rate(self):
        result = run(
            rows=9, cols=9, mines=10, games=20, seed=2026, engine=self.engine
        )
        self.assertGreaterEqual(result["wins"], 16, result["reasons"])

    def test_expert_win_rate(self):
        result = run(
            rows=16, cols=30, mines=99, games=10, seed=2026, engine=self.engine
        )
        self.assertGreaterEqual(result["wins"], 2, result["reasons"])


if __name__ == "__main__":
    unittest.main()
