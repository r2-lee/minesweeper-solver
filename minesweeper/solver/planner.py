"""信念空间上的 UCT 规划：把"猜哪一格"当成一个带信息反馈的序列决策问题。

与 :mod:`minesweeper.solver.rollout` 的区别
------------------------------------------
``rollout`` 是固定形状的枚举：挑 k 个候选、每个候选抽 n 张雷图、算平均存活率。
这里是**树搜索**：节点是"信念状态 + 已知棋盘"，动作是"开某一格"，机遇节点按观测
（开出来看到什么数字）分组，用 UCT 在**有限的决策预算**内自适应地分配采样，奖励是
"从这一刻起把这一局赢下来"（0/1）。

因为一局最多只会猜 2~3 次，这棵树其实很浅；预算几乎全花在"哪一格能少一次猜测"上，
而这正是 ``min_prob`` 看不见的东西。
"""

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.enums import Mark
from ..core.geometry import Position
from . import frontier
from .strategy import ActionKind

DEFAULT_TIME = 0.05  # 每次决策的规划预算（秒）
DEFAULT_WORLDS = 24  # 信念集里维护的雷图数量
DEFAULT_CANDIDATES = 6


class _Node(object):
    __slots__ = ("visits", "value", "children", "position", "table")

    def __init__(self, position=None, table=None):
        self.visits = 0
        self.value = 0.0
        self.children = {}
        self.position = position
        self.table = table


def _candidates(table, limit=DEFAULT_CANDIDATES, band=0.15):
    """按概率升序取候选（只在最安全的一小撮里挑，避免把预算浪费在必死的格子上）。"""

    ordered = sorted((p, cell) for cell, p in table.items() if 0.0 < p < 1.0)
    if not ordered:
        return []
    floor = ordered[0][0]
    picked = [(p, cell) for p, cell in ordered if p <= floor + band]
    return picked[:limit]


def _replay(board, mined):
    """在"已知哪些格是雷"的假设下算出每个已开格的数字（用于模拟观测）。"""

    rows, cols = board.rows, board.cols
    numbers = {}
    for row in range(rows):
        for col in range(cols):
            if board.mark_matrix[row][col] != Mark.OPENED:
                continue
            count = 0
            for drow, dcol in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                r, c = row + drow, col + dcol
                if 0 <= r < rows and 0 <= c < cols and (r, c) in mined:
                    count += 1
            numbers[(row, col)] = count
    return numbers


def _rollout_value(board, mined, config, rng):
    """从当前状态按基础策略走完这一局，返回是否获胜。"""

    from .rollout import _world_board

    probe = _world_board(board, mined)
    try:
        solver = __import__("minesweeper.solver.strategy", fromlist=["AutoSolver"]).AutoSolver(
            probe, config=config, rng=rng
        )
    except Exception:
        return 0.0
    for action in solver.actions():
        if action.kind is ActionKind.OPEN:
            status, _cells = probe.expansion(*action.position)
            if getattr(status, "name", "") == "FAIL":
                return 0.0
            if probe.is_won():
                return 1.0
        else:
            probe.mark_mine(*action.position)
            if probe.is_won():
                return 1.0
    return 0.0


def plan_open(board, config=None, budget=DEFAULT_TIME, worlds=DEFAULT_WORLDS, rng=None, log=None):
    """UCT 选格；返回 ``(位置, 估计胜率)``，无法规划时返回 ``None``。

    预算内会反复：选一条未充分探索的动作 → 抽一张与观测一致的雷图 → 从"开这一格"之后
    按基础策略走完 → 用胜负回传。动作价值因此是"这一手之后的整局胜率"，而不只是
    "这一手不炸的概率"。
    """

    import time

    from .strategy import SolverConfig

    if config is None:
        config = SolverConfig(exact_marginals=True, guess_policy="min_prob", endgame=False)
    if rng is None:
        rng = random

    system = frontier.build_system(board)
    table = frontier.probabilities(system)
    picks = _candidates(table, DEFAULT_CANDIDATES)
    if not picks:
        return None

    deadline = time.time() + budget
    nodes: Dict[Position, List[float]] = {cell: [0, 0.0] for _p, cell in picks}
    try:
        layouts = [frontier.sample_mines(system, rng) for _ in range(worlds)]
    except Exception:
        layouts = []
    if not layouts:
        return None

    while time.time() < deadline:
        # UCB1 选动作
        best, best_score = None, -1e9
        total = sum(v[0] for v in nodes.values()) or 1
        for cell, (visits, value) in nodes.items():
            if visits == 0:
                best = cell
                break
            score = value / visits + math.sqrt(2.0 * math.log(total) / visits)
            if score > best_score:
                best, best_score = cell, score
        if best is None:
            break

        layout = rng.choice(layouts)
        reward = 0.0 if best in layout else _rollout_value(board, layout, config, rng)
        nodes[best][0] += 1
        nodes[best][1] += reward

    cell, (visits, value) = max(nodes.items(), key=lambda item: (item[1][1] / max(1, item[1][0]), item[1][0]))
    if visits == 0:
        return None
    estimate = value / visits
    if log is not None:
        log.info("规划选格 %s（估计胜率≈%.3f，%d 次模拟）", cell, estimate, visits)
    return cell, estimate

