"""局部概率计算：围绕一个数字格做组合穷举，得到每格"是雷"的频率。

这是整条求解链里最底层、被调用得最频繁的一步。它只做两件事：

1. 把棋盘的一个小窗口交给 :class:`Engine`（原生模块或参考实现）；
2. 把"每个格子被选中了多少次"换算成概率表。

所有"这个窗口能不能算"的判断都收敛到 :meth:`LocalWindow.check`，
这里只负责记录原因并返回空表——空表在策略层的含义是"没有新信息"。
"""

import logging
from typing import Optional

from ..core.board import Board
from ..core.geometry import Position
from .engine import Engine, as_result
from .probability import ProbabilityTable
from .window import LocalWindow, build_window

logger = logging.getLogger(__name__)


class LocalSolver:
    """局部求解器：一次算一个数字格周围的小窗口。

    用法::

        solver = LocalSolver(board, engine)
        table = solver.probabilities(3, 4, level=2)   # {(row, col): 概率}
    """

    def __init__(self, board: Board, engine: Engine) -> None:
        self.board = board
        self.engine = engine

    def window(self, x: int, y: int, level: int = 2) -> LocalWindow:
        """取出窗口对象（测试和调试时想直接看矩阵/上下界就调它）。"""
        return build_window(self.board, x, y, level)

    def probabilities(self, x: int, y: int, level: int = 2) -> ProbabilityTable:
        """算 (x, y) 周围窗口的概率表。

        :return: ``{(row, col): 概率}``；窗口不可算或没有合法布局时返回空表。
                 概率 0 表示"确定安全"，1 表示"确定是雷"。
        """
        window = self.window(x, y, level)

        reason: Optional[str] = window.check()
        if reason is not None:
            # 正常的"算不了"，不是错误：空白格、边界窗口、误标都会走到这里。
            logger.debug("局部窗口 (%s, %s) 跳过：%s", x, y, reason)
            return ProbabilityTable()

        result = as_result(
            self.engine.local_cal(
                window.flat,
                window.rows,
                window.cols,
                window.min_mines,
                window.max_mines,
                window.strict_positions,
            )
        )
        if not result.usable:
            # count == -1：原生模块表示"算不了"；count == 0：约束自相矛盾。
            # 旧版把这两种都当成"有解"，于是 abs(0 / -1) == 0 把整窗标成安全（KI-1）。
            logger.debug("局部窗口 (%s, %s) 无合法布局：count=%d", x, y, result.count)
            return ProbabilityTable()

        return ProbabilityTable.from_engine_result(result, window.absolute)
