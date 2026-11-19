"""棋盘状态与格子标记的常量定义。

这里刻意保持为纯枚举常量，不依赖 Qt、不依赖原生模块，
这样任何测试都可以直接 import 而不需要启动 GUI。
"""

from enum import Enum, IntEnum


class Status(Enum):
    """一局游戏的状态。"""

    NORMAL = 1
    FAIL = 2
    WIN = 3


class Mark(IntEnum):
    """mark_matrix 中保存的格子标记值。

    与旧版 mine.py 中的数字一一对应（旧版混用了裸数字 0/1/2/-10）:

        0   -> Mark.COVERED   未展开
        1   -> Mark.FLAG      标记为雷
        2   -> Mark.QUESTION  标记为问号
        -10 -> Mark.OPENED    已展开
    """

    COVERED = 0
    FLAG = 1
    QUESTION = 2
    OPENED = -10


# mine_matrix 中表示"是雷"的取值。
MINE = -1

# 八邻域方向，顺序与旧版 mine.py 完全一致。
# 旧版顺序会影响到 get_round() 的返回顺序，测试里对此有断言。
DIRECTIONS = (
    (0, 1),
    (0, -1),
    (-1, 0),
    (1, 0),
    (1, 1),
    (1, -1),
    (-1, 1),
    (-1, -1),
)
