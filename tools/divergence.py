"""Show where our solver's first guess differs from EdLogg's, on one board.

Usage: python tools/divergence.py <harness-output> <index> <ed-trace-file>
"""

from __future__ import annotations

import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.solver import benchmark
from minesweeper.solver.engine import resolve_engine
from minesweeper.solver.local import LocalSolver
from minesweeper.solver.strategy import AutoSolver, SolverConfig


def parse_boards(path):
    boards = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 6:
                boards.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[5]))
    return boards


def to_matrix(layout):
    rows = []
    for raw in layout.split("/"):
        if raw:
            rows.append([-1 if ch == "1" else 0 for ch in raw])
    return rows


def edlogg_guesses(trace_path):
    guesses = []
    step = None
    cells = []
    with open(trace_path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "s":
                if step is not None and step["rule"] >= 3:
                    guesses.append((step, cells))
                step = {
                    "step": int(parts[1]),
                    "rule": int(parts[2]),
                    "guesses": int(parts[3]),
                    "prob": float(parts[4]),
                    "remaining": int(parts[5]),
                }
                cells = []
            elif parts[0] == "c":
                cells.append((int(parts[1]), int(parts[2]), int(parts[3])))
    return guesses


def main():
    boards = parse_boards(sys.argv[1])
    index = int(sys.argv[2])
    trace_path = sys.argv[3]
    entry = [b for b in boards if b[0] == index][0]
    matrix = to_matrix(entry[3])

    theirs = edlogg_guesses(trace_path)
    print(f"board {index} seed {entry[1]} edlogg_win={entry[2]}")
    print(f"EdLogg guesses: {[(g['step'], g['rule'], cells) for g, cells in theirs][:6]}")

    engine = resolve_engine("auto")
    board = benchmark.board_from_layout(16, 30, 99, matrix)
    board.expansion(3, 3)
    config = SolverConfig()
    solver = AutoSolver(board, engine=engine, config=config)

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logging.getLogger("minesweeper.solver.strategy").addHandler(Capture())
    logging.getLogger("minesweeper.solver.strategy").setLevel(logging.INFO)

    steps = 0
    for action in solver.actions():
        steps += 1
        is_guess = any("猜" in message or "端局" in message for message in records)
        if is_guess:
            print(f"\nour first guess at step {steps}: {action.kind.name} {action.position}")
            print(f"remaining before our guess: {board.remaining() if hasattr(board, 'remaining') else 'n/a'}")
            local = LocalSolver(board, engine)
            table = local.probabilities(action.position[0], action.position[1], 2)
            print(f"local window table around our pick: {dict(list(table.items())[:8])}")
            break
        records.clear()
        if action.kind.name == "OPEN":
            board.expansion(*action.position)
        else:
            board.mark_mine(*action.position)
    print(f"\nour certain steps before first guess: {steps - 1}")


if __name__ == "__main__":
    main()
