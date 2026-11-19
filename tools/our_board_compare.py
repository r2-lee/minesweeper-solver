"""以我们的发牌器为准，比较 EdLogg 求解器与我们的求解器（同一批盘）。

流程：
1. 用 `Board.gen_mine`（我们的发牌器，首点 3x3 安全区）生成 N 张 16x30/99 雷图；
2. 把每张雷图写成 `edl.exe` 的输入文件，跑他自己的 C++ 求解器，取 `win guesses`；
3. 同一张雷图喂我们的 `benchmark.play_game`，统计胜率与猜测次数。

用法：
    python tools/our_board_compare.py <edl.exe> <count> <seed> [--jobs 8]
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import subprocess
import sys
import tempfile
from typing import List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.core.board import Board  # noqa: E402
from minesweeper.solver import strategy  # noqa: E402
from minesweeper.solver.benchmark import play_game  # noqa: E402

_ROWS, _COLS, _MINES = 16, 30, 99
_START = (3, 3)

_ENGINE = None
_EDL = None
_GUESS_COUNT = {"n": 0}
_ORIGINAL_GUESS = strategy.AutoSolver._guess


def _counting_guess(self, *args, **kwargs):
    _GUESS_COUNT["n"] += 1
    return _ORIGINAL_GUESS(self, *args, **kwargs)


def _init(edl: str) -> None:
    global _ENGINE, _EDL
    _EDL = edl
    _ENGINE = strategy.resolve_engine("auto")
    strategy.AutoSolver._guess = _counting_guess


def _layout_matrix(board: Board) -> List[List[int]]:
    return [
        [1 if board.mine_matrix[row][col] == -1 else 0 for col in range(board.cols)]
        for row in range(board.rows)
    ]


def _layout_text(matrix: List[List[int]]) -> str:
    lines = ["%d %d %d %d %d" % (_ROWS, _COLS, _MINES, _START[0], _START[1])]
    for row in matrix:
        lines.append("".join("1" if cell else "0" for cell in row))
    return "\n".join(lines) + "\n"


def _one(task) -> dict:
    index, matrix = task
    handle, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(_layout_text(matrix))
        output = subprocess.run([_EDL, path], capture_output=True, text=True, timeout=120).stdout.split()
    finally:
        os.unlink(path)
    his_win = int(output[0]) if output else 0
    his_guesses = int(output[1]) if len(output) > 1 else 0

    before = _GUESS_COUNT["n"]
    ours_won, _, _ = play_game(
        _ENGINE, _ROWS, _COLS, _MINES, random.Random(1000 + index), layout=matrix, first=_START
    )
    ours_guesses = _GUESS_COUNT["n"] - before
    return {
        "his_win": his_win,
        "his_guesses": his_guesses,
        "our_win": 1 if ours_won else 0,
        "our_guesses": ours_guesses,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edl")
    parser.add_argument("count", type=int)
    parser.add_argument("seed", type=int)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)

    matrices = []
    for index in range(args.count):
        board = Board(_ROWS, _COLS, _MINES, random.Random(args.seed * 100000 + index))
        board.gen_mine(_START)
        matrices.append(_layout_matrix(board))
    tasks = list(enumerate(matrices))

    if args.jobs > 1:
        with multiprocessing.Pool(args.jobs, initializer=_init, initargs=(args.edl,)) as pool:
            results = pool.map(_one, tasks)
    else:
        _init(args.edl)
        results = [_one(task) for task in tasks]

    games = len(results)
    his_wins = sum(r["his_win"] for r in results)
    our_wins = sum(r["our_win"] for r in results)
    his_guesses = sum(r["his_guesses"] for r in results)
    our_guesses = sum(r["our_guesses"] for r in results)
    both = sum(1 for r in results if r["his_win"] and r["our_win"])
    only_his = sum(1 for r in results if r["his_win"] and not r["our_win"])
    only_ours = sum(1 for r in results if r["our_win"] and not r["his_win"])
    print(
        "games %d | EdLogg %d (%.2f%%) | ours %d (%.2f%%) | diff %+.2f pts"
        % (games, his_wins, 100.0 * his_wins / games, our_wins, 100.0 * our_wins / games,
           100.0 * (our_wins - his_wins) / games)
    )
    print("guesses/game: EdLogg %.2f | ours %.2f" % (his_guesses / games, our_guesses / games))
    print("paired: both %d, only EdLogg %d, only ours %d" % (both, only_his, only_ours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
