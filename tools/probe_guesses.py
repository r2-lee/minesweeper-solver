"""统计每局猜测次数与胜率：用于评估端局精确搜索的门槛。

用法：
    python3 tools/probe_guesses.py -n 400 --cells 20 --worlds 512 --nodes 2000
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

from minesweeper.solver import benchmark, strategy


class Counting(strategy.AutoSolver):
    calls = 0

    def _guess(self, *args, **kwargs):
        Counting.calls += 1
        return super()._guess(*args, **kwargs)


def run(games, rows, cols, mines, seed, first, cells, worlds, nodes, endgame):
    benchmark.AutoSolver = Counting
    config = strategy.SolverConfig(
        endgame=endgame,
        endgame_cells=cells,
        endgame_worlds=worlds,
        endgame_nodes=nodes,
    )
    wins = 0
    guesses = 0
    steps = 0
    started = time.time()
    for index in range(games):
        board_rng, solver_rng = benchmark.game_seeds(seed, index)
        Counting.calls = 0
        won, game_steps, _reason = benchmark.play_game(
            None,
            rows,
            cols,
            mines,
            board_rng,
            solver_rng=solver_rng,
            config=config,
            first_click=first,
        )
        wins += 1 if won else 0
        guesses += Counting.calls
        steps += game_steps
    elapsed = time.time() - started
    print(
        "endgame=%s cells=%d worlds=%d nodes=%d  wins %d/%d = %.2f%%  guesses/game %.2f  steps/game %.1f  %.1fs"
        % (
            endgame,
            cells,
            worlds,
            nodes,
            wins,
            games,
            100.0 * wins / games,
            guesses / games,
            steps / games,
            elapsed,
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--games", type=int, default=400)
    parser.add_argument("--rows", type=int, default=16)
    parser.add_argument("--cols", type=int, default=30)
    parser.add_argument("--mines", type=int, default=99)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--first", default="center")
    parser.add_argument("--cells", type=int, default=20)
    parser.add_argument("--worlds", type=int, default=512)
    parser.add_argument("--nodes", type=int, default=2000)
    parser.add_argument("--no-endgame", action="store_true")
    args = parser.parse_args(argv)
    run(
        args.games,
        args.rows,
        args.cols,
        args.mines,
        args.seed,
        args.first,
        args.cells,
        args.worlds,
        args.nodes,
        not args.no_endgame,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
