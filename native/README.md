# frontier_native

`minesweeper/solver/frontier.py` 里的组件枚举（`_enumerate_component`）是精确
边际求解器唯一的热点：纯 Python 约 **5 µs/节点**，遇到 40~300 万节点的大组件
要 2~16 秒。这个目录把它换成同一算法的 C++ 实现，**只替换这一段搜索**，
约束建模、总雷数卷积、概率计算仍然在 Python 里，所以结果逐位相同
（原生模块返回的是精确整数，不是浮点近似）。

## 实测（同种子，2000 局高级）

| | 纯 Python | 原生 |
| --- | --- | --- |
| 最坏单组件（73 格 / 约 297 万节点） | 15.7 s | **0.06 s** |
| 19 个已记录的退化现场合计 | 约 100 s | **0.38 s** |
| 2000 局基准（Linux，16 进程） | 48.1 s | **3.6 s** |
| 2000 局基准（Windows 32 位，16 进程） | 152.6 s | **26.0 s** |
| 单步求解 p95 / max | 12.9 ms / 139 ms | **3.1 ms / 4.4 ms** |
| 退回窗口法次数 | 60 | **0** |
| 胜率 | 49.40% | 49.35%（差 1 局，噪声） |

`frontier.default_budget()` 在检测到原生模块时会从 40 万节点放宽到 2000 万，
所以实测已经没有"组件过大退回窗口法"的情况（见 `docs/KNOWN_ISSUES.md` 的 KI-8）。

## 接口

```
enumerate_component(n_cells, positions_flat, offsets, required, limit)
    -> (ways, cell_ways, nodes) | None   # None = 超出节点预算
```

* `positions_flat`：所有约束的格编号（组件内局部编号）拼在一起
* `offsets`：长度 `len(required) + 1`，第 i 条约束占用
  `positions_flat[offsets[i]:offsets[i + 1]]`
* `required`：每条约束要求恰好几颗雷
* `ways[k]`：该组件恰好 k 颗雷的合法方案数
* `cell_ways[i * (n + 1) + k]`：其中第 i 格是雷的方案数
* 计数用 `unsigned __int128` 累加（组件最多 128 格，`C(n, k)` 放得下），
  再转成 Python 整数返回，因此“0/1 判定”与纯 Python 版完全一致

## 构建

### Linux / macOS

```sh
native/build_linux.sh                 # 产物：frontier_native.cpython-3xx-*.so（仓库根）
PYTHON=python3.14 native/build_linux.sh /tmp/out
```

### Windows（32 位嵌入式 Python 3.8）

在 “x86 Native Tools Command Prompt for VS 2022” 里：

```bat
native\build_windows.bat              :: 产物：frontier_native.pyd（仓库根）
```

脚本默认使用 `..\python\python38win32`（头文件/库）和 `runtime\python38.dll`，
路径不对时改脚本顶部的 `PYINC` / `PYLIB`。注意必须用 **x86** 工具链，
`Mat_Cal.pyd` 和 `runtime\python.exe` 都是 32 位的。

## 行为

* 模块不存在或导入失败时，`accelerator.available()` 返回 `False`，
  自动退回纯 Python 实现（Linux、没装编译器的机器、测试环境都安全）。
* `tests/test_frontier.py` 里的暴力枚举用例会同时覆盖两条路径：
  装了原生模块时，同一个断言既验证原生实现也验证 Python 参考实现。
* `tools/winrate.py -v` 的输出会打印当前用的是 `native` 还是 `python`。
