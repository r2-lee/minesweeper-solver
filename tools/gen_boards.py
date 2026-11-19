#!/usr/bin/env python3
"""Emit EdLogg batch-driver board blocks: start index, count, seed, first click."""
import argparse
import random
import sys

sys.path.insert(0, ".")

from minesweeper.core.board import Board


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--seed", type=int, default=9001)
    ap.add_argument("--rows", type=int, default=16)
    ap.add_argument("--cols", type=int, default=30)
    ap.add_argument("--mines", type=int, default=99)
    ap.add_argument("--fx", type=int, default=3)
    ap.add_argument("--fy", type=int, default=3)
    args = ap.parse_args()

    out = sys.stdout
    header = "%d %d %d %d %d" % (args.rows, args.cols, args.mines, args.fx, args.fy)
    for i in range(args.start, args.start + args.count):
        rng = random.Random(args.seed * 100000 + i)
        board = Board(args.rows, args.cols, args.mines, rng=rng)
        board.gen_mine((args.fx, args.fy))
        rows = []
        for r in range(args.rows):
            rows.append("".join("1" if v == -1 else "0" for v in board.mine_matrix[r]))
        out.write(header + "\n")
        out.write("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
