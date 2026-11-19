"""纯逻辑层：棋盘状态、几何换算、配置与战绩持久化。

这一层不依赖 PyQt5，也不依赖原生模块 Mat_Cal，因此可以直接在普通 Python 里测试。

模块划分::

    enums.py     状态 / 标记常量
    geometry.py  坐标与下标的换算、邻域遍历
    board.py     棋盘（布雷、展开、标雷、判胜）
    storage.py   config.json / results.json 的读写
"""

from .board import Board
from .enums import DIRECTIONS, MINE, Mark, Status
from .geometry import (
    Matrix,
    Position,
    flatten,
    iter_positions,
    neighbours,
    shape,
    to_index,
    to_position,
)
from .storage import (
    DEFAULT_CONFIG,
    append_result,
    config_key,
    is_valid_config,
    load_config,
    load_results,
    save_config,
)

__all__ = [
    "Board",
    "DIRECTIONS",
    "MINE",
    "Mark",
    "Status",
    "Matrix",
    "Position",
    "flatten",
    "iter_positions",
    "neighbours",
    "shape",
    "to_index",
    "to_position",
    "DEFAULT_CONFIG",
    "append_result",
    "config_key",
    "is_valid_config",
    "load_config",
    "load_results",
    "save_config",
]
