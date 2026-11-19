"""全局概率计算：把整盘当成一个约束系统做组合穷举。

只有当"未展开格 + 剩余雷数"都很少时才算得动（阈值在
:class:`minesweeper.solver.strategy.SolverConfig` 里），但它是**精确**的：
每个数字格都要求精确满足，雷的总数也固定，所以得到的 0/1 是真正的逻辑结论。

和局部计算的区别：

* 局部窗口只知道自己那一小块，边界上的数字格只能做上界；
* 全局计算知道整张棋盘，边界数字格也能精确约束。
"""

import logging
from functools import partial

from ..core.board import Board
from ..core.geometry import flatten, to_position
from .engine import Engine, as_result
from .probability import ProbabilityTable
from .window import board_values, unknown_positions

logger = logging.getLogger(__name__)


class WholeSolver:
    """整盘求解器。"""

    def __init__(self, board: Board, engine: Engine) -> None:
        self.board = board
        self.engine = engine

    def probabilities(self) -> ProbabilityTable:
        """整盘概率表 ``{(row, col): 概率}``；不可算时返回空表。"""
        board = self.board
        values = board_values(board)
        unknown = unknown_positions(values)
        remain = board.remain_mine()

        # 剩余雷数的三种非法情况（旧版直接塞给原生模块，KI-3）：
        # 没有未知格、标多了（remain<0）、标少了（remain 比未知格还多）。
        if not unknown or remain < 0 or remain > len(unknown):
            logger.debug(
                "全局计算跳过：未知格=%d, 剩余雷=%d", len(unknown), remain
            )
            return ProbabilityTable()

        # 雷已经全部标完：剩下的未知格必然安全（这是精确结论，不是启发式）。
        if remain == 0:
            return ProbabilityTable({position: 0.0 for position in unknown})

        result = as_result(
            self.engine.whole_cal(
                flatten(values),
                board.rows,
                board.cols,
                remain,
            )
        )
        if not result.usable:
            logger.debug("全局计算无合法布局：count=%d", result.count)
            return ProbabilityTable()

        return ProbabilityTable.from_engine_result(
            result, partial(to_position, cols=board.cols)
        )
