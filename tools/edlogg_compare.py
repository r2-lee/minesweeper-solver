"""Compare our solver against EdLogg's on the very same boards.

Input is the output of the compiled harness (``ed.exe one <seed>`` per line, or
``tools/edlogg_harness.py``)::

    <index> <seed> <win> <guesses> <prob> <layout>

where ``layout`` is 16 rows of 30 characters ('1' = mine) separated by '/'.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.core.enums import MINE
from minesweeper.solver import benchmark
from minesweeper.solver.engine import resolve_engine
from minesweeper.solver.strategy import SolverConfig

ROWS = 16
COLS = 30
MINES = 99

_ENGINE = None
_CONFIG: Optional[SolverConfig] = None


def _init(config: Optional[SolverConfig]) -> None:
    global _ENGINE, _CONFIG
    _ENGINE = resolve_engine("auto")
    _CONFIG = config


def _play(task: Sequence[object]) -> Tuple[int, bool, int, str]:
    index, layout = int(task[0]), task[1]
    outcome = benchmark.play_game(
        _ENGINE,
        ROWS,
        COLS,
        MINES,
        layout=layout,
        first=(3, 3),
        config=_CONFIG,
    )
    return index, bool(outcome.won), int(outcome.steps), str(outcome.reason)


def parse_line(line: str) -> Optional[Tuple[int, int, int, str]]:
    parts = line.split()
    if len(parts) != 6:
        return None
    index, seed, win, guesses, prob, layout = parts
    return int(index), int(win), int(guesses), layout


def to_matrix(layout: str) -> List[List[int]]:
    matrix = []
    for raw in layout.split("/"):
        if not raw:
            continue
        matrix.append([MINE if ch == "1" else 0 for ch in raw])
    if len(matrix) != ROWS or any(len(row) != COLS for row in matrix):
        raise ValueError(f"bad layout: {len(matrix)} rows")
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare our solver with EdLogg's on identical boards")
    parser.add_argument("results", help="file produced by the EdLogg harness")
    parser.add_argument("-j", "--jobs", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="only the first N boards")
    parser.add_argument("--guess", default="min_prob")
    parser.add_argument("--mode", default="exact", choices=["exact", "windows"])
    parser.add_argument("--show", type=int, default=5, help="print N disagreement examples")
    args = parser.parse_args()

    boards: List[Tuple[int, int, int, str]] = []
    with open(args.results, "r", encoding="utf-8") as handle:
        for line in handle:
            parsed = parse_line(line.strip())
            if parsed is not None:
                boards.append(parsed)
    if args.limit:
        boards = boards[: args.limit]
    if not boards:
        print("no boards", file=sys.stderr)
        return 1

    config = SolverConfig(
        exact_marginals=args.mode == "exact",
        guess_policy=args.guess,
    )

    tasks = [(index, to_matrix(layout)) for index, win, guesses, layout in boards]
    edlogg_win = {index: bool(win) for index, win, guesses, layout in boards}

    with multiprocessing.Pool(args.jobs, initializer=_init, initargs=(config,)) as pool:
        results = pool.map(_play, tasks, chunksize=8)

    ours = {index: won for index, won, steps, reason in results}
    both = sum(1 for index in ours if ours[index] and edlogg_win[index])
    only_us = sum(1 for index in ours if ours[index] and not edlogg_win[index])
    only_them = sum(1 for index in ours if not ours[index] and edlogg_win[index])
    neither = sum(1 for index in ours if not ours[index] and not edlogg_win[index])
    total = len(ours)

    print(f"boards          {total}")
    print(f"  both win      {both} ({both / total * 100:.2f}%)")
    print(f"  only ours     {only_us} ({only_us / total * 100:.2f}%)")
    print(f"  only EdLogg   {only_them} ({only_them / total * 100:.2f}%)")
    print(f"  neither       {neither} ({neither / total * 100:.2f}%)")
    print(f"ours {sum(ours.values()) / total * 100:.2f}%   EdLogg {sum(edlogg_win.values()) / total * 100:.2f}%")

    if args.show:
        sample = [index for index in ours if ours[index] != edlogg_win[index]][: args.show]
        print("\ndisagreements (index: ours / EdLogg):")
        for index in sample:
            print(f"  {index}: {'win' if ours[index] else 'loss'} / {'win' if edlogg_win[index] else 'loss'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
