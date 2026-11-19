"""游戏格子按钮。

与旧版 ``CustomButton`` 行为一致：除了普通按钮功能外，还支持「闪红叉」——
在辅助计算判错时通过 ``start_flash()`` 连续 4 次（每次 100ms）切换红叉显示。
"""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QPushButton

FLASH_INTERVAL_MS = 100
FLASH_TIMES = 4


class CustomButton(QPushButton):
    """带闪烁红叉功能的格子按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flash_count = 0
        self.is_flashing = False
        self.show_x = False
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.flash)

    def start_flash(self) -> None:
        """开始闪红叉（4 次，每次 100ms）。"""
        self.is_flashing = True
        self.flash_count = 0
        self.show_x = True
        self.update()
        self.flash_timer.start(FLASH_INTERVAL_MS)

    def flash(self) -> None:
        """定时器回调：切换红叉显示，满 4 次后复位。"""
        self.flash_count += 1
        self.show_x = not self.show_x
        self.update()
        if self.flash_count >= FLASH_TIMES:
            self.flash_timer.stop()
            self.is_flashing = False
            self.show_x = False
            self.flash_count = 0
            self.update()

    def stop_flash(self) -> None:
        """立即停止闪烁并复位状态（测试与重开游戏时使用）。"""
        self.flash_timer.stop()
        self.is_flashing = False
        self.show_x = False
        self.flash_count = 0
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        super().paintEvent(event)
        if self.is_flashing and self.show_x:
            self.paintX()

    def paintX(self) -> None:  # noqa: N802 - 沿用旧版命名
        """在按钮中心画一个红色 2px 的叉。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255, 0, 0), 2))
        center_x = self.width() // 2
        center_y = self.height() // 2
        side_length = min(self.width(), self.height()) // 2
        painter.drawLine(
            center_x - side_length,
            center_y - side_length,
            center_x + side_length,
            center_y + side_length,
        )
        painter.drawLine(
            center_x + side_length,
            center_y - side_length,
            center_x - side_length,
            center_y + side_length,
        )
