"""界面样式常量。

旧版把这些样式表散落在 5 个方法的字符串字面量里，改一次颜色要全局搜索；
现在集中在这里，测试里也可以直接引用。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

#: 未展开（旧版 style_uncover）
STYLE_COVERED = """
    QPushButton {
        background-color: rgb(65, 163, 255);
        border: 1px solid black;
        padding: 5px;
    }
"""

#: 已展开（旧版 style_open）
STYLE_OPENED = """
    QPushButton {
        background-color: white;
        border: 1px solid black;
        padding: 5px;
    }
"""

#: 失败时点击到的雷
STYLE_MINE_HIT = """
    QPushButton {
        background-color: red;
        border: 1px solid black;
        padding: 5px;
    }
"""

#: 失败时标记正确的地雷
STYLE_MINE_FLAGGED = """
    QPushButton {
        background-color: rgb(36, 169, 102);
        border: 1px solid black;
        padding: 5px;
    }
"""

#: 失败时未标记出来的地雷
STYLE_MINE_UNFLAGGED = """
    QPushButton {
        background-color: yellow;
        border: 1px solid black;
        padding: 5px;
    }
"""

#: 数字 1~6 的颜色，其余数字用黑色（与旧版 update_button_text 一致）
NUMBER_COLORS = {
    1: Qt.blue,
    2: QColor(23, 106, 3),
    3: Qt.red,
    4: Qt.darkBlue,
    5: Qt.darkRed,
    6: QColor(85, 0, 127),
}
DEFAULT_NUMBER_COLOR = Qt.black


def number_color(number):
    """返回数字格应该使用的文字颜色。"""
    return NUMBER_COLORS.get(number, DEFAULT_NUMBER_COLOR)
