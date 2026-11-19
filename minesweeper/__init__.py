"""扫雷游戏（PyQt5 + pybind11 加速）。

分层结构（依赖只能自上而下）::

    minesweeper/
        core/     纯逻辑：棋盘状态、配置与战绩持久化（不依赖 Qt、不依赖 Mat_Cal）
        solver/   自动计算：原生引擎适配、概率计算、策略循环
        ui/       PyQt5 界面：主窗口、设置对话框、按钮控件
        paths.py  运行时路径（PyStand / 嵌入式 Python 的 sys.path 处理）
        app.py    程序入口（创建 QApplication、加载配置、显示窗口）

典型用法::

    from minesweeper import Board, AutoSolver, load_engine

    board = Board(9, 9, 10)
    board.gen_mine((4, 4))
    board.expansion(4, 4)
    for action in AutoSolver(board, engine=load_engine()).actions():
        ...
"""

from .core.board import Board
from .core.enums import DIRECTIONS, MINE, Mark, Status
from .solver.engine import EngineUnavailable, load_engine
from .solver.strategy import Action, ActionKind, AutoSolver, SolverConfig

__version__ = "2.0.0"

__all__ = [
    "Board",
    "DIRECTIONS",
    "MINE",
    "Mark",
    "Status",
    "EngineUnavailable",
    "load_engine",
    "Action",
    "ActionKind",
    "AutoSolver",
    "SolverConfig",
    "__version__",
]
