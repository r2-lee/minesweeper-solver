"""Headless Hill-solver benchmark: play N expert boards through hill-worker.jar."""
import argparse, json, os, random, subprocess, sys, time
from collections import Counter
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, "site-packages"); sys.path.insert(0, ".")
from minesweeper.core.board import Board
from minesweeper.core.enums import Mark, Status

DEFAULT_HILL = os.environ.get("HILL_WORKER_DIR", os.path.join("hill"))
FIRST_CELLS = {"center": None, "edge": None, "corner": None}
GUESS_METHODS = ("GUESS", "SUPERLOC", "GAMETREE", "ADAPTIVE")


def first_cell(kind: str, rows: int, cols: int) -> Tuple[int, int]:
    if kind == "center":
        return rows // 2, cols // 2
    if kind == "edge":
        return 0, cols // 2
    if kind == "corner":
        return 0, 0
    raise ValueError(kind)


def snapshot(board: Board) -> str:
    return "".join(
        str(board.mine_matrix[r][c]) if board.mark_matrix[r][c] == Mark.OPENED
        else "F" if board.mark_matrix[r][c] == Mark.FLAG else "H"
        for r in range(board.rows) for c in range(board.cols)
    )


class Worker:
    def __init__(self, command: List[str]):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, encoding="ascii", bufsize=1)

    def ask(self, line: str) -> str:
        self.proc.stdin.write(line + "\n"); self.proc.stdin.flush()
        reply = self.proc.stdout.readline()
        if not reply:
            raise RuntimeError("worker exited")
        return reply.rstrip("\r\n")

    def new_game(self, rows: int, cols: int, mines: int) -> None:
        reply = self.ask("NEW\t%d\t%d\t%d" % (rows, cols, mines))
        if reply != "OK":
            raise RuntimeError("NEW failed: " + reply)

    def moves(self, snap: str) -> List[Tuple[str, int, str, str]]:
        reply = self.ask("BOARD\t" + snap)
        if reply.startswith("ERR"):
            raise RuntimeError("BOARD failed: " + reply)
        parts = reply.split("\t")
        out = []
        for field in parts[1:]:
            code, index, safety, method = field.split(":", 3)
            out.append((code, int(index), safety, method))
        return out

    def close(self) -> None:
        try:
            self.proc.terminate(); self.proc.wait(timeout=5)
        except Exception:
            pass


def play(worker: Worker, rows: int, cols: int, mines: int, rng: random.Random, first: str, first_cell_xy=None) -> Tuple[bool, int, int, Counter]:
    board = Board(rows, cols, mines, rng=rng)
    start = tuple(first_cell_xy) if first_cell_xy is not None else first_cell(first, rows, cols)
    board.gen_mine(start)
    status, _ = board.expansion(*start)
    guesses = 0
    steps = 0
    methods = Counter()
    if status == Status.WIN:
        return True, 0, 1, methods
    if status == Status.FAIL:
        return False, 0, 1, methods
    worker.new_game(rows, cols, mines)
    while True:
        if board.is_won():
            return True, guesses, steps, methods
        moves = worker.moves(snapshot(board))
        progressed = False
        for code, index, _safety, method in moves:
            row, col = divmod(index, cols)
            mark = board.mark_matrix[row][col]
            if code in ("C", "A"):
                if mark in (Mark.OPENED, Mark.FLAG):
                    continue
                try:
                    certain = _safety == "1"
                except Exception:
                    certain = False
                if not certain:
                    guesses += 1
                methods[method] += 1
                status, _ = board.expansion(row, col)
                steps += 1
                progressed = True
                if status == Status.FAIL:
                    return False, guesses, steps, methods
                if status == Status.WIN or board.is_won():
                    return True, guesses, steps, methods
            elif code == "F":
                if mark in (Mark.OPENED, Mark.FLAG):
                    continue
                board.mark_mine(row, col)
                progressed = True
                if board.is_won():
                    return True, guesses, steps, methods
            elif code == "U":
                if mark != Mark.FLAG:
                    continue
                board.mark_matrix[row][col] = Mark.COVERED
                progressed = True
        if not progressed:
            return False, guesses, steps, methods


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--games", type=int, default=200)
    ap.add_argument("--rows", type=int, default=16)
    ap.add_argument("--cols", type=int, default=30)
    ap.add_argument("--mines", type=int, default=99)
    ap.add_argument("--first", default="center")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--java", default=os.environ.get("HILL_JAVA", ""))
    ap.add_argument("--hill", default=DEFAULT_HILL,
                    help="目录里要有 hill-worker.jar 和 runtime/（参考实现不随仓库分发），也可用环境变量 HILL_WORKER_DIR")
    args = ap.parse_args()
    java = args.java or os.path.join(args.hill, "runtime", "bin",
                                      "java.exe" if os.name == "nt" else "java")
    jar = os.path.join(args.hill, "hill-worker.jar")
    cmd = [java, "-Xms32m", "-Xmx1024m", "-XX:ActiveProcessorCount=2", "-jar", jar]
    worker = Worker(cmd)
    wins = 0; total_guesses = 0; total_steps = 0; methods = Counter(); started = time.time()
    try:
        for i in range(args.games):
            rng = random.Random(args.seed * 100000 + i)
            won, guesses, steps, m = play(worker, args.rows, args.cols, args.mines, rng, args.first)
            wins += 1 if won else 0
            total_guesses += guesses; total_steps += steps; methods.update(m)
    finally:
        worker.close()
    elapsed = time.time() - started
    print(json.dumps({
        "first": args.first, "games": args.games, "wins": wins,
        "win_rate": round(wins / args.games, 5),
        "guesses_per_game": round(total_guesses / args.games, 3),
        "steps_per_game": round(total_steps / args.games, 2),
        "elapsed_s": round(elapsed, 2), "ms_per_game": round(1000 * elapsed / args.games, 1),
        "methods": dict(methods.most_common(12)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
