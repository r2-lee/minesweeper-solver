"""设置对话框：选择初级 / 中级 / 高级 / 自定义棋盘。

布局与旧版 ``SettingsDialog`` 保持一致（自定义单选按钮只出现在网格里，
不进入左侧竖排布局，也不预选中任何等级）。
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.storage import MAX_COLS, MAX_MINES, MAX_ROWS, MIN_COLS, MIN_MINES, MIN_ROWS

#: 三个预设等级（与旧版一致；注意「高级」是 16x30x99）
BEGINNER = {"rows": 9, "cols": 9, "mines": 10}
INTERMEDIATE = {"rows": 16, "cols": 16, "mines": 40}
ADVANCED = {"rows": 16, "cols": 30, "mines": 99}


class SettingsDialog(QDialog):
    """游戏设置对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置对话框")

        main_layout = QVBoxLayout()

        level_layout = QVBoxLayout()
        self.level_group = QButtonGroup(self)

        self.beginner_radio = QRadioButton("初级")
        self.intermediate_radio = QRadioButton("中级")
        self.advanced_radio = QRadioButton("高级")
        self.custom_radio = QRadioButton("自定义")

        level_layout.addWidget(self.beginner_radio)
        level_layout.addWidget(self.intermediate_radio)
        level_layout.addWidget(self.advanced_radio)

        self.level_group.addButton(self.beginner_radio)
        self.level_group.addButton(self.intermediate_radio)
        self.level_group.addButton(self.advanced_radio)
        self.level_group.addButton(self.custom_radio)

        custom_layout = QGridLayout()

        self.height_label = QLabel("高度")
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(MIN_ROWS, MAX_ROWS)

        self.width_label = QLabel("宽度")
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(MIN_COLS, MAX_COLS)

        self.mine_label = QLabel("雷数")
        self.mine_spinbox = QSpinBox()
        self.mine_spinbox.setRange(MIN_MINES, MAX_MINES)

        custom_layout.addWidget(self.custom_radio, 1, 1)
        custom_layout.addWidget(self.height_label, 2, 1)
        custom_layout.addWidget(self.height_spinbox, 2, 2)
        custom_layout.addWidget(self.width_label, 3, 1)
        custom_layout.addWidget(self.width_spinbox, 3, 2)
        custom_layout.addWidget(self.mine_label, 4, 1)
        custom_layout.addWidget(self.mine_spinbox, 4, 2)

        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("退出")
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        layout1 = QHBoxLayout()
        layout1.addLayout(level_layout)
        layout1.addLayout(custom_layout)
        main_layout.addLayout(layout1)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def get_settings(self) -> dict:
        """返回选中的配置；一个都没选时返回空 dict（与旧版一致）。"""
        if self.beginner_radio.isChecked():
            return dict(BEGINNER)
        if self.intermediate_radio.isChecked():
            return dict(INTERMEDIATE)
        if self.advanced_radio.isChecked():
            return dict(ADVANCED)
        if self.custom_radio.isChecked():
            return {
                "rows": self.height_spinbox.value(),
                "cols": self.width_spinbox.value(),
                "mines": self.mine_spinbox.value(),
            }
        return {}
