"""Replay EdLogg's traced moves on our board model and compare every guess.

For each guess step we know the exact state (because we replay every Expose/AddMine
they made), so we can ask: what was the true risk of their pick, and what would
"pick the lowest-probability cell" have chosen instead?
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.core.enums import MINE, Mark
from minesweeper.solver import benchmark, frontier
from minesweeper.solver.probability import best_guess


def parse_trace(path):
    steps = []
    current = None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "s":
                if current is not None:
                    steps.append(current)
                current = {
                    "step": int(parts[1]),
                    "rule": int(parts[2]),
                    "guesses": int(parts[3]),
                    "prob": float(parts[4]),
                    "remaining": int(parts[5]),
                    "calls": [],
                }
            elif parts[0] == "c" and current is not None:
                current["calls"].append((int(parts[1]), int(parts[2]), int(parts[3])))
    if current is not None:
        steps.append(current)
    return steps


def to_matrix(layout):
    rows = []
    for raw in layout.split("/"):
        if raw:
            rows.append([MINE if ch == "1" else 0 for ch in raw])
    return rows


def analyse(layout, trace_path):
    board = benchmark.board_from_layout(16, 30, 99, to_matrix(layout))
    board.expansion(3, 3)

    records = []
    for step in parse_trace(trace_path):
        guess = step["rule"] >= 3
        if guess and step["calls"]:
            system = frontier.build_system(board)
            table = frontier.probabilities(system)
            their = step["calls"][0]
            their_cell = (their[2], their[1])  # trace stores (kind, x, y); our board is (row, col)
            our_choice = best_guess([table])
            ours = our_choice[0] if our_choice is not None else None
            their_risk = table.get(their_cell)
            our_risk = table[ours] if ours is not None else None
            their_mine = board.mine_matrix[their_cell[0]][their_cell[1]] == MINE
            our_mine = board.mine_matrix[ours[0]][ours[1]] == MINE if ours is not None else None
            records.append(
                {
                    "step": step["step"],
                    "rule": step["rule"],
                    "their_cell": their_cell,
                    "their_risk": their_risk,
                    "their_mine": their_mine,
                    "our_cell": ours,
                    "our_risk": our_risk,
                    "our_mine": our_mine,
                }
            )
        for kind, x, y in step["calls"]:
            if not (0 <= x < 30 and 0 <= y < 16):
                continue  # the C code traces neighbour probes before its own bounds check
            if kind == 0:
                board.expansion(y, x)
            elif board.mark_matrix[y][x] == Mark.COVERED:
                board.mark_mine(y, x)
    return records


def _run(task):
    index, layout, exe = task
    seed = None
    return index, layout, exe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", help="harness output with layouts")
    parser.add_argument("--exe", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--tmp", default=os.environ.get("TEMP", "."))
    args = parser.parse_args()

    boards = []
    with open(args.results, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 6:
                boards.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[5]))
    boards = boards[: args.limit]

    total = 0
    better = 0
    worse = 0
    same = 0
    killed = 0
    saved = 0
    for index, seed, win, layout in boards:
        trace_path = os.path.join(args.tmp, f"trace_{index}.txt")
        with open(trace_path, "w", encoding="utf-8") as out:
            subprocess.run([args.exe, "trace", str(seed)], stdout=out, timeout=300)
        for record in analyse(layout, trace_path):
            total += 1
            if record["their_mine"] and not record["our_mine"]:
                killed += 1
            elif record["our_mine"] and not record["their_mine"]:
                saved += 1
            if record["their_risk"] is not None and record["our_risk"] is not None:
                if record["their_risk"] > record["our_risk"] + 1e-9:
                    worse += 1
                elif record["their_risk"] < record["our_risk"] - 1e-9:
                    better += 1
                else:
                    same += 1

    print(f"boards {len(boards)} guesses {total}")
    print(f"  their pick riskier than ours  {worse}")
    print(f"  their pick safer than ours    {better}")
    print(f"  identical risk                {same}")
    print(f"  they died / we survived       {killed}")
    print(f"  we died / they survived       {saved}")


if __name__ == "__main__":
    main()




