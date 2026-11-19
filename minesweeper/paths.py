"""路径解析：数据文件与 Qt 插件目录一律按「程序目录」定位。

旧版 ``mine.py`` 用的是 ``'config.json'`` / ``'results.json'`` 这类相对路径，
只有当工作目录恰好是程序目录时才正确；从别处启动（快捷方式、命令行、
PyStand 的 ``mine.exe``）就可能读写到错误的位置。这里统一改成基于
``minesweeper`` 包所在目录来推导。
"""

from __future__ import annotations

import os
import sys

#: ``minesweeper`` 包目录
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
#: 程序目录（``minesweeper`` 的上一级，也就是 mine.exe 所在目录）
APP_DIR = os.path.dirname(PACKAGE_DIR)

CONFIG_NAME = "config.json"
RESULTS_NAME = "results.json"
SITE_PACKAGES_NAME = "site-packages"
ENTRY_SCRIPT_NAME = "mine.py"


def app_path(*parts: str) -> str:
    """返回程序目录下的路径。"""
    return os.path.join(APP_DIR, *parts)


def config_path() -> str:
    """返回 ``config.json`` 的绝对路径。"""
    return app_path(CONFIG_NAME)


def results_path() -> str:
    """返回 ``results.json`` 的绝对路径。"""
    return app_path(RESULTS_NAME)


def site_packages_dir() -> str:
    """返回随程序发布的 ``site-packages`` 目录。"""
    return app_path(SITE_PACKAGES_NAME)


def qt_plugins_dir() -> str:
    """返回 Qt 插件目录（platforms 等子目录的上一级）。"""
    return os.path.join(site_packages_dir(), "PyQt5", "Qt5", "plugins")


def entry_script() -> str:
    """返回可用于重启程序的入口脚本 ``mine.py``。"""
    return app_path(ENTRY_SCRIPT_NAME)


def ensure_sys_path() -> None:
    """把程序目录和 site-packages 放进 ``sys.path``（去重、保持幂等）。

    嵌入式 Python 的 ``python38._pth`` 只包含 ``python38.zip`` 和 ``runtime``，
    脚本所在目录不会自动可导入，因此入口处需要显式补上。
    """
    for directory in (site_packages_dir(), APP_DIR):
        if directory not in sys.path:
            sys.path.insert(0, directory)
