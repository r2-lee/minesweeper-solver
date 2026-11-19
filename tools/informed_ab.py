"""Paired A/B: min_prob vs informed on identical boards."""
import argparse
import math
import multiprocessing
import sys
import time

sys.path[:0] = [".", "site-packages"]

from minesweeper.solver import benchmark
from minesweeper.solver.strategy import SolverConfig

A = "min_prob"
B = "progress"


def _play(args):
    index, seed, rows, cols, mines, first, band, cands, policy_a, policy_b = args
    seeds = benchmark.game_seeds(seed, index)
    win_a, steps_a, _ = benchmark.play_game(
        None, rows, cols, mines, seeds[0], seeds[1], SolverConfig(guess_policy=policy_a), first_click=first
    )
    seeds = benchmark.game_seeds(seed, index)
    cfg = SolverConfig(guess_policy=policy_b, informed_band=band, informed_candidates=cands)
    win_b, steps_b, _ = benchmark.play_game(
        None, rows, cols, mines, seeds[0], seeds[1], cfg, first_click=first
    )
    return index, int(win_a), int(win_b), steps_a, steps_b


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-n", "--games", type=int, default=2000)
    p.add_argument("-j", "--jobs", type=int, default=12)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--rows", type=int, default=16)
    p.add_argument("--cols", type=int, default=30)
    p.add_argument("--mines", type=int, default=99)
    p.add_argument("--first", default="center", choices=["random", "center"])
    p.add_argument("--band", type=float, default=0.02)
    p.add_argument("--candidates", type=int, default=5)
    p.add_argument("--a", default=A)
    p.add_argument("--b", default=B)
    args = p.parse_args()

    tasks = [
        (i, args.seed, args.rows, args.cols, args.mines, args.first, args.band, args.candidates, args.a, args.b)
        for i in range(args.games)
    ]
    started = time.time()
    with multiprocessing.Pool(args.jobs) as pool:
        rows = []
        for done, row in enumerate(pool.imap_unordered(_play, tasks), 1):
            rows.append(row)
            if done % 200 == 0:
                print("... %d/%d  %.1fs" % (done, args.games, time.time() - started), flush=True)

    both = sum(1 for _, a, b, _, _ in rows if a and b)
    neither = sum(1 for _, a, b, _, _ in rows if not a and not b)
    only_a = sum(1 for _, a, b, _, _ in rows if a and not b)
    only_b = sum(1 for _, a, b, _, _ in rows if b and not a)
    steps_a = sum(r[3] for r in rows) / len(rows)
    steps_b = sum(r[4] for r in rows) / len(rows)
    if only_a + only_b:
        z = (only_b - only_a) / math.sqrt(only_a + only_b)
    else:
        z = 0.0
    n = len(rows)
    print("%s  %d/%d = %.2f%%  steps %.1f" % (args.a, both + only_a, n, 100.0 * (both + only_a) / n, steps_a))
    print("%s  %d/%d = %.2f%%  steps %.1f" % (args.b, both + only_b, n, 100.0 * (both + only_b) / n, steps_b))
    print("both %d / neither %d / only_%s %d / only_%s %d" % (both, neither, args.a, only_a, args.b, only_b))
    print("diff %+d games (%+.2f pt), McNemar z = %.2f, elapsed %.1fs" % (only_b - only_a, 100.0 * (only_b - only_a) / n, z, time.time() - started))


if __name__ == "__main__":
    main()
