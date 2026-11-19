"""Sweep every first-click position on the expert board through the Hill worker."""
import argparse, csv, json, os, random, sys, time
from collections import Counter
from multiprocessing import Pool
from typing import List, Tuple

sys.path.insert(0, "site-packages"); sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hill_ab

_WORKER = None
_SHAPE = None


def _init(rows: int, cols: int, mines: int, java: str, jar: str) -> None:
    global _WORKER, _SHAPE
    _WORKER = hill_ab.Worker([java, "-Xms32m", "-Xmx1024m", "-XX:ActiveProcessorCount=2", "-jar", jar])
    _SHAPE = (rows, cols, mines)


def _one(task: Tuple[int, int, int, int, int]) -> Tuple[int, int, int, int, int, float]:
    row, col, games, seed, start = task
    rows, cols, mines = _SHAPE
    wins = 0; guesses = 0; steps = 0
    for i in range(start, start + games):
        rng = random.Random(seed * 1000003 + i * 7919 + row * 31 + col)
        won, g, s, _m = hill_ab.play(_WORKER, rows, cols, mines, rng, "center", first_cell_xy=(row, col))
        wins += 1 if won else 0
        guesses += g; steps += s
    return row, col, wins, games, guesses, steps / max(1, games)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--games", type=int, default=300)
    ap.add_argument("--rows", type=int, default=16)
    ap.add_argument("--cols", type=int, default=30)
    ap.add_argument("--mines", type=int, default=99)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--jobs", type=int, default=14)
    ap.add_argument("--java", default=os.environ.get("HILL_JAVA", ""))
    ap.add_argument("--hill", default=hill_ab.DEFAULT_HILL)
    ap.add_argument("--out", default="docs/benchmarks/hill-opening-heatmap.csv")
    ap.add_argument("--positions", default="")
    ap.add_argument("--chunk", type=int, default=250)
    args = ap.parse_args()

    if args.positions:
        cells = [tuple(int(v) for v in part.split(",")) for part in args.positions.split(";") if part]
    else:
        cells = [(r, c) for r in range(args.rows) for c in range(args.cols)]
    java = args.java or os.path.join(args.hill, "runtime", "bin",
                                     "java.exe" if os.name == "nt" else "java")
    jar = os.path.join(args.hill, "hill-worker.jar")
    chunk = max(1, args.chunk)
    tasks = []
    for r, c in cells:
        for start in range(0, args.games, chunk):
            tasks.append((r, c, min(chunk, args.games - start), args.seed, start))
    random.Random(args.seed).shuffle(tasks)

    started = time.time()
    acc = {}

    def dump() -> None:
        if not acc:
            return
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["row", "col", "wins", "games", "win_rate", "guesses_per_game",
                             "steps_per_game"])
            for (row, col), (wins, games, guesses, steps) in sorted(acc.items()):
                writer.writerow([row, col, wins, games, round(wins / games, 5),
                                 round(guesses / games, 3), round(steps / games, 2)])

    with Pool(args.jobs, initializer=_init, initargs=(args.rows, args.cols, args.mines, java, jar)) as pool:
        for i, (row, col, wins, games, guesses, steps) in enumerate(pool.imap_unordered(_one, tasks), 1):
            agg = acc.setdefault((row, col), [0, 0, 0, 0.0])
            agg[0] += wins; agg[1] += games; agg[2] += guesses; agg[3] += steps * games
            if i % 10 == 0:
                print("%d/%d  %.0fs" % (i, len(tasks), time.time() - started), flush=True)
                dump()
    dump()
    total_wins = sum(v[0] for v in acc.values()); total_games = sum(v[1] for v in acc.values())
    print(json.dumps({"cells": len(acc), "games": total_games, "wins": total_wins,
                      "win_rate": round(total_wins / max(1, total_games), 5),
                      "elapsed_s": round(time.time() - started, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
