"""自动计算的胜率测量。

纯计算部分放这里，命令行入口在 ``tools/winrate.py``，测试直接调
:func:`play_game` / :func:`run`。

一局的定义：随机挑一格作为首格（3x3 安全区），展开；之后完全交给
:class:`~minesweeper.solver.strategy.AutoSolver` 驱动，直到分出胜负。

结束原因（:data:`REASONS`）：

=======  ====================================================
``win``  所有非雷格都展开（真的赢，不是"没得走"）
``boom`` 展开到雷
``dead-end``生成器提前结束（算不出下一步）
``timeout``动作数超过 ``max_actions``（防 bug 死循环）
=======  ====================================================
"""

import multiprocessing
import random
import time
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from ..core.board import Board
from ..core.enums import MINE, Status
from ..core.geometry import Position
from .engine import Engine, resolve_engine
from .strategy import ActionKind, AutoSolver, SolverConfig

#: 结束原因
WIN = "win"
BOOM = "boom"
DEAD_END = "dead-end"
TIMEOUT = "timeout"
REASONS = (WIN, BOOM, DEAD_END, TIMEOUT)

#: 每局最多走多少步（防止 bug 导致的死循环把测量挂住）
MAX_ACTIONS = 5000


class GameOutcome(NamedTuple):
    """一局的结果。"""

    won: bool
    steps: int
    reason: str


def game_seeds(seed: int, index: int) -> Tuple[random.Random, random.Random]:
    """第 *index* 局的一对独立随机数：``(布雷, 猜测)``。

    两者必须分开：求解器的随机选择会把随机数流往前推，如果共用同一个
    ``Random``，同一 ``seed`` 下两次测量的雷图就不一样，数字没法比。
    """
    base = seed * 100000 + index
    return random.Random(base), random.Random(base + 50000)


FIRST_CLICK_MODES = ("random", "center")


def open_first_cell(
    board: Board, rng: random.Random, mode: str = "random"
) -> Position:
    """选首格布雷并展开，返回首格坐标。

    ``mode="random"`` 与真人开局一致（随便点一下），``mode="center"`` 固定点棋盘
    中心——公开的胜率数据大多用中心开局，比较时必须用同一种口径。
    """

    if mode not in FIRST_CLICK_MODES:
        raise ValueError("未知的首点方式：%r" % (mode,))
    if mode == "center":
        first = (board.rows // 2, board.cols // 2)
    else:
        first = (rng.randint(0, board.rows - 1), rng.randint(0, board.cols - 1))
    board.gen_mine(first)
    board.expansion(*first)
    return first


def board_from_layout(
    rows: int, cols: int, mines: int, layout: Sequence[Sequence[int]]
) -> Board:
    """按给定雷图（1=雷、0=安全）造棋盘，用于"同一批棋盘"的新旧/两套求解器对照。"""

    if len(layout) != rows or any(len(row) != cols for row in layout):
        raise ValueError("雷图尺寸与 rows/cols 不符")

    board = Board(rows, cols, mines)
    board.mine_matrix = [
        [MINE if layout[row][col] else 0 for col in range(cols)]
        for row in range(rows)
    ]
    for row in range(rows):
        for col in range(cols):
            if board.mine_matrix[row][col] != MINE:
                board.mine_matrix[row][col] = board._count_adjacent_mines(row, col)
    return board


def play_game(
    engine: Engine,
    rows: int,
    cols: int,
    mines: int,
    board_rng: Optional[random.Random] = None,
    solver_rng: Optional[random.Random] = None,
    config: Optional[SolverConfig] = None,
    max_actions: int = MAX_ACTIONS,
    first_click: str = "random",
    layout: Optional[Sequence[Sequence[int]]] = None,
    first: Optional[Position] = None,
) -> GameOutcome:
    """玩一局，返回 :class:`GameOutcome`（可以直接解包成三个值）。

    :param layout: 给定雷图（``1``=雷）时直接用这张图，不再随机布雷——用来让
        两套求解器跑**完全相同的棋盘**
    :param first: 首点坐标（``layout`` 模式下默认棋盘中心）
    """
    if solver_rng is None:
        solver_rng = board_rng if board_rng is not None else random.Random(0)

    if layout is None:
        if board_rng is None:
            board_rng = random.Random(0)
        board = Board(rows, cols, mines, rng=board_rng)
        open_first_cell(board, board_rng, first_click)
    else:
        board = board_from_layout(rows, cols, mines, layout)
        if first is None:
            first = (rows // 2, cols // 2)
        board.expansion(*first)

    if board.is_won():
        return GameOutcome(True, 1, WIN)

    solver = AutoSolver(board, engine=engine, config=config, rng=solver_rng)
    steps = 0
    for action in solver.actions():
        steps += 1
        if steps > max_actions:
            return GameOutcome(False, steps, TIMEOUT)

        if action.kind is ActionKind.OPEN:
            status, _ = board.expansion(*action.position)
            if status is Status.FAIL:
                return GameOutcome(False, steps, BOOM)
        else:
            board.mark_mine(*action.position)

        # 一次展开可能把最后一片安全区全打开，必须立刻判胜；否则生成器
        # "无事可做"地结束时会被记成 dead-end。
        if board.is_won():
            return GameOutcome(True, steps, WIN)

    return GameOutcome(board.is_won(), steps, WIN if board.is_won() else DEAD_END)


def run(
    rows: int = 16,
    cols: int = 30,
    mines: int = 99,
    games: int = 20,
    seed: int = 2026,
    config: Optional[SolverConfig] = None,
    engine: Optional[Engine] = None,
    engine_name: str = "auto",
    jobs: int = 1,
    progress: bool = False,
    first_click: str = "random",
) -> Dict[str, object]:
    """跑 *games* 局并汇总。

    返回的字典字段：``rows/cols/mines/games/wins/win_rate/steps/
    steps_per_game/reasons/elapsed``（``reasons`` 是各结束原因的计数）。

    :param engine: 已构造的引擎；不给就按 *engine_name* 现建
    :param engine_name: ``auto``（优先原生）/ ``native`` / ``reference``；
        多进程时每个 worker 各自按这个名字建引擎（引擎对象本身不可 pickle）
    :param jobs: 并行进程数（每局互相独立，可以直接按局并行）
    """
    jobs = max(1, int(jobs))
    if engine is None and jobs == 1:
        engine = resolve_engine(engine_name)

    tasks = [
        (rows, cols, mines, seed, index, first_click) for index in range(games)
    ]
    reasons: Dict[str, int] = {}
    start = time.time()

    if jobs > 1 and games > 1:
        pool = multiprocessing.Pool(
            processes=jobs, initializer=_worker_init, initargs=(engine_name, config)
        )
        try:
            chunk = max(1, games // (jobs * 4))
            outcomes = list(pool.imap(_worker_play, tasks, chunk))
        finally:
            pool.close()
            pool.join()
    else:
        outcomes = []
        for task in tasks:
            outcome = _play_task(engine, task, config)
            outcomes.append(outcome)
            if progress:
                _print_progress(len(outcomes), outcome)

    if jobs > 1 and progress:
        for index, outcome in enumerate(outcomes):
            _print_progress(index + 1, outcome)

    wins = sum(1 for outcome in outcomes if outcome.won)
    total_steps = sum(outcome.steps for outcome in outcomes)
    for outcome in outcomes:
        reasons[outcome.reason] = reasons.get(outcome.reason, 0) + 1

    elapsed = time.time() - start
    games = max(games, 0)
    return {
        "rows": rows,
        "cols": cols,
        "mines": mines,
        "games": games,
        "wins": wins,
        "win_rate": wins / float(games) if games else 0.0,
        "steps": total_steps,
        "steps_per_game": total_steps / float(games) if games else 0.0,
        "reasons": reasons,
        "elapsed": elapsed,
        "exact": bool((config or SolverConfig()).exact_marginals),
        "guess": (config or SolverConfig()).guess_policy,
        "jobs": jobs,
        "first": first_click,
    }


def _play_task(
    engine: Engine,
    task: Tuple[int, int, int, int, int, str],
    config: Optional[SolverConfig],
) -> GameOutcome:
    rows, cols, mines, seed, index, first_click = task
    board_rng, solver_rng = game_seeds(seed, index)
    return play_game(
        engine, rows, cols, mines, board_rng, solver_rng, config, first_click=first_click
    )


def _print_progress(number: int, outcome: GameOutcome) -> None:
    print(
        "第 {:2d} 局: {:4s}  {:5d} 步  ({})".format(
            number, "胜利" if outcome.won else "失败", outcome.steps, outcome.reason
        ),
        flush=True,
    )


# ----------------------------------------------------------------------
# 多进程支持
# ----------------------------------------------------------------------
_WORKER: Dict[str, object] = {}


def _worker_init(engine_name: str, config: Optional[SolverConfig]) -> None:
    _WORKER["engine"] = resolve_engine(engine_name)
    _WORKER["config"] = config


def _worker_play(task: Tuple[int, int, int, int, int, str]) -> GameOutcome:
    return _play_task(
        _WORKER["engine"],  # type: ignore[arg-type]
        task,
        _WORKER.get("config"),  # type: ignore[arg-type]
    )


def format_summary(result: Dict[str, object]) -> str:
    """把 :func:`run` 的结果排成多行文本。"""
    games = result["games"] or 1
    return (
        "棋盘: {rows}x{cols} / {mines} 雷\n"
        "模式: {mode}   猜法: {guess}   首点: {first}\n"
        "局数: {games}   胜利: {wins}   胜率: {rate:.1%}\n"
        "平均步数: {steps:.1f}   总耗时: {elapsed:.1f}s   每局: {each:.2f}s\n"
        "结束原因: {reasons}"
    ).format(
        rows=result["rows"],
        cols=result["cols"],
        mines=result["mines"],
        mode="精确边际" if result.get("exact") else "窗口法",
        guess=result.get("guess", "-"),
        first=result.get("first", "random"),
        games=result["games"],
        wins=result["wins"],
        rate=result["win_rate"],
        steps=result["steps_per_game"],
        elapsed=result["elapsed"],
        each=result["elapsed"] / float(games),
        reasons=result["reasons"],
    )
