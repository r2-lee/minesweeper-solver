"""自动计算层。

依赖关系（自下而上）::

    probability.py  概率表的类型与"挑一个最安全的格子"的公共逻辑
    engine.py       组合穷举（原生 Mat_Cal / 纯 Python 参考实现）
    window.py       把棋盘裁剪成"局部窗口"，并给出可信的雷数上下界
    local.py        局部概率（等价旧版 autoCal_local）
    whole.py        全局概率（等价旧版 autoCal_whole）
    strategy.py     策略循环（等价旧版 auto_calculate 生成器）
    benchmark.py    整局对局与胜率统计

只有 :class:`~minesweeper.solver.strategy.AutoSolver` 会被界面调用，
其余都是它拆下来的零件，也都可以在测试里单独替换。
"""

from .benchmark import GameOutcome, play_game, run
from .engine import (
    Engine,
    EngineResult,
    EngineUnavailable,
    NativeEngine,
    ReferenceEngine,
    load_engine,
)
from .local import LocalSolver
from .probability import ProbabilityTable, TableLike, best_guess
from .strategy import Action, ActionKind, AutoSolver, SolverConfig
from .whole import WholeSolver
from .window import LocalWindow, board_values, build_window, local_centers, unknown_positions

__all__ = [
    # 概率
    "ProbabilityTable",
    "TableLike",
    "best_guess",
    # 引擎
    "Engine",
    "EngineResult",
    "EngineUnavailable",
    "NativeEngine",
    "ReferenceEngine",
    "load_engine",
    # 窗口与求解器
    "LocalWindow",
    "build_window",
    "board_values",
    "unknown_positions",
    "local_centers",
    "LocalSolver",
    "WholeSolver",
    # 策略
    "Action",
    "ActionKind",
    "AutoSolver",
    "SolverConfig",
    # 测量
    "GameOutcome",
    "play_game",
    "run",
]
