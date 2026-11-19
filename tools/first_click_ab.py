"""首点规则对胜率的影响：同一批盘、同一求解器，只换"第一下"时雷场怎么生成。

三种开局规则：

``zero3x3``
    当前游戏用的规则：首点周围 3x3 一个雷都不放 —— 首点必然翻出一片空区。
``safe_only``
    只保证首点这格不是雷，周围照常可能全是雷 —— 首点可能只是一个数字，
    不会连锁展开。
``random``
    完全不保护：首点本身也可能是雷（踩中即输，"第一下就死"）。

用法::

    python tools/first_click_ab.py -n 20000 -j 16            # 三种规则各 2 万局
    python tools/first_click_ab.py -n 500 --modes zero3x3 -v # 冒烟
"""

from __future__ import annotations

import argparse
import multiprocessing
import random
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, ".")

from minesweeper.core.board import Board
from minesweeper.core.enums import MINE, Mark, Status
from minesweeper.solver.benchmark import (
    MAX_ACTIONS,
    board_from_layout,
    game_seeds,
)
from minesweeper.solver.engine import resolve_engine
from minesweeper.solver.strategy import Action, ActionKind, AutoSolver, SolverConfig, _Step

MODES = ("zero3x3", "zero3x3_plus1", "zero3x3_nozero", "zero5x5", "safe_only", "random")
FIRST_POSITIONS = ("center", "corner", "edge")


# --------------------------------------------------------------------------- 棋盘


def layout_for(
    rng: random.Random, rows: int, cols: int, mines: int, first: Tuple[int, int], mode: str
) -> List[List[int]]:
    """按 ``mode`` 生成一张 ``rows x cols`` 的雷图（1 = 雷）。"""
    row, col = first
    blocked = set()
    if mode == "zero5x5":
        for dr in (-2, -1, 0, 1, 2):
            for dc in (-2, -1, 0, 1, 2):
                r, c = row + dr, col + dc
                if 0 <= r < rows and 0 <= c < cols:
                    blocked.add((r, c))
    elif mode in ("zero3x3", "zero3x3_plus1", "zero3x3_nozero"):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                r, c = row + dr, col + dc
                if 0 <= r < rows and 0 <= c < cols:
                    blocked.add((r, c))
    elif mode == "safe_only":
        blocked.add((row, col))
    elif mode != "random":
        raise ValueError("unknown mode: %r" % (mode,))

    cells = [(r, c) for r in range(rows) for c in range(cols) if (r, c) not in blocked]
    attempts = 1 if mode == "zero3x3" else 400
    for _ in range(attempts):
        chosen = rng.sample(cells, mines)
        layout = [[0] * cols for _ in range(rows)]
        for r, c in chosen:
            layout[r][c] = 1
        if mode == "zero3x3":
            return layout
        has_zero = any(
            _is_zero_cell(layout, rows, cols, (row + dr, col + dc))
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if (dr, dc) != (0, 0) and 0 <= row + dr < rows and 0 <= col + dc < cols
        )
        if (mode == "zero3x3_plus1") == has_zero:
            return layout
    return layout  # 极端情况下退回最后一次采样


def _is_zero_cell(layout: List[List[int]], rows: int, cols: int, cell: Tuple[int, int]) -> bool:
    """这一格的八邻域里没有雷（即打开它会亮出 "0"）。"""
    r0, c0 = cell
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr, dc) == (0, 0):
                continue
            r, c = r0 + dr, c0 + dc
            if 0 <= r < rows and 0 <= c < cols and layout[r][c]:
                return False
    return True


# --------------------------------------------------------------------------- 单局


class CountingSolver(AutoSolver):
    """数一局里到底"猜"了几次（``_guess`` 被调用一次 = 一次猜测）。"""

    def __init__(self, *args, **kwargs) -> None:
        self.cheats = kwargs.pop("cheats", 0)
        super().__init__(*args, **kwargs)
        self.guesses = 0
        self.cheats_used = 0

    def _guess(self, values, tables, state, exact: bool = False):  # type: ignore[override]
        self.guesses += 1
        step = super()._guess(values, tables, state, exact=exact)
        if self.cheats <= 0 or step.action is None or step.action.kind != ActionKind.OPEN:
            return step
        row, col = step.action.position
        if self.board.mine_matrix[row][col] != MINE:
            return step  # 这一猜本来就安全，不算用掉作弊
        # 作弊：换成一个"保证安全、而且最容易连锁"的格子
        best = None
        best_score = -1
        for r in range(self.board.rows):
            for c in range(self.board.cols):
                if self.board.mark_matrix[r][c] != Mark.COVERED:
                    continue
                if self.board.mine_matrix[r][c] == MINE:
                    continue
                score = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < self.board.rows and 0 <= cc < self.board.cols:
                            if self.board.mine_matrix[rr][cc] == 0:
                                score += 1
                if score > best_score:
                    best_score = score
                    best = (r, c)
        if best is None:
            return step
        self.cheats -= 1
        self.cheats_used += 1
        return _Step(step.state, Action(ActionKind.OPEN, best))


def first_position(name: str, rows: int, cols: int) -> Tuple[int, int]:
    """``center`` 版心、``corner`` 左上角 (0,0)、``edge`` 上边中点。"""
    if name == "center":
        return rows // 2, cols // 2
    if name == "corner":
        return 0, 0
    if name == "edge":
        return 0, cols // 2
    raise ValueError("unknown first position: %r" % (name,))


def play(
    engine,
    rows: int,
    cols: int,
    mines: int,
    board_rng: random.Random,
    solver_rng: random.Random,
    mode: str,
    config: Optional[SolverConfig] = None,
    first_name: str = "center",
    cheats: int = 0,
) -> Tuple[int, int, int, int]:
    """返回 ``(win, guesses, steps, first_was_blank)``。"""
    first = first_position(first_name, rows, cols)
    layout = layout_for(board_rng, rows, cols, mines, first, mode)
    board = board_from_layout(rows, cols, mines, layout)

    if board.mine_matrix[first[0]][first[1]] == MINE:
        return 0, 0, 0, 0  # 第一下就踩雷

    status, opened = board.expansion(*first)
    blank = 1 if len(opened) > 1 else 0
    if status == Status.FAIL:
        return 0, 0, 1, blank

    solver = CountingSolver(
        board,
        engine=engine,
        config=config if config is not None else SolverConfig(),
        rng=solver_rng,
        cheats=cheats,
    )
    steps = 0
    try:
        for action in solver.actions():
            steps += 1
            if action.kind == ActionKind.OPEN:
                status, _ = board.expansion(*action.position)
                if status == Status.FAIL:
                    return 0, solver.guesses, steps, blank
            else:
                status = board.mark_mine(*action.position)
            if status == Status.FAIL:
                return 0, solver.guesses, steps, blank
            if board.is_won():
                return 1, solver.guesses, steps, blank
            if steps >= MAX_ACTIONS:
                break
    except StopIteration:  # pragma: no cover - actions() 自己会结束
        pass
    return (1 if board.is_won() else 0), solver.guesses, steps, blank


# --------------------------------------------------------------------------- 并行


_TASK: Dict[str, object] = {}


def _init(rows: int, cols: int, mines: int, mode: str, engine_name: str, config, first, cheats) -> None:
    _TASK["engine"] = resolve_engine(engine_name)
    _TASK["shape"] = (rows, cols, mines)
    _TASK["mode"] = mode
    _TASK["config"] = config
    _TASK["first"] = first
    _TASK["cheats"] = cheats


def _one(index: int) -> Tuple[int, int, int, int]:
    row = _run_one(index)
    return row


def _run_one(index: int) -> Tuple[int, int, int, int]:
    rows, cols, mines = _TASK["shape"]  # type: ignore[misc]
    board_rng, solver_rng = game_seeds(2026, index)
    return play(
        _TASK["engine"],  # type: ignore[arg-type]
        rows,
        cols,
        mines,
        board_rng,
        solver_rng,
        _TASK["mode"],  # type: ignore[arg-type]
        _TASK["config"],  # type: ignore[arg-type]
        _TASK["first"],  # type: ignore[arg-type]
        _TASK["cheats"],  # type: ignore[arg-type]
    )


def run(
    mode: str,
    games: int,
    jobs: int,
    seed: int,
    engine_name: str,
    config=None,
    first: str = "center",
    cheats: int = 0,
) -> Dict[str, object]:
    rows, cols, mines = 16, 30, 99
    started = time.time()
    if jobs <= 1:
        engine = resolve_engine(engine_name)
        rows_out = [
            play(engine, rows, cols, mines, *game_seeds(seed, i)[:2], mode, config, first, cheats)  # type: ignore[arg-type]
            for i in range(games)
        ]
    else:
        global _TASK
        _TASK = {
            "engine": None,
            "shape": (rows, cols, mines),
            "mode": mode,
            "config": config,
            "first": first,
            "cheats": cheats,
        }
        with multiprocessing.Pool(
            jobs, initializer=_init, initargs=(rows, cols, mines, mode, engine_name, config, first, cheats)
        ) as pool:
            rows_out = pool.map(_one, range(games), chunksize=16)

    wins = sum(r[0] for r in rows_out)
    guesses = [r[1] for r in rows_out]
    blanks = sum(r[3] for r in rows_out)
    blank_games = blanks
    blank_wins = sum(r[0] for r in rows_out if r[3])
    nonblank_games = len(rows_out) - blank_games
    nonblank_wins = wins - blank_wins
    hist: Dict[int, int] = {}
    for g in guesses:
        hist[g] = hist.get(g, 0) + 1
    return {
        "mode": mode,
        "first": first,
        "cheats": cheats,
        "games": games,
        "wins": wins,
        "rate": wins / games if games else 0.0,
        "guesses": sum(guesses) / games if games else 0.0,
        "guess_hist": dict(sorted(hist.items())),
        "blank_rate": blanks / games if games else 0.0,
        "blank_games": blank_games,
        "blank_rate_win": (blank_wins / blank_games) if blank_games else 0.0,
        "nonblank_games": nonblank_games,
        "nonblank_rate_win": (nonblank_wins / nonblank_games) if nonblank_games else 0.0,
        "steps": sum(r[2] for r in rows_out) / games if games else 0.0,
        "elapsed": time.time() - started,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="首点规则对胜率的影响")
    parser.add_argument("-n", "--games", type=int, default=2000)
    parser.add_argument("-j", "--jobs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--engine", default="auto")
    parser.add_argument("--first", default="center", choices=list(FIRST_POSITIONS))
    parser.add_argument("--cheats", type=int, default=0, help="每局给几次作弊（把必死的一猜换成安全格）")
    args = parser.parse_args(argv)

    for mode in args.modes:
        res = run(
            mode,
            args.games,
            args.jobs,
            args.seed,
            args.engine,
            first=args.first,
            cheats=args.cheats,
        )
        hist = res["guess_hist"]  # type: ignore[assignment]
        top = "  ".join(
            "%d次:%d" % (k, v)
            for k, v in sorted(hist.items(), key=lambda kv: -kv[1])[:6]  # type: ignore[union-attr]
        )
        print(
            "%-9s 首点=%-6s 作弊=%d n=%-6d 胜率=%6.2f%%  猜测/局=%.2f  首点开空=%.1f%%  步数=%.1f  %.1fs"
            % (
                res["mode"],
                res["first"],
                res["cheats"],
                res["games"],
                res["rate"] * 100,
                res["guesses"],
                res["blank_rate"] * 100,
                res["steps"],
                res["elapsed"],
            )
        )
        print("          猜测次数分布: %s" % top)
        print(
            "          首点开空 %d 局胜率 %5.2f%% ；首点只翻出数字 %d 局胜率 %5.2f%%"
            % (
                res["blank_games"],
                res["blank_rate_win"] * 100,
                res["nonblank_games"],
                res["nonblank_rate_win"] * 100,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
