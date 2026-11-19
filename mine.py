"""扫雷 —— 程序入口。

真正的实现都在 ``minesweeper`` 包里，这个文件只负责三件事：

1. 把程序目录和 ``site-packages`` 放进 ``sys.path``（嵌入式 Python 的
   ``python38._pth`` 只包含 ``python38.zip`` 和 ``runtime``，脚本目录不会自动可导入）；
2. 交给 :func:`minesweeper.app.main` 装配 Qt 插件路径、读取配置、创建窗口；
3. 进入事件循环。

PyStand 的 ``mine.exe`` 会执行同目录下的 ``mine.py``，因此这里**不要**再
派生任何子进程，否则会出现两个游戏窗口。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (os.path.join(_HERE, "site-packages"), _HERE):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.app import main  # noqa: E402  (必须在 sys.path 调整之后导入)

if __name__ == "__main__":
    sys.exit(main())
