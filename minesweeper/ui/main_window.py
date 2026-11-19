"""主窗口：棋盘交互、计时、记录、自动计算 / 辅助计算。

这是旧版 ``mine.py`` 里 ``MainWindow`` 的等价移植。除了几处明确的缺陷修复
（见各方法注释里的 ``DEV-`` 编号），行为与旧版保持一致：包括左右键同时按下
的判断优先级、右键不刷新雷数显示、连续计算等细节。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PyQt5.QtCore import QEvent, QTime, QTimer, Qt
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLCDNumber,
    QMainWindow,
    QMenuBar,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QToolBar,
    QToolButton,
    QWidget,
)

from .. import paths
from ..core import storage
from ..core.board import Board
from ..core.enums import Mark, Status
from ..solver.engine import EngineUnavailable, load_engine
from ..solver.local import LocalSolver
from ..solver.strategy import ActionKind, AutoSolver
from . import styles
from .dialogs import SettingsDialog
from .widgets import CustomButton

DEFAULT_AUTOCALC_SPEED = 30
BOARD_FONT_FAMILY = "Arial Black"
BOARD_FONT_SIZE = 12
MIN_CELL_SIZE = 20


def restart_command() -> list:
    """返回重启程序要执行的命令。

    旧版是 ``subprocess.Popen(f"{current_dir}\\main.exe")``，而 ``main.exe``
    并不存在——一改设置程序就关闭且不再启动（DEV-3）。这里优先用同目录下的
    启动器 exe（``mine.exe``），否则退回到「当前解释器 + mine.py」。
    """
    for name in ("mine.exe", "PyStand.exe"):
        launcher = paths.app_path(name)
        if os.path.isfile(launcher):
            return [launcher]
    return [sys.executable, paths.entry_script()]


class MainWindow(QMainWindow):
    """扫雷主窗口。"""

    def __init__(
        self,
        config: dict,
        board: Board = None,
        engine=None,
        config_file: str = None,
        results_file: str = None,
    ):
        super().__init__()
        self.config = dict(config)
        self.rows = self.config["rows"]
        self.cols = self.config["cols"]
        self._config_file = config_file or paths.config_path()
        self._results_file = results_file or paths.results_path()
        self.board = board if board is not None else Board(self.rows, self.cols, self.config["mines"])
        self._engine = engine

        self.first_click = True
        self.cheatTime = 0
        self.isFinish = False
        self.isReset = False
        self._GameState = Status.NORMAL
        # 鼠标中键 / 左右键同按时的确认状态
        self.current_button = None
        self.checkState = False

        self.autocalSpeed = DEFAULT_AUTOCALC_SPEED
        self.AutoCaltimer = QTimer(self)
        self.AutoCaltimer.timeout.connect(self.update_view)
        self.generator = None
        self._autosolver = None
        self.Timer = QTimer(self)
        self.time = QTime(0, 0, 0)
        self.Timer.timeout.connect(self.update_time)

        self.initUI()

    # ------------------------------------------------------------------
    # 兼容旧属性名：旧代码到处写的是 self.mineClass
    # ------------------------------------------------------------------
    @property
    def mineClass(self) -> Board:
        """旧版对棋盘对象的称呼，保留为只读别名。"""
        return self.board

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def initUI(self) -> None:
        self.setWindowTitle("扫雷")
        font = QFont(BOARD_FONT_FAMILY, BOARD_FONT_SIZE)
        font.setBold(True)

        grid_layout = QGridLayout()
        grid_layout.setSpacing(0)

        self.ButtonList = [[None for _ in range(self.cols)] for _ in range(self.rows)]

        for i in range(self.rows):
            for j in range(self.cols):
                button = CustomButton()
                button.setStyleSheet(self.style_uncover)
                button.setFont(font)
                button.setMinimumSize(MIN_CELL_SIZE, MIN_CELL_SIZE)
                button.installEventFilter(self)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                grid_layout.addWidget(button, i, j)
                self.ButtonList[i][j] = button
                button.row = i
                button.col = j

        for row in range(self.rows):
            grid_layout.setRowStretch(row, 1)
        for col in range(self.cols):
            grid_layout.setColumnStretch(col, 1)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setLayout(grid_layout)

        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        self.label = QLabel("剩余雷数")
        toolbar.addWidget(self.label)

        self.lcd_number = QLCDNumber()
        self.lcd_number.setSegmentStyle(QLCDNumber.Flat)
        self.lcd_number.display(self.board.remain_mine())

        palette = self.lcd_number.palette()
        palette.setColor(QPalette.Window, QColor(0, 0, 0))
        palette.setColor(QPalette.WindowText, QColor(255, 255, 255))

        self.cheatlcd_number = QLCDNumber()
        self.cheatlcd_number.setSegmentStyle(QLCDNumber.Flat)
        self.cheatlcd_number.display(self.cheatTime)

        self.timelcd = QLCDNumber()
        self.timelcd.setSegmentStyle(QLCDNumber.Flat)
        self.timelcd.display(self.time.toString("mm:ss"))

        for lcd in (self.lcd_number, self.cheatlcd_number, self.timelcd):
            lcd.setPalette(palette)
            lcd.setStyleSheet("background-color: black; color: white;")

        toolbar.addWidget(self.lcd_number)

        self.startButton = QToolButton()
        self.startButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

        self.resetButton = QToolButton()
        self.resetButton.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))

        self.showButton = QToolButton()
        self.showButton.setIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
        self.showButton.setText("全部展开")
        self.showButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.helpButton = QToolButton()
        self.helpButton.setIcon(self.style().standardIcon(QStyle.SP_DialogNoButton))
        self.helpButton.setCheckable(True)
        self.helpButton.setText("辅助计算 阶数:")
        self.helpButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.autoCalButton = QToolButton()
        self.autoCalButton.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self.autoCalButton.setCheckable(True)
        self.autoCalButton.setText("自动计算")
        self.autoCalButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.cheatButton = QToolButton()
        self.cheatButton.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.cheatButton.setCheckable(True)
        self.cheatButton.setText("作弊一次")
        self.cheatButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.helpspinbox = QSpinBox()
        self.helpspinbox.setRange(1, 6)

        toolbar.addWidget(self.startButton)
        toolbar.addWidget(self.resetButton)
        toolbar.addWidget(self.showButton)

        container = QWidget()
        layout = QHBoxLayout()
        layout.addWidget(self.helpButton)
        layout.addWidget(self.helpspinbox)
        container.setLayout(layout)
        toolbar.addWidget(container)
        toolbar.addWidget(self.autoCalButton)
        toolbar.addWidget(self.cheatButton)
        toolbar.addWidget(self.cheatlcd_number)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar.addWidget(spacer)
        label1 = QLabel("时间：")
        toolbar.addWidget(label1)
        toolbar.addWidget(self.timelcd)

        self.startButton.clicked.connect(self.newstart)
        self.resetButton.clicked.connect(self.reset)
        self.showButton.clicked.connect(self.showall)
        self.autoCalButton.toggled.connect(self.autocalculate)

        menu_bar = QMenuBar()
        self.setMenuBar(menu_bar)

        settingMenu = menu_bar.addMenu("设置")
        set_action = QAction("游戏设置", self)
        set_action.triggered.connect(self.Game_Set)
        settingMenu.addAction(set_action)

        setspeed_menu = settingMenu.addMenu("自动计算速度")
        action_group = QActionGroup(self)
        speed_action1 = QAction("非常慢", self, checkable=True, checked=False)
        speed_action2 = QAction("慢", self, checkable=True, checked=False)
        speed_action3 = QAction("中等", self, checkable=True, checked=False)
        speed_action4 = QAction("快", self, checkable=True, checked=True)
        speed_action5 = QAction("非常快", self, checkable=True, checked=False)
        for action in (speed_action1, speed_action2, speed_action3, speed_action4, speed_action5):
            setspeed_menu.addAction(action)
            action_group.addAction(action)

        speed_action1.triggered.connect(lambda: self.set_speed(1000))
        speed_action2.triggered.connect(lambda: self.set_speed(300))
        speed_action3.triggered.connect(lambda: self.set_speed(100))
        speed_action4.triggered.connect(lambda: self.set_speed(30))
        speed_action5.triggered.connect(lambda: self.set_speed(1))

        start_action = QAction("新游戏", self)
        start_action.triggered.connect(self.newstart)
        reset_action = QAction("重置本次游戏", self)
        reset_action.triggered.connect(self.reset)
        show_action = QAction("全部展开", self)
        show_action.triggered.connect(self.showall)
        cal_action = QAction("自动计算", self)
        cal_action.triggered.connect(self.autocalculate)
        self.continue_action = QAction("连续计算", self)
        self.continue_action.setCheckable(True)
        self.continue_action.setChecked(False)

        settingMenu.addAction(start_action)
        settingMenu.addAction(reset_action)
        settingMenu.addAction(show_action)
        settingMenu.addAction(cal_action)
        settingMenu.addAction(self.continue_action)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    @property
    def GameState(self) -> Status:
        return self._GameState

    @GameState.setter
    def GameState(self, new_value: Status) -> None:
        if self._GameState != new_value:
            self._GameState = new_value
            self.handleValueChanged(new_value)

    def set_speed(self, speed: int) -> None:
        self.autocalSpeed = speed

    def handleValueChanged(self, value: Status) -> None:
        if value == Status.WIN:
            self.isFinish = True
            self.Timer.stop()
            self.startButton.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            self.log_function_call(1)
        elif value == Status.FAIL:
            self.isFinish = True
            self.Timer.stop()
            self.startButton.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
            self.log_function_call(0)

    def log_function_call(self, state: int) -> None:
        """把本局结果追加写入 results.json。"""
        record = {
            "state": state,
            "time": self.time.toString("mm:ss"),
            "currenttime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cheat": self.cheatTime,
        }
        key = storage.config_key(
            {"rows": self.rows, "cols": self.cols, "mines": self.config["mines"]}
        )
        storage.append_result(self._results_file, key, record)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if any(button == obj for row in self.ButtonList for button in row):
            if event.type() == QEvent.MouseButtonPress:
                # 注意运算符优先级：旧版这里等价于
                #   (buttons == Left|Right) or (buttons == Middle and not isFinish)
                # 即「左右键同按」不受 isFinish 限制，保留原行为。
                if event.buttons() == (
                    Qt.LeftButton | Qt.RightButton
                ) or event.buttons() == Qt.MiddleButton and not self.isFinish:
                    self.checkState = True
                    self.current_button = obj
                    self.update_surrounding_buttons(obj, self.style_open)
                elif event.button() == Qt.LeftButton and event.buttons() & Qt.LeftButton:
                    self.on_left_button_clicked(obj)
                elif event.button() == Qt.RightButton and event.buttons() & Qt.RightButton:
                    self.on_right_button_clicked(obj)

            elif event.type() == QEvent.MouseButtonRelease:
                if self.checkState and event.button() in (
                    Qt.MiddleButton,
                    Qt.LeftButton,
                    Qt.RightButton,
                ):
                    self.on_middle_button_clicked(self.current_button)
                    self.current_button = None
                    self.checkState = False

            elif event.type() == QEvent.MouseMove:
                if event.buttons() == (
                    Qt.LeftButton | Qt.RightButton
                ) or event.buttons() == Qt.MiddleButton:
                    button = QApplication.widgetAt(event.globalPos())
                    if (
                        isinstance(button, CustomButton)
                        and button != self.current_button
                        and not self.isFinish
                    ):
                        if self.current_button:
                            self.update_surrounding_buttons(self.current_button, self.style_uncover)
                        self.current_button = button
                        self.update_surrounding_buttons(button, self.style_open)

            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self.on_middle_button_clicked(obj)

        return super().eventFilter(obj, event)

    def update_surrounding_buttons(self, button, style: str) -> None:
        """把 ``button`` 周围 3x3 内未翻开的格子换成指定样式。"""
        if button is None:
            return
        for i in range(-1, 2):
            for j in range(-1, 2):
                row = getattr(button, "row", None)
                col = getattr(button, "col", None)
                if row is None or col is None:
                    return
                if (
                    0 <= row + i < self.rows
                    and 0 <= col + j < self.cols
                    and self.board.mark_matrix[row + i][col + j] == Mark.COVERED
                ):
                    self.ButtonList[row + i][col + j].setStyleSheet(style)

    # ------------------------------------------------------------------
    # 棋盘操作
    # ------------------------------------------------------------------
    def expansion(self, x: int, y: int) -> None:
        state, expansion_list = self.board.expansion(x, y)
        if state in (Status.NORMAL, Status.WIN):
            for px, py in expansion_list:
                button = self.ButtonList[px][py]
                self.update_button_text(button, self.board.mine_matrix[px][py])
            self.GameState = state
        else:
            self.show_mines(x, y)
            self.GameState = state

    def mine_mark(self, x: int, y: int) -> None:
        self.GameState = self.board.mark_mine(x, y)
        button = self.ButtonList[x][y]
        button.setText("★")
        button.setStyleSheet(self.style_uncover)
        self.lcd_number.display(self.board.remain_mine())

    def show_mines(self, x: int, y: int) -> None:
        """失败时揭示所有雷：标对的绿底、标错的 X、未标的黄底，点击处红底。"""
        for i in range(self.rows):
            for j in range(self.cols):
                if (
                    self.board.mark_matrix[i][j] == Mark.FLAG
                    or self.board.mine_matrix[i][j] == -1
                ):
                    button = self.ButtonList[i][j]
                    if (
                        self.board.mark_matrix[i][j] == Mark.FLAG
                        and self.board.mine_matrix[i][j] != -1
                    ):
                        button.setText("X")
                    elif (
                        self.board.mark_matrix[i][j] == Mark.FLAG
                        and self.board.mine_matrix[i][j] == -1
                    ):
                        button.setStyleSheet(styles.STYLE_MINE_FLAGGED)
                        button.setText("⚡")
                    else:
                        button.setStyleSheet(styles.STYLE_MINE_UNFLAGGED)
                        button.setText("⚡")

        clicked_button = self.ButtonList[x][y]
        clicked_button.setStyleSheet(styles.STYLE_MINE_HIT)
        clicked_button.setText("⚡")

    def on_left_button_clicked(self, button) -> None:
        if self.isFinish:
            return
        x, y = button.row, button.col
        if self.board.mark_matrix[x][y] == Mark.FLAG:
            return
        if self.first_click:
            self.board.gen_mine((x, y))
            self.expansion(x, y)
            self.first_click = False
            self.Timer.start(1000)
        else:
            self.expansion(x, y)

    def on_right_button_clicked(self, button) -> None:
        if self.isFinish:
            return
        x, y = button.row, button.col
        if self.first_click:
            return
        mark, _state = self.board.cycle_flag(x, y)
        if mark == Mark.COVERED:
            button.setText("")
        elif mark == Mark.QUESTION:
            button.setText("?")
        elif mark == Mark.FLAG:
            # 旧版右键走 mine_mark 分支时会刷新雷数显示；保持该行为
            button.setText("★")
            button.setStyleSheet(self.style_uncover)
            self.lcd_number.display(self.board.remain_mine())

    def on_middle_button_clicked(self, button) -> None:
        if self.isFinish:
            return
        if button is None:  # DEV-2：旧版此处会 AttributeError
            return
        x, y = button.row, button.col
        if self.board.mark_matrix[x][y] == Mark.OPENED:
            pos = self.board.get_round(x, y)
            if self.cheatButton.isChecked():
                for px, py in pos:
                    # 旧版写的是 mark != 10（恒真，因为标记只可能是 0/1/2/-10），保留
                    if self.board.mark_matrix[px][py] != 10:
                        if self.board.mine_matrix[px][py] >= 0:
                            self.expansion(px, py)
                        else:
                            self.mine_mark(px, py)

                self.cheatButton.setChecked(False)
                self.cheatTime = self.cheatTime + 1
                self.cheatlcd_number.display(self.cheatTime)
                return

            if self.helpButton.isChecked():
                try:
                    info_dict = self.local_solver().probabilities(x, y, self.helpspinbox.value())
                except (EngineUnavailable, IndexError) as exc:
                    print("Error:", exc)
                    info_dict = {}
                for (px, py), value in info_dict.items():
                    if value == 0:
                        self.expansion(px, py)
                    elif value == 1:
                        self.mine_mark(px, py)

            count = 0  # 标记为雷且确实为雷
            count1 = 0  # 标记为雷
            for px, py in pos:
                if self.board.mark_matrix[px][py] == Mark.FLAG:
                    count1 = count1 + 1
                    if self.board.mine_matrix[px][py] == -1:
                        count = count + 1

            if count1 == self.board.mine_matrix[x][y] and count == count1:
                for px, py in pos:
                    if self.board.mark_matrix[px][py] in (Mark.COVERED, Mark.QUESTION):
                        self.expansion(px, py)

            elif count1 == self.board.mine_matrix[x][y] and count != count1:
                self.show_mines(x, y)

            else:
                button.start_flash()
                self.update_surrounding_buttons(self.ButtonList[x][y], self.style_uncover)
        else:
            self.update_surrounding_buttons(self.current_button, self.style_uncover)

    def update_button_text(self, button, number: int) -> None:
        button.setStyleSheet(self.style_open)
        if number == 0:
            button.setText("")
        else:
            button.setText(str(number))

        palette = button.palette()
        palette.setColor(QPalette.ButtonText, styles.number_color(number))
        button.setPalette(palette)

    def local_solver(self) -> LocalSolver:
        """惰性构造辅助计算用的 LocalSolver。"""
        if self._engine is None:
            self._engine = load_engine()
        return LocalSolver(self.board, self._engine)

    # ------------------------------------------------------------------
    # 菜单 / 按钮动作
    # ------------------------------------------------------------------
    def Game_Set(self) -> None:  # noqa: N802 - 沿用旧版命名
        settings_dialog = SettingsDialog(self)
        if settings_dialog.exec_() == SettingsDialog.Accepted:
            settings = settings_dialog.get_settings()
            self.reinitialize_game(settings)

    def reinitialize_game(self, settings: dict) -> None:
        """保存新配置并重启程序。"""
        if not settings:
            return
        data = storage.load_config(self._config_file)
        changed = False
        for key in settings:
            if data.get(key) != settings[key]:
                changed = True
                data[key] = settings[key]

        if changed:
            storage.save_config(self._config_file, data)

        command = restart_command()
        self.close()
        subprocess.Popen(command, cwd=paths.APP_DIR)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def newstart(self) -> None:
        for row in self.ButtonList:
            for btn in row:
                btn.stop_flash()
                btn.setStyleSheet(self.style_uncover)
                btn.setText("")
        self.first_click = True
        self.cheatTime = 0
        self.isFinish = False
        self.isReset = False
        self.time = QTime(0, 0, 0)
        self.Timer.stop()
        self.board.new_game()
        self.lcd_number.display(self.board.remain_mine())
        self.cheatlcd_number.display(self.cheatTime)
        self.timelcd.display(self.time.toString("mm:ss"))
        self.startButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def reset(self) -> None:
        for row in self.ButtonList:
            for btn in row:
                btn.stop_flash()
                btn.setStyleSheet(self.style_uncover)
                btn.setText("")
        self.first_click = False
        self.cheatTime = 0
        self.isFinish = False
        self.isReset = True
        self.time = QTime(0, 0, 0)
        self.Timer.stop()
        self.board.reset()
        self.lcd_number.display(self.board.remain_mine())
        self.cheatlcd_number.display(self.cheatTime)
        self.timelcd.display(self.time.toString("mm:ss"))
        self.startButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def showall(self) -> None:
        if self.first_click:
            return
        for i in range(self.rows):
            for j in range(self.cols):
                button = self.ButtonList[i][j]
                state = self.board.mine_matrix[i][j]
                if state == -1:
                    button.setStyleSheet(styles.STYLE_MINE_HIT)
                    button.setText("⚡")
                else:
                    self.update_button_text(button, state)
        self.first_click = False
        self.isFinish = True

    def autocalculate(self, checked: bool) -> None:
        if self.isFinish or self.isReset:
            self.autoCalButton.setChecked(False)
            return
        if checked:
            if self.first_click:
                px, py = self.board.random_position()
                self.board.new_game()
                self.board.gen_mine((px, py))
                self.first_click = False
                self.expansion(px, py)
                self.Timer.start(1000)

            self._autosolver = AutoSolver(self.board)
            self.generator = self._autosolver.actions()
            self.AutoCaltimer.setInterval(self.autocalSpeed)
            self.AutoCaltimer.start()
            self.update_view()
        else:
            self.AutoCaltimer.stop()

    def update_view(self) -> None:
        if not self.autoCalButton.isChecked():
            return
        try:
            action = next(self.generator)
            if action.kind == ActionKind.OPEN:
                self.expansion(action.position[0], action.position[1])
            else:
                self.mine_mark(action.position[0], action.position[1])
            if self.isFinish:
                raise StopIteration
            if self.board.is_won():
                raise StopIteration
        except StopIteration:
            self.autoCalButton.setChecked(False)
            self._autosolver = AutoSolver(self.board)
            self.generator = self._autosolver.actions()
            if self.continue_action.isChecked():
                self.newstart()
                self.autocalculate(True)
                self.autoCalButton.setChecked(True)

    def update_time(self) -> None:
        self.time = self.time.addSecs(1)
        self.timelcd.display(self.time.toString("mm:ss"))

    # ------------------------------------------------------------------
    # 样式（旧版是 property，保持同名）
    # ------------------------------------------------------------------
    @property
    def style_uncover(self) -> str:
        return styles.STYLE_COVERED

    @property
    def style_open(self) -> str:
        return styles.STYLE_OPENED
