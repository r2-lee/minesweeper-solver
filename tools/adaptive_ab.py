"""配对的 10 万盘 A/B：``min_prob`` vs ``adaptive``（Hill 式按需加深）。

同一张盘分别用两种猜法各跑一遍，统计配对胜负，用 McNemar 检验算显著性。
"""

import argparse
import multiprocessing as multiprocessing
import sys
import time

sys.path.insert(0, ".")

from minesweeper.solver.benchmark import game_seeds, play_game
from minesweeper.solver.strategy import SolverConfig


def _play(task):
    index, rows, cols, mines, seed = task
    board_rng, solver_rng = game_seeds(seed, index)
    base = play_game(
        None, rows, cols, mines, board_rng, solver_rng,
        config=SolverConfig(guess_policy="min_prob"),
    )[0]
    board_rng, solver_rng = game_seeds(seed, index)
    adaptive = play_game(
        None, rows, cols, mines, board_rng, solver_rng,
        config=SolverConfig(guess_policy="adaptive"),
    )[0]
    return bool(base), bool(adaptive)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--games", type=int, default=100000)
    parser.add_argument("--rows", type=int, default=16)
    parser.add_argument("--cols", type=int, default=30)
    parser.add_argument("--mines", type=int, default=99)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("-j", "--jobs", type=int, default=32)
    args = parser.parse_args(argv)

    tasks = [
        (index, args.rows, args.cols, args.mines, args.seed) for index in range(args.games)
    ]
    started = time.perf_counter()
    both = base_only = adaptive_only = neither = 0
    with multiprocessing.Pool(args.jobs) as pool:
        for done, (base, adaptive) in enumerate(
            pool.imap_unordered(_play, tasks, chunksize=8), start=1
        ):
            if base and adaptive:
                both += 1
            elif base:
                base_only += 1
            elif adaptive:
                adaptive_only += 1
            else:
                neither += 1
            if done % 10000 == 0:
                elapsed = time.perf_counter() - started
                print("%6d / %d  (%.0fs)" % (done, args.games, elapsed), flush=True)

    total = both + base_only + adaptive_only + neither
    base_wins = both + base_only
    adaptive_wins = both + adaptive_only
    # McNemar：只看不一致的那些盘
    disagree = base_only + adaptive_only
    if disagree:
        z = (adaptive_only - base_only) / (disagree ** 0.5)
    else:
        z = 0.0
    print("")
    print("games            %d" % total)
    print("min_prob         %d  (%.2f%%)" % (base_wins, 100.0 * base_wins / total))
    print("adaptive         %d  (%.2f%%)" % (adaptive_wins, 100.0 * adaptive_wins / total))
    print("both won         %d" % both)
    print("both lost        %d" % neither)
    print("only min_prob    %d" % base_only)
    print("only adaptive    %d" % adaptive_only)
    print("difference       %+d games (%+.2f pp)" % (
        adaptive_wins - base_wins, 100.0 * (adaptive_wins - base_wins) / total))
    print("mcnemar z        %+.2f  (|z|>1.96 ≈ p<0.05)" % z)
    print("elapsed          %.1fs" % (time.perf_counter() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
