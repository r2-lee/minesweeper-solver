"""跑全部单元测试。

用法（必须用嵌入式运行时的 32 位解释器，才能真正验证 Mat_Cal 原生模块）::

    runtime\\python.exe run_tests.py
    runtime\\python.exe run_tests.py -v tests.test_solver      # 只跑某个模块

在系统 Python（64 位、没有 pyd）里也能跑，只是原生模块的对照测试会自动跳过。
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

for _path in (os.path.join(HERE, "site-packages"), HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# 没有显示器时用 offscreen 后端；已有配置则尊重用户设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    verbosity = 2 if ("-v" in argv or "--verbose" in argv) else 1
    argv = [arg for arg in argv if arg not in ("-v", "--verbose")]

    loader = unittest.TestLoader()
    if argv:
        suite = loader.loadTestsFromNames(argv)
    else:
        suite = loader.discover(os.path.join(HERE, "tests"), top_level_dir=HERE)

    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
