"""Expand a quadrant sweep CSV to the full symmetric board by reflection."""
import argparse, csv, sys

ap = argparse.ArgumentParser()
ap.add_argument("--in", dest="src", default="docs/benchmarks/hill-opening-heatmap-quadrant.csv")
ap.add_argument("--out", dest="dst", default="docs/benchmarks/hill-opening-heatmap.csv")
ap.add_argument("--rows", type=int, default=16)
ap.add_argument("--cols", type=int, default=30)
args = ap.parse_args()

q = {}
with open(args.src, encoding="utf-8") as fh:
    for rec in csv.DictReader(fh):
        q[(int(rec["row"]), int(rec["col"]))] = rec
missing = [(r, c) for r in range(args.rows) for c in range(args.cols)
           if (min(r, args.rows - 1 - r), min(c, args.cols - 1 - c)) not in q]
if missing:
    print("missing quadrant data for", len(missing), "cells"); sys.exit(1)
with open(args.dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["row", "col", "wins", "games", "win_rate", "guesses_per_game", "steps_per_game"])
    for r in range(args.rows):
        for c in range(args.cols):
            rec = q[(min(r, args.rows - 1 - r), min(c, args.cols - 1 - c))]
            w.writerow([r, c, rec["wins"], rec["games"], rec["win_rate"],
                        rec["guesses_per_game"], rec["steps_per_game"]])
print("mirrored", len(q), "quadrant cells ->", args.rows * args.cols, "board cells")
