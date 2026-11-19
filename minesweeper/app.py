"""应用装配与启动入口。

把「创建 QApplication」「读取配置」「创建主窗口」「进入事件循环」拆成
可以单独调用的小函数，方便在测试里用 offscreen 平台做冒烟测试。
"""

from __future__ import annotations

import sys

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QApplication

from . import paths
from .core import storage
from .ui.main_window import MainWindow


def configure_qt_plugins() -> None:
    """把随程序发布的 Qt 插件目录加入搜索路径。

    旧版写的是相对路径 ``r".\\site-packages\\PyQt5\\Qt5\\plugins"``，只有在程序
    目录下启动才有效；这里改成绝对路径。
    """
    QCoreApplication.addLibraryPath(paths.qt_plugins_dir())


def create_application(argv=None) -> QApplication:
    """返回进程内唯一的 QApplication（重复调用不会新建第二个）。"""
    app = QApplication.instance()
    if app is None:
        arguments = list(argv) if argv is not None else list(sys.argv)
        app = QApplication(arguments)
    return app


def load_config() -> dict:
    """读取（必要时创建）配置文件。"""
    return storage.load_config(paths.config_path())


def create_window(config: dict = None, **kwargs) -> MainWindow:
    """创建主窗口；``config`` 省略时从 ``config.json`` 读取。"""
    if config is None:
        config = load_config()
    return MainWindow(config, **kwargs)


def main(argv=None) -> int:
    """程序主入口，返回进程退出码。"""
    paths.ensure_sys_path()
    configure_qt_plugins()
    app = create_application(argv)
    window = create_window()
    window.show()
    return app.exec_()
