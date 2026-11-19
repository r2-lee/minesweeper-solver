"""用我们自己的精确边际做裁判，统计 EdLogg 求解器"真正无法确定的决策"次数。

为什么要这么做：两边各自的 `guesses` 计数器口径不同。他的计数器会把"按完整约束
其实可以证明"的格子也算成猜测；我们的计数器不会。所以拿同一个裁判（我们的精确表）
去审他的每一步猜测，才能得到可比的数字。

用法：
    python tools/referee_guesses.py <ed.exe> <count> <seed> [--rows 16 --cols 30 --mines 99]

输出每局一行，最后是汇总（每局平均猜测次数、其中真正无法确定的比例）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.core.board import Board  # noqa: E402
from minesweeper.core.enums import Mark, MINE  # noqa: E402
from minesweeper.solver.frontier import FrontierSolver  # noqa: E402


def _parse_layout(text: str, rows: int, cols: int) -> List[Tuple[int, int]]:
    lines = [line for line in text.split("/") if line]
    if len(lines) != rows:
        raise ValueError("layout has %d rows, expected %d" % (len(lines), rows))
    mines = []
    for row, line in enumerate(lines):
        if len(line) != cols:
            raise ValueError("layout row %d has %d cells, expected %d" % (row, len(line), cols))
        for col, char in enumerate(line):
            if char == "1":
                mines.append((row, col))
    return mines


def _board(rows: int, cols: int, mines: int, layout: List[Tuple[int, int]]) -> Board:
    board = Board(rows, cols, mines)
    marks = set(layout)
    board.mine_matrix = [
        [MINE if (row, col) in marks else 0 for col in range(cols)] for row in range(rows)
    ]
    for row in range(rows):
        for col in range(cols):
            if board.mine_matrix[row][col] != MINE:
                board._count_adjacent_mines(row, col)
    return board


def _apply(board: Board, kind: int, row: int, col: int, value: int) -> None:
    if value == 9:
        board.mark_matrix[row][col] = Mark.FLAG
    elif value >= 0:
        board.mark_matrix[row][col] = Mark.OPENED


def replay(ed: str, seed: str, rows: int, cols: int, mines: int) -> dict:
    output = subprocess.run(
        [ed, "trace", seed], capture_output=True, text=True, check=True
    ).stdout

    pending: List[Tuple[int, int, int, int]] = []
    steps: List[Tuple[int, int, int, List[Tuple[int, int, int, int]]]] = []
    layout: Optional[List[Tuple[int, int]]] = None
    won = False
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "d":
            pending.append((int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
        elif parts[0] == "s":
            steps.append((int(parts[1]), int(parts[2]), int(parts[3]), pending))
            pending = []
        elif parts[0] == "end":
            won = parts[1] == "1"
            layout = _parse_layout(parts[4], rows, cols)
    if layout is None:
        raise ValueError("trace did not contain an end line")

    board = _board(rows, cols, mines, layout)
    solver = FrontierSolver(board)
    previous = 0
    guesses = 0
    genuine = 0
    certain_mine = 0
    certain_safe = 0
    risks: List[float] = []

    for number, rule, total, diffs in steps:
        is_guess = total > previous
        previous = total
        if is_guess:
            guesses += 1
            targets = [(col, row) for col, row, before, after in diffs if 0 <= after <= 8]
            target = targets[0] if targets else None
            if target is not None:
                table = solver.probabilities()
                probability = table.get((target[1], target[0]))
                if probability is None:
                    genuine += 1  # 裁判也判断不了：真正的猜测
                    risks.append(-1.0)
                elif probability <= 1e-9:
                    certain_mine += 1
                elif probability >= 1 - 1e-9:
                    certain_safe += 1
                else:
                    genuine += 1
                    risks.append(probability)
        for col, row, before, after in diffs:
            _apply(board, 0, row, col, after)

    return {
        "seed": seed,
        "won": won,
        "guesses": guesses,
        "genuine": genuine,
        "certain_mine": certain_mine,
        "certain_safe": certain_safe,
        "risks": risks,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ed", help="path to ed.exe")
    parser.add_argument("count", type=int, help="number of games")
    parser.add_argument("seed", help="starting seed of the chain")
    parser.add_argument("--rows", type=int, default=16)
    parser.add_argument("--cols", type=int, default=30)
    parser.add_argument("--mines", type=int, default=99)
    args = parser.parse_args(argv)

    chain = subprocess.run(
        [args.ed, "chain", str(args.count), args.seed], capture_output=True, text=True, check=True
    ).stdout.split()

    total_games = total_guesses = total_genuine = total_mine = total_safe = 0
    wins = 0
    risk_values: List[float] = []
    for index, seed in enumerate(chain):
        result = replay(args.ed, seed, args.rows, args.cols, args.mines)
        wins += 1 if result["won"] else 0
        total_games += 1
        total_guesses += result["guesses"]
        total_genuine += result["genuine"]
        total_mine += result["certain_mine"]
        total_safe += result["certain_safe"]
        risk_values.extend(value for value in result["risks"] if value >= 0)
        print(
            "%3d seed=%s win=%d guesses=%d genuine=%d certainMine=%d certainSafe=%d"
            % (
                index,
                result["seed"],
                result["won"],
                result["guesses"],
                result["genuine"],
                result["certain_mine"],
                result["certain_safe"],
            )
        )

    print("---")
    print("games %d  wins %d (%.2f%%)" % (total_games, wins, 100.0 * wins / total_games))
    print(
        "his guesses/game %.2f   genuine/game %.2f   certainMine/game %.2f   certainSafe/game %.2f"
        % (
            total_guesses / total_games,
            total_genuine / total_games,
            total_mine / total_games,
            total_safe / total_games,
        )
    )
    if risk_values:
        risk_values.sort()
        middle = risk_values[len(risk_values) // 2]
        print(
            "genuine risk: mean %.3f median %.3f n %d"
            % (sum(risk_values) / len(risk_values), middle, len(risk_values))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
