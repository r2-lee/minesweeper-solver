"""重测所有猜法/配置：每个配置跑在**独立子进程**里。

崩溃隔离：某个配置的进程段错误时，父进程只记一行 CRASHED，其余配置继续跑，
结果文件不会缺行、也不会丢已经跑完的配置。

用法（Linux）：
    bash ~/rerun_ab.sh                      # 见 tools/rerun_ab.sh
    python3 tools/full_ab.py --games 20000 --jobs 16
"""

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "site-packages"))

CASES = {
    "min_prob": {},
    "endgame_off": {"endgame": False},
    "superloc": {"guess_policy": "superloc"},
    "coin": {"guess_policy": "coin"},
    "gamble": {"guess_policy": "gamble"},
    "deep": {"guess_policy": "deep"},
    "blank": {"guess_policy": "blank"},
    "search_d2": {"guess_policy": "search", "guess_depth": 2, "guess_worlds": 800},
    "lookahead": {"guess_policy": "lookahead"},
    "living": {"guess_policy": "living"},
    "rollout_3": {"guess_policy": "rollout", "rollout_samples": 3},
    "pinned": {"guess_policy": "pinned"},
    "plan": {"guess_policy": "plan"},
    "fewest": {"guess_policy": "fewest"},
    "progress": {"guess_policy": "progress"},
    "gametree": {"guess_policy": "gametree"},
    "search_d3": {"guess_policy": "search", "guess_depth": 3, "guess_worlds": 2000},
    "endgame_wide": {"endgame_cells": 40, "endgame_worlds": 4096, "endgame_nodes": 20000},
}

HEADER = ["name", "games", "wins", "win_rate", "steps_per_game", "elapsed_s",
          "reasons", "config"]


def write_row(path, row):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\t".join(row) + "\n")


def run_one(name, args):
    from minesweeper.solver import benchmark
    from minesweeper.solver.strategy import SolverConfig

    config = SolverConfig(**CASES[name])
    started = time.time()
    result = benchmark.run(
        rows=args.rows, cols=args.cols, mines=args.mines,
        games=args.games, seed=args.seed, config=config,
        jobs=args.jobs, progress=False,
    )
    elapsed = time.time() - started
    write_row(args.out, [
        name, str(result["games"]), str(result["wins"]), "%.4f" % result["win_rate"],
        "%.2f" % result["steps_per_game"], "%.1f" % elapsed,
        json.dumps(result["reasons"], sort_keys=True), json.dumps(CASES[name], sort_keys=True),
    ])
    print("[done] %-12s %d/%d = %.4f  %.1fs" % (
        name, result["wins"], result["games"], result["win_rate"], elapsed), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--rows", type=int, default=16)
    ap.add_argument("--cols", type=int, default=30)
    ap.add_argument("--mines", type=int, default=99)
    ap.add_argument("--out", default=os.path.expanduser("~/ab_results.tsv"))
    ap.add_argument("--only", default="")
    ap.add_argument("--single", default="", help="内部用：只跑这一个配置")
    args = ap.parse_args()

    if args.single:
        run_one(args.single, args)
        return 0

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(CASES)
    done = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as handle:
            for line in handle:
                done.add(line.split("\t")[0])
    else:
        write_row(args.out, HEADER)

    for name in names:
        if name in done:
            print("[skip] %s" % name, flush=True)
            continue
        print("[run ] %-12s %s" % (name, CASES[name]), flush=True)
        started = time.time()
        code = subprocess.call([
            sys.executable, os.path.abspath(__file__),
            "--single", name, "--games", str(args.games), "--jobs", str(args.jobs),
            "--seed", str(args.seed), "--rows", str(args.rows), "--cols", str(args.cols),
            "--mines", str(args.mines), "--out", args.out,
        ])
        if code != 0:
            print("[crash] %s exit=%d after %.0fs" % (name, code, time.time() - started), flush=True)
            write_row(args.out, [name, "0", "0", "CRASHED", "-", "%.1f" % (time.time() - started),
                                 "{}", json.dumps(CASES[name], sort_keys=True)])
    print("all done -> %s" % args.out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
