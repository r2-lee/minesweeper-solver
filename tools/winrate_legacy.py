"""在同一批雷图上对比"重构后的新算法"与"backup 里的旧算法"的胜率。

旧算法没有单独的模块入口（它和界面混在一个文件里），这里直接把
``backup/mine_original.py`` 前 486 行（到 ``base_MineDetection`` 结束）exec 出来，
只取它的棋盘状态机和 ``auto_calculate()`` 生成器，不碰任何 Qt 界面代码。

用法::

    runtime\\python.exe tools\\winrate_legacy.py -n 50 --seed 2026

两边的雷图完全一致：第 *i* 局用 ``Random(seed * 100000 + i)`` 布雷，新算法的猜测
随机数用 ``Random(seed * 100000 + i + 50000)``，互不干扰。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.core.board import Board  # noqa: E402
from minesweeper.solver.benchmark import game_seeds, open_first_cell, play_game  # noqa: E402
from minesweeper.solver.engine import load_engine  # noqa: E402

LEGACY_PATH = os.path.join(_ROOT, "backup", "mine_original.py")
LEGACY_END_LINE = 486  # base_MineDetection 的最后一行（mine_mark 的 return）


class _DevNull(object):
    """替代 io.StringIO 的丢弃流，旧算法打印量很大，不留内存。"""

    def write(self, text):
        return len(text)

    def flush(self):
        pass


def load_legacy():
    """把旧文件的前 486 行 exec 到一个独立命名空间，返回其中的名字。"""
    with open(LEGACY_PATH, encoding="utf-8") as handle:
        lines = handle.readlines()
    head = "".join(lines[:LEGACY_END_LINE])
    namespace = {"__name__": "legacy_mine", "__file__": LEGACY_PATH}
    exec(compile(head, LEGACY_PATH, "exec"), namespace)  # noqa: S102 - 只读旧算法
    return namespace


def make_board(rows, cols, mines, board_rng):
    """按给定随机数布雷并展开首格，返回 (board, 首格)。"""
    board = Board(rows, cols, mines, rng=board_rng)
    first = open_first_cell(board, board_rng)
    return board, first


class LegacyPlayer(object):
    """驱动旧 ``base_MineDetection`` 的棋盘状态机。"""

    def __init__(self, legacy, board, first):
        self.status = legacy["Status"]
        self.game = legacy["base_MineDetection"](board.rows, board.cols, board.mines)
        self.game.mine_Matrix = [row[:] for row in board.mine_matrix]
        self.game.index_Matrix = [[1] * board.cols for _ in range(board.rows)]
        self.game.mark_Matrix = [[0] * board.cols for _ in range(board.rows)]
        state, _ = self.game.expansion(*first)
        self.won = state is self.status.WIN
        self.lost = state is self.status.FAIL
        self.stuck = False
        self.generator = None if self.won else self.game.auto_calculate()

    def step(self):
        """走一步。返回 (是否仍在进行, 结果)，结果为 win/boom/stuck/None。"""
        if self.won:
            return False, "win"
        try:
            open_list, mark_list = next(self.generator)
        except StopIteration:
            self.won = self.game.win_judge()
            return False, "win" if self.won else "dead-end"
        except UnboundLocalError:
            # 旧版"算不出下一步还硬要猜"时会在这里炸掉（DEV-1）。
            self.won = self.game.win_judge()
            return False, "win" if self.won else "stuck"
        for position in open_list:
            state, _ = self.game.expansion(*position)
            if state is self.status.FAIL:
                return False, "boom"
            if state is self.status.WIN:
                self.won = True
                return False, "win"
        for position in mark_list:
            if self.game.mine_mark(*position) is self.status.WIN:
                self.won = True
                return False, "win"
        return True, None


def play_legacy(legacy, rows, cols, mines, board_rng, max_steps=5000):
    board, first = make_board(rows, cols, mines, board_rng)
    player = LegacyPlayer(legacy, board, first)
    steps = 0
    # 旧算法每一步都往 stdout 打印调试信息，测量时全部吞掉。
    with contextlib.redirect_stdout(_DevNull()):
        while True:
            running, outcome = player.step()
            if outcome is not None:
                return outcome == "win", steps, outcome
            steps += 1
            if steps > max_steps:
                return False, steps, "timeout"


def play_new(engine, rows, cols, mines, board_rng, solver_rng, max_steps=5000):
    won, steps, reason = play_game(
        engine, rows, cols, mines, board_rng, solver_rng, max_actions=max_steps
    )
    return won, steps, reason


def main(argv=None):
    parser = argparse.ArgumentParser(description="新旧算法同雷图胜率对比")
    parser.add_argument("-n", "--games", type=int, default=40)
    parser.add_argument("--rows", type=int, default=16)
    parser.add_argument("--cols", type=int, default=30)
    parser.add_argument("--mines", type=int, default=99)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)

    if not os.path.isfile(LEGACY_PATH):  # pragma: no cover - 备份缺失时直接报错
        print("找不到旧算法备份: {}".format(LEGACY_PATH))
        return 1

    legacy = load_legacy()
    engine = load_engine()
    tally = {
        "legacy": {"win": 0, "boom": 0, "dead-end": 0, "stuck": 0, "timeout": 0},
        "new": {"win": 0, "boom": 0, "dead-end": 0, "timeout": 0},
    }
    start = time.time()
    for index in range(args.games):
        base = args.seed * 100000 + index
        legacy_won, legacy_steps, legacy_reason = play_legacy(
            legacy, args.rows, args.cols, args.mines, random.Random(base)
        )
        new_won, new_steps, new_reason = play_new(
            engine,
            args.rows,
            args.cols,
            args.mines,
            random.Random(base),
            random.Random(base + 50000),
        )
        tally["legacy"][legacy_reason] += 1
        tally["new"][new_reason] += 1
        print(
            "第 {:2d} 局: 旧 {:4s}({:4d} 步, {:8s})   新 {:4s}({:4d} 步, {:8s})".format(
                index + 1,
                "胜利" if legacy_won else "失败",
                legacy_steps,
                legacy_reason,
                "胜利" if new_won else "失败",
                new_steps,
                new_reason,
            ),
            flush=True,
        )

    games = float(args.games)
    print("-" * 62)
    print("棋盘: {}x{} / {} 雷   局数: {}".format(args.rows, args.cols, args.mines, args.games))
    print("旧算法胜率: {:5.1%}   {}".format(tally["legacy"]["win"] / games, tally["legacy"]))
    print("新算法胜率: {:5.1%}   {}".format(tally["new"]["win"] / games, tally["new"]))
    print("总耗时: {:.1f}s".format(time.time() - start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
