"""界面层测试（offscreen 平台，不需要真实显示器，也不依赖 QtTest 模块）。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from . import support  # noqa: F401  设置 sys.path 与 QT_QPA_PLATFORM

try:  # 没装 PyQt5 时整组跳过，方便在只有核心依赖的环境里跑测试
    from PyQt5.QtCore import QEvent, QPointF, Qt  # noqa: E402
    from PyQt5.QtGui import QMouseEvent  # noqa: E402
    from PyQt5.QtWidgets import QApplication  # noqa: E402
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest("PyQt5 未安装，跳过界面测试：%s" % exc)

from minesweeper import paths  # noqa: E402
from minesweeper.app import create_application  # noqa: E402
from minesweeper.core.enums import Mark, Status  # noqa: E402
from minesweeper.solver.engine import ReferenceEngine  # noqa: E402
from minesweeper.solver.strategy import Action, ActionKind  # noqa: E402
from minesweeper.ui.dialogs import (  # noqa: E402
    ADVANCED,
    BEGINNER,
    INTERMEDIATE,
    SettingsDialog,
)
from minesweeper.ui.main_window import MainWindow, restart_command  # noqa: E402
from minesweeper.ui.widgets import FLASH_TIMES, CustomButton  # noqa: E402

from .support import make_board  # noqa: E402

_APP = None


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


# ----------------------------------------------------------------------
# 手工构造鼠标事件（这个 PyQt5 精简包里没有 QtTest 模块）
# ----------------------------------------------------------------------
def _send(widget, event_type, button, buttons):
    local = QPointF(widget.width() / 2.0, widget.height() / 2.0)
    global_pos = QPointF(widget.mapToGlobal(local.toPoint()))
    event = QMouseEvent(event_type, local, global_pos, button, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


def press(widget, button=Qt.LeftButton, buttons=None):
    _send(widget, QEvent.MouseButtonPress, button, button if buttons is None else buttons)


def release(widget, button=Qt.LeftButton):
    _send(widget, QEvent.MouseButtonRelease, button, Qt.NoButton)


def click(widget, button=Qt.LeftButton):
    press(widget, button)
    release(widget, button)


class WindowTestCase(unittest.TestCase):
    """建一个 9x9/10 雷的窗口，配置文件落在临时目录里。"""

    config = {"rows": 9, "cols": 9, "mines": 10}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_file = os.path.join(self._tmp.name, "config.json")
        self.results_file = os.path.join(self._tmp.name, "results.json")
        self.window = self.make_window()
        self.addCleanup(self.window.deleteLater)

    def make_window(self, board=None, config=None):
        window = MainWindow(
            config or self.config,
            board=board,
            engine=ReferenceEngine(),
            config_file=self.config_file,
            results_file=self.results_file,
        )
        self.addCleanup(window.close)
        return window

    # -- 小工具 --------------------------------------------------------
    def first_click(self, row=4, col=4):
        click(self.window.ButtonList[row][col], Qt.LeftButton)
        return self.window.ButtonList[row][col]

    def find_covered_button(self):
        for row in range(self.window.rows):
            for col in range(self.window.cols):
                if self.window.board.mark_matrix[row][col] == Mark.COVERED:
                    return self.window.ButtonList[row][col]
        self.fail("没有未展开的格子了")

    def all_texts(self):
        return [button.text() for row in self.window.ButtonList for button in row]


class InitUITest(WindowTestCase):
    def test_grid_is_built(self):
        self.assertEqual(len(self.window.ButtonList), 9)
        self.assertTrue(all(len(row) == 9 for row in self.window.ButtonList))
        self.assertTrue(
            all(
                isinstance(button, CustomButton)
                for row in self.window.ButtonList
                for button in row
            )
        )
        self.assertEqual(self.window.windowTitle(), "扫雷")
        self.assertEqual(self.window.board.mines, 10)

    def test_button_carries_coordinates(self):
        button = self.window.ButtonList[3][5]
        self.assertEqual((button.row, button.col), (3, 5))

    def test_custom_board_is_used(self):
        board = make_board(3, 3, [(0, 0)])
        window = self.make_window(board=board, config={"rows": 3, "cols": 3, "mines": 1})
        self.assertIs(window.board, board)
        self.assertEqual(len(window.ButtonList), 3)

    def test_mineclass_alias(self):
        self.assertIs(self.window.mineClass, self.window.board)

    def test_create_application_is_singleton(self):
        self.assertIs(create_application(), QApplication.instance())


class ClickTest(WindowTestCase):
    def test_left_click_starts_the_game(self):
        self.assertTrue(self.window.first_click)
        self.first_click()
        self.assertFalse(self.window.first_click)
        self.assertTrue(self.window.board.is_generated)
        self.assertTrue(self.window.Timer.isActive())
        self.assertTrue(any(text != "" for text in self.all_texts()))

    def test_right_click_cycles_flag_question_clear(self):
        self.first_click()
        button = self.find_covered_button()
        click(button, Qt.RightButton)
        self.assertEqual(button.text(), "★")
        click(button, Qt.RightButton)
        self.assertEqual(button.text(), "?")
        click(button, Qt.RightButton)
        self.assertEqual(button.text(), "")

    def test_right_click_before_first_click_is_ignored(self):
        button = self.window.ButtonList[0][0]
        click(button, Qt.RightButton)
        self.assertEqual(button.text(), "")
        self.assertTrue(self.window.first_click)

    def test_flagging_updates_mine_counter(self):
        self.first_click()
        button = self.find_covered_button()
        click(button, Qt.RightButton)
        self.assertEqual(int(self.window.lcd_number.value()), 9)

    def test_middle_click_flashes_when_numbers_do_not_match(self):
        """中键点在已展开格上、邻域标雷数与数字不符 -> 闪红叉。"""
        board = make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        window = self.make_window(board=board, config={"rows": 3, "cols": 3, "mines": 1})
        window.first_click = False
        button = window.ButtonList[1][1]
        click(button, Qt.MiddleButton)
        self.assertTrue(button.is_flashing)

    def test_left_right_same_press_sets_check_state(self):
        """旧版这个分支不受 isFinish 限制，这里锁定行为。"""
        self.first_click()
        window = self.window
        window.isFinish = True
        button = window.ButtonList[0][0]
        press(button, Qt.LeftButton, buttons=Qt.LeftButton | Qt.RightButton)
        self.assertTrue(window.checkState)
        self.assertIs(window.current_button, button)
        release(button, Qt.LeftButton)

    def test_middle_click_without_current_button_is_safe(self):
        """DEV-2：旧版在这里会 AttributeError。"""
        self.window.current_button = None
        self.window.on_middle_button_clicked(None)  # 不应抛异常

    def test_reveal_all_after_first_click(self):
        self.first_click()
        self.window.showall()
        self.assertTrue(self.window.isFinish)
        mines = sum(
            1 for row in self.window.board.mine_matrix for value in row if value == -1
        )
        shown = self.all_texts().count("⚡")
        self.assertEqual(shown, mines)

    def test_showall_before_first_click_does_nothing(self):
        self.window.showall()
        self.assertFalse(self.window.isFinish)


class BoardActionTest(WindowTestCase):
    def test_new_game_clears_everything(self):
        self.first_click()
        self.window.newstart()
        self.assertTrue(self.window.first_click)
        self.assertEqual(self.window.board.mine_matrix, [])
        self.assertTrue(all(text == "" for text in self.all_texts()))
        self.assertEqual(int(self.window.lcd_number.value()), 10)

    def test_reset_keeps_mine_field(self):
        self.first_click()
        before = [list(row) for row in self.window.board.mine_matrix]
        self.window.reset()
        self.assertEqual(self.window.board.mine_matrix, before)
        self.assertTrue(self.window.board.is_generated)
        self.assertTrue(self.window.isReset)
        self.assertFalse(self.window.first_click)
        self.assertTrue(all(text == "" for text in self.all_texts()))

    def test_fail_state_finishes_and_logs(self):
        self.first_click()
        self.window.GameState = Status.FAIL
        self.assertTrue(self.window.isFinish)
        self.assertFalse(self.window.Timer.isActive())
        with open(self.results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("9_9_10", data)
        self.assertEqual(data["9_9_10"][0]["state"], 0)

    def test_win_state_logs_success(self):
        self.first_click()
        self.window.GameState = Status.WIN
        with open(self.results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["9_9_10"][0]["state"], 1)

    def test_update_button_text(self):
        button = CustomButton()
        self.window.update_button_text(button, 3)
        self.assertEqual(button.text(), "3")
        self.assertEqual(button.styleSheet(), self.window.style_open)
        self.window.update_button_text(button, 0)
        self.assertEqual(button.text(), "")


class AutoCalculateTest(WindowTestCase):
    """自动计算只测"接线"，动作流用假的 AutoSolver 提供。"""

    config = {"rows": 4, "cols": 4, "mines": 1}

    def setUp(self):
        super().setUp()
        board = make_board(4, 4, [(3, 3)], opened_at=[(0, 0)])
        self.window.board = board
        self.window.first_click = False

    def _run(self, actions):
        class _FakeAutoSolver:
            def __init__(self, board):
                self.board = board

            def actions(self):
                return iter(actions)

        with mock.patch("minesweeper.ui.main_window.AutoSolver", _FakeAutoSolver):
            self.window.autoCalButton.setChecked(True)
            self.window.autocalculate(True)

    def test_open_action_is_applied(self):
        self._run([Action(ActionKind.OPEN, (1, 1))])
        self.assertEqual(
            self.window.ButtonList[1][1].styleSheet(), self.window.style_open
        )

    def test_flag_action_is_applied(self):
        self._run([Action(ActionKind.FLAG, (3, 3))])
        self.assertEqual(self.window.ButtonList[3][3].text(), "★")
        self.assertEqual(self.window.board.mark_matrix[3][3], Mark.FLAG)

    def test_generator_exhaustion_unchecks_button(self):
        # 只有一步动作：第二次 update_view 会 StopIteration -> 取消勾选
        self._run([Action(ActionKind.OPEN, (1, 1))])
        self.window.update_view()
        self.assertFalse(self.window.autoCalButton.isChecked())


class RestartTest(WindowTestCase):
    """改设置后要保存配置并重启（旧版指向不存在的 main.exe）。"""

    def setUp(self):
        super().setUp()
        self.popen = mock.patch("minesweeper.ui.main_window.subprocess.Popen")
        self.fake_popen = self.popen.start()
        self.addCleanup(self.popen.stop)

    def test_empty_settings_is_noop(self):
        self.window.reinitialize_game({})
        self.fake_popen.assert_not_called()
        self.assertFalse(os.path.exists(self.config_file))

    def test_settings_are_saved_and_program_restarts(self):
        self.window.reinitialize_game({"rows": 12, "cols": 18, "mines": 30})
        with open(self.config_file, "r", encoding="utf-8") as f:
            self.assertEqual(
                json.load(f), {"rows": 12, "cols": 18, "mines": 30}
            )
        self.fake_popen.assert_called_once()
        command = self.fake_popen.call_args[0][0]
        self.assertEqual(command[0], restart_command()[0])
        self.assertEqual(self.fake_popen.call_args[1]["cwd"], paths.APP_DIR)

    def test_restart_command_points_at_existing_launcher(self):
        command = restart_command()
        self.assertTrue(os.path.isfile(command[0]))


class SettingsDialogTest(unittest.TestCase):
    def setUp(self):
        self.dialog = SettingsDialog()
        self.addCleanup(self.dialog.deleteLater)

    def test_nothing_selected_returns_empty(self):
        self.assertEqual(self.dialog.get_settings(), {})

    def test_presets(self):
        self.dialog.beginner_radio.setChecked(True)
        self.assertEqual(self.dialog.get_settings(), BEGINNER)
        self.dialog.intermediate_radio.setChecked(True)
        self.assertEqual(self.dialog.get_settings(), INTERMEDIATE)
        self.dialog.advanced_radio.setChecked(True)
        self.assertEqual(self.dialog.get_settings(), ADVANCED)

    def test_custom(self):
        self.dialog.custom_radio.setChecked(True)
        self.dialog.height_spinbox.setValue(12)
        self.dialog.width_spinbox.setValue(20)
        self.dialog.mine_spinbox.setValue(40)
        self.assertEqual(
            self.dialog.get_settings(), {"rows": 12, "cols": 20, "mines": 40}
        )

    def test_preset_values(self):
        self.assertEqual(BEGINNER, {"rows": 9, "cols": 9, "mines": 10})
        self.assertEqual(INTERMEDIATE, {"rows": 16, "cols": 16, "mines": 40})
        self.assertEqual(ADVANCED, {"rows": 16, "cols": 30, "mines": 99})


class CustomButtonTest(unittest.TestCase):
    def test_flash_stops_after_four_ticks(self):
        button = CustomButton()
        self.addCleanup(button.deleteLater)
        button.start_flash()
        self.assertTrue(button.is_flashing)
        self.assertTrue(button.show_x)
        for _ in range(FLASH_TIMES):
            button.flash()
        self.assertFalse(button.is_flashing)
        self.assertFalse(button.show_x)
        self.assertEqual(button.flash_count, 0)

    def test_stop_flash_resets(self):
        button = CustomButton()
        self.addCleanup(button.deleteLater)
        button.start_flash()
        button.stop_flash()
        self.assertFalse(button.is_flashing)
        self.assertFalse(button.flash_timer.isActive())


if __name__ == "__main__":
    unittest.main()
