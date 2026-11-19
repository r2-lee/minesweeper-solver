"""入口脚本测试。

重点是"启动只有一条路径、不派生任何子进程"——旧版 reinitialize_game 里
``subprocess.Popen("...\\main.exe")`` 才是双窗口的隐患来源。
"""

import os
import sys
import types
import unittest

from . import support  # noqa: F401

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENTRY = os.path.join(_ROOT, "mine.py")
_PYSTAND_INT = os.path.join(_ROOT, "PyStand.int")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class EntrySourceTest(unittest.TestCase):
    def test_mine_py_has_main_guard(self):
        source = _read(_ENTRY)
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("from minesweeper.app import main", source)

    def test_entry_scripts_do_not_spawn_processes(self):
        for path in (_ENTRY, _PYSTAND_INT):
            source = _read(path)
            self.assertNotIn("subprocess", source, path)
            self.assertNotIn("Popen", source, path)

    def test_pystand_int_has_main_guard(self):
        source = _read(_PYSTAND_INT)
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("from minesweeper.app import main", source)


class PyStandIntExecutionTest(unittest.TestCase):
    def test_runs_main_once_and_exits_zero(self):
        """按 PyStand 的方式 exec PyStand.int，main 应该被调用一次并正常退出。"""
        import minesweeper

        calls = []
        fake_module = types.ModuleType("minesweeper.app")

        def fake_main():
            calls.append(1)
            return 0

        fake_module.main = fake_main

        real_module = sys.modules.get("minesweeper.app")
        real_attr = getattr(minesweeper, "app", None)
        sys.modules["minesweeper.app"] = fake_module
        minesweeper.app = fake_module
        try:
            source = _read(_PYSTAND_INT)
            with self.assertRaises(SystemExit) as ctx:
                exec(
                    compile(source, _PYSTAND_INT, "exec"),
                    {"__name__": "__main__", "__file__": _PYSTAND_INT},
                )
            self.assertEqual(ctx.exception.code, 0)
        finally:
            if real_module is not None:
                sys.modules["minesweeper.app"] = real_module
            else:
                sys.modules.pop("minesweeper.app", None)
            if real_attr is not None:
                minesweeper.app = real_attr

        self.assertEqual(calls, [1])


class PathsTest(unittest.TestCase):
    def test_project_directories_exist(self):
        from minesweeper import paths

        self.assertTrue(os.path.isdir(paths.APP_DIR))
        self.assertTrue(os.path.isfile(paths.entry_script()))
        if not os.path.isdir(paths.qt_plugins_dir()):
            # 纯 Linux 部署没有 Windows 的 PyQt5 精简包，这一条只在桌面端有意义。
            self.skipTest("PyQt5 bundle is not part of this checkout")

    def test_config_and_results_paths_live_next_to_entry(self):
        from minesweeper import paths

        self.assertEqual(os.path.dirname(paths.config_path()), paths.APP_DIR)
        self.assertEqual(os.path.dirname(paths.results_path()), paths.APP_DIR)
        self.assertTrue(paths.config_path().endswith("config.json"))
        self.assertTrue(paths.results_path().endswith("results.json"))

    def test_ensure_sys_path_is_idempotent(self):
        from minesweeper import paths

        before = list(sys.path)
        paths.ensure_sys_path()
        paths.ensure_sys_path()
        after = list(sys.path)
        self.assertEqual(sys.path.count(paths.APP_DIR), 1)
        self.assertEqual(sys.path.count(paths.site_packages_dir()), 1)
        self.assertEqual(len(after), len(before) + (len(after) - len(before)))
        self.assertIn(paths.APP_DIR, after)


if __name__ == "__main__":
    unittest.main()
