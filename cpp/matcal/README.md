# Mat_Cal：旧窗口法用的原生模块

`MineCal.cpp` 是「窗口法」求解器的 C++ 实现（pybind11），导出四个函数：

| 函数 | 作用 |
|---|---|
| `Local_Mat_Cal(matrix, rows, cols, min_x, max_x, inner_pos)` | 在 `2k+1` 的局部窗口里枚举"恰好 k 颗雷"的全部合法布雷，返回计数与每格累计 |
| `Whole_Mat_Cal(grid, rows, cols, x)` | 全盘枚举，固定雷数 `x` |
| `local_mat_valid(grid, rows, cols, inner_pos)` | 局部窗口的约束校验（`inner_pos` 是 `unordered_set<int>`，接口只接受 `set`） |
| `Whole_Mat_Valid(grid, rows, cols)` | 全盘校验 |

## 它现在还需要吗

**不需要。** 当前的默认求解器是纯 Python 的精确边际（`minesweeper/solver/frontier.py`），
把边沿按连通性切成组件、枚举组件内全部合法布雷、再用剩余雷数做卷积，得到的是精确后验；
速度也更快（没有窗口法的重复枚举）。这个 `.pyd` 只服务于历史对照：

```bash
python tools/winrate.py --mode windows -n 600    # 旧窗口法，需要 Mat_Cal
python tools/winrate.py -n 1000                  # 默认精确边际，不需要 Mat_Cal
```

## 构建

```bash
pip install pybind11
# Linux / macOS
cmake -S cpp/matcal -B build/matcal -DCMAKE_BUILD_TYPE=Release
cmake --build build/matcal -j
# Windows（32 位 Python 就必须用 32 位工具链）
cmake -S cpp/matcal -B build/matcal -A Win32 -DCMAKE_BUILD_TYPE=Release
cmake --build build/matcal --config Release
```

产物是 `Mat_Cal.*.pyd`（Windows）或 `Mat_Cal.*.so`（Linux），放进 `site-packages/` 后
`import Mat_Cal` 即可。位数必须和解释器一致——32 位 Python 只能加载 32 位模块。

## 已知怪癖

- `local_mat_valid` 的 `inner_pos` 参数类型是 `unordered_set<int>`，必须传 `set`，传 `list` 会 `TypeError`；
  `Local_Mat_Cal` 的同名参数是 `vector<int>`，可以传 `list`。
- `result[i].first` 只在"出现过合法配置"时才被赋值，否则保持 `(0, 0)`。
- 计数是精确整数累加，但 `min_x < 0` 或 `max_x > 格子数` 时 C++ 侧会越界（UB）。
  这些行为记录在 `docs/KNOWN_ISSUES.md` 的 KI-1 ~ KI-3 里，Python 侧的修复是加守卫，而不是改 C++。
