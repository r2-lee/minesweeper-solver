"""同一批棋盘、同一个裁判：EdLogg 与我们各跑 N 局，比较胜率与"真正无法确定的决策"次数。

一局里两件事都做：
1. 跑 `ed.exe trace <seed>` 拿到他的逐步差分行 → 重放出每步棋盘 → 用我们的精确表
   判断他的每次猜测是否"真正无法确定"（`referee_guesses.replay`）；
2. 用同一张雷图跑我们的求解器（`benchmark.play_game`），统计胜率与猜测次数。

用法：
    python tools/referee_compare.py <ed.exe> <count> <seed> [--jobs 8]
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import subprocess
import sys
from typing import List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT, os.path.join(_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.solver.benchmark import play_game  # noqa: E402
from minesweeper.solver import strategy  # noqa: E402
from referee_guesses import _parse_layout, replay  # noqa: E402

_ROWS, _COLS, _MINES = 16, 30, 99
_ENGINE = None
_ED = None
_GUESS_COUNT = {"n": 0}
_ORIGINAL_GUESS = strategy.AutoSolver._guess


def _counting_guess(self, *args, **kwargs):
    _GUESS_COUNT["n"] += 1
    return _ORIGINAL_GUESS(self, *args, **kwargs)


def _init(ed: str) -> None:
    global _ENGINE, _ED
    _ED = ed
    _ENGINE = strategy.resolve_engine("auto")
    strategy.AutoSolver._guess = _counting_guess


def _layout_matrix(ed: str, seed: str) -> List[List[int]]:
    output = subprocess.run([ed, "trace", seed], capture_output=True, text=True, check=True).stdout
    for line in output.splitlines():
        if line.startswith("end "):
            cells = set(_parse_layout(line.split()[4], _ROWS, _COLS))
            return [
                [1 if (row, col) in cells else 0 for col in range(_COLS)]
                for row in range(_ROWS)
            ]
    raise ValueError("trace did not contain an end line")


def _one(task) -> dict:
    index, seed = task
    ours_guesses_before = _GUESS_COUNT["n"]
    ours_won, _, _ = play_game(
        _ENGINE, _ROWS, _COLS, _MINES, random.Random(1000 + index), layout=_layout_matrix(_ED, seed),
        first=(3, 3),
    )
    ours_guesses = _GUESS_COUNT["n"] - ours_guesses_before
    his = replay(_ED, seed, _ROWS, _COLS, _MINES)
    return {
        "seed": seed,
        "his_win": 1 if his["won"] else 0,
        "his_guesses": his["guesses"],
        "his_genuine": his["genuine"],
        "our_win": 1 if ours_won else 0,
        "our_guesses": ours_guesses,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ed")
    parser.add_argument("count", type=int)
    parser.add_argument("seed")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)

    global _ED
    _ED = args.ed
    chain = subprocess.run(
        [args.ed, "chain", str(args.count), args.seed], capture_output=True, text=True, check=True
    ).stdout.split()
    tasks = list(enumerate(chain))

    if args.jobs > 1:
        with multiprocessing.Pool(args.jobs, initializer=_init, initargs=(args.ed,)) as pool:
            results = pool.map(_one, tasks)
    else:
        _init(args.ed)
        results = [_one(task) for task in tasks]

    games = len(results)
    his_wins = sum(r["his_win"] for r in results)
    our_wins = sum(r["our_win"] for r in results)
    his_guesses = sum(r["his_guesses"] for r in results)
    his_genuine = sum(r["his_genuine"] for r in results)
    our_guesses = sum(r["our_guesses"] for r in results)
    both = sum(1 for r in results if r["his_win"] and r["our_win"])
    only_his = sum(1 for r in results if r["his_win"] and not r["our_win"])
    only_ours = sum(1 for r in results if r["our_win"] and not r["his_win"])
    print(
        "games %d | EdLogg wins %d (%.2f%%) | ours wins %d (%.2f%%) | diff %+.2f pts"
        % (games, his_wins, 100.0 * his_wins / games, our_wins, 100.0 * our_wins / games,
           100.0 * (our_wins - his_wins) / games)
    )
    print(
        "guesses/game: EdLogg counted %.2f, genuine %.2f | ours %.2f"
        % (his_guesses / games, his_genuine / games, our_guesses / games)
    )
    print("paired: both %d, only EdLogg %d, only ours %d" % (both, only_his, only_ours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
