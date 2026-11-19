"""Final bake-off: which guess policy has the highest win rate on our boards."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "site-packages"))

from minesweeper.solver import benchmark
from minesweeper.solver.strategy import SolverConfig

CONFIGS = [
    ("default", {}),
    ("min_prob", {"guess_policy": "min_prob"}),
    ("progress", {"guess_policy": "progress"}),
    ("informed", {"guess_policy": "informed"}),
    ("adaptive", {"guess_policy": "adaptive"}),
    ("deep", {"guess_policy": "deep"}),
    ("gametree", {"guess_policy": "gametree"}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--games", type=int, default=10000)
    ap.add_argument("-j", "--jobs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--rows", type=int, default=16)
    ap.add_argument("--cols", type=int, default=30)
    ap.add_argument("--mines", type=int, default=99)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    wanted = {name.strip() for name in args.only.split(",") if name.strip()}
    rows = []
    for name, kwargs in CONFIGS:
        if wanted and name not in wanted:
            continue
        result = benchmark.run(
            rows=args.rows,
            cols=args.cols,
            mines=args.mines,
            games=args.games,
            seed=args.seed,
            jobs=args.jobs,
            first_click="center",
            config=SolverConfig(**kwargs),
        )
        row = {
            "name": name,
            "wins": result["wins"],
            "games": result["games"],
            "rate": round(result["win_rate"], 4),
            "steps": round(result["steps_per_game"], 1),
            "elapsed": round(result["elapsed"], 1),
        }
        rows.append(row)
        print(
            "%-10s %6d/%-6d = %6.2f%%  steps %6.1f  %6.1fs"
            % (name, row["wins"], row["games"], 100.0 * row["rate"], row["steps"], row["elapsed"]),
            flush=True,
        )
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(rows, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
