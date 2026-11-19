# 扫雷：一个可复现的求解器实验

[![tests](https://github.com/r2-lee/minesweeper-solver/actions/workflows/tests.yml/badge.svg)](https://github.com/r2-lee/minesweeper-solver/actions/workflows/tests.yml)

一个 Windows 扫雷游戏 + 一套分层求解器。界面用 PyQt5；核心逻辑（棋盘、约束求解、猜法策略）是纯 Python，
另有一个可选的 C++ 原生加速器（`native/`，CPython C API，无需 pybind11）。

仓库里还有**全部基准脚本与实测数据**：累计约 370 万局对局、480 格首点热力图、十几种猜法的配对 A/B。

三档胜率（默认配置，`tools/winrate.py` 可复现）：

| 难度 | 胜率 | 猜测/局 |
|---|---|---|
| 初级 9×9 / 10 雷 | **95.95%** | 0.14 |
| 中级 16×16 / 40 雷 | **86.95%** | 0.54 |
| 高级 16×30 / 99 雷 | **51.19%** | 2.65 |

求解器默认走**精确边际**：把边沿按连通性切成组件、枚举每个组件的全部合法布雷方案、再用剩余雷数做卷积，
得到全盘每个格子的"是雷概率"；并列候选按 Hill 式 `progress` 重排。早期版本（局部窗口法）在高级盘只有 42.5%。

作为参照系，我把两个公开实现也跑在同一批盘上：Hill 的 Java 求解器 **54.59%**、EdLogg 的 C++ 实现 **53.97%**。
这两套的代码不在本仓库，复现方式与对比数据见 `docs/zhihu/01-solver.md` 与 `docs/benchmarks/`。

## 里面有什么

| 路径 | 内容 |
|---|---|
| `minesweeper/` | 游戏与求解器：`core`（棋盘/配置/几何）、`solver`（精确边际、端局搜索、14 种猜法）、`ui`（PyQt5） |
| `native/` | 可选的原生加速器（枚举组件配置，单组件 15.7 s → 0.06 s），`build_linux.sh` / `build_windows.bat` |
| `cpp/matcal/` | 旧「窗口法」的 pybind11 模块源码（`Mat_Cal`），现在只用于历史对照，默认求解器不需要它 |
| `tests/` | 248 个单元测试（`python run_tests.py`） |
| `tools/` | 胜率基准、首点扫描、热力图、A/B 配对检验、EdLogg/Hill 对照脚本 |
| `docs/` | 两篇知乎文章（`zhihu/`）、算法日志（`ALGORITHM_LOG.md`）、已知问题（`KNOWN_ISSUES.md`）、胜率结构（`WINRATE_STRUCTURE.md`）、基准数据（`benchmarks/`） |

> 对照用的两个参考实现（Hill 的 `hill-worker.jar`、EdLogg 的 C++ 源码）**不在本仓库**，
> 它们只用来产出 `docs/benchmarks/` 里的对比数字；`tools/hill_ab.py` 通过 `--hill` 或
> 环境变量 `HILL_WORKER_DIR` 指向你本地的 jar 目录。

## 跑起来

Windows 打包版（`runtime/`、`site-packages/`、`mine.exe`）**不入库**——那些是预编译二进制。
在任意 Python 3.8+ 环境里：

```bash
pip install PyQt5            # 跑界面/界面测试才需要；没有它界面测试会自动跳过
python run_tests.py          # 248 个用例
python tools/winrate.py -n 1000 --jobs 8
python tools/winrate.py --rows 9 --cols 9 --mines 10 -n 5000 --jobs 8
```

精确边际是纯 Python，**不需要** `Mat_Cal.pyd`（那是旧窗口法用的原生模块）；装了 `native/` 的加速器会更快，没装也能跑。

---

## 附：Windows 打包版的用法

下面是仓库原本的 PyStand 打包版（32 位嵌入式 Python 3.8 + `Mat_Cal.pyd`）的用法，仅在你的目录里存在 `runtime/` 时有效：

```bat
:: 直接玩（PyStand 启动器）
mine.exe

:: 用嵌入式解释器跑源码
runtime\python.exe mine.py

:: 跑全部单元测试
runtime\python.exe run_tests.py
runtime\python.exe run_tests.py -v tests.test_solver

:: 测自动计算胜率（默认精确边际；--mode windows 是旧窗口法，用来做对照）
runtime\python.exe tools\winrate.py -n 100
runtime\python.exe tools\winrate.py --rows 9 --cols 9 --mines 10 -n 2000 --jobs 8
runtime\python.exe tools\winrate.py --mode windows --rows 16 --cols 30 --mines 99 -n 600
:: 同一批雷图上对比新旧算法
runtime\python.exe tools\winrate_legacy.py -n 100

:: Linux（精确模式是纯 Python，不需要 Mat_Cal.pyd）
python3 tools/winrate.py --rows 16 --cols 30 --mines 99 -n 1000 --jobs 16
```

> `mine.exe` 的脚本解析顺序是 `<exe名>.int` → `<exe名>.py` → `<exe名>.pyw`，
> 目录里没有 `mine.int`，所以它执行的是 **`mine.py`**。
> `PyStand.int` 是给 `<exe名>.int` 这条路径准备的等价入口，两者都只调用
> `minesweeper.app.main()`，**不派生任何子进程**（旧版 `reinitialize_game` 会去
> `Popen("main.exe")`，那才是"启动出两个窗口"的隐患）。

## 目录结构

```
mine.py                # 瘦入口：修好 sys.path 后调用 minesweeper.app.main()
PyStand.int            # PyStand 的等价入口（同样只调 main）
run_tests.py           # 测试入口（用 runtime\python.exe 跑）
config.json            # {"rows": 16, "cols": 16, "mines": 99}
results.json           # 历史战绩，按 "行_列_雷" 分组
minesweeper/
  paths.py             # 所有磁盘/插件路径（不再依赖 CWD）
  app.py               # QApplication、Qt 插件路径、窗口装配、main()
  core/
    enums.py           # Status / Mark / MINE / DIRECTIONS（八邻域顺序与旧版一致）
    geometry.py        # 坐标/一维下标换算、邻域遍历、矩阵形状与展平
    board.py           # Board：布雷、展开、标雷、胜负判定（纯逻辑，无 Qt）
    storage.py         # config.json / results.json 读写与校验
  solver/
    probability.py     # ProbabilityTable：概率表类型 + 跨表挑最小概率格
    engine.py          # Engine 接口 + NativeEngine(Mat_Cal) + ReferenceEngine(纯 Python 对照实现)
    frontier.py        # 精确边际：边沿约束 → 连通组件 → 枚举 → 按总雷数卷积
    window.py          # 棋盘 -> 局部窗口、边角裁剪、单格取值映射、雷数上下界
    local.py           # 局部概率（旧 autoCal_local）
    whole.py           # 全局概率（旧 autoCal_whole）
    strategy.py        # 自动计算状态机（旧 auto_calculate 生成器）
    benchmark.py       # 胜率测量（play_game / run），给 tools 和测试共用
    accelerator.py     # 原生枚举加速器的薄封装（没编译时自动退回纯 Python）
    errors.py          # SolverError
  ui/
    widgets.py         # CustomButton（闪红叉）
    dialogs.py         # SettingsDialog（初级/中级/高级/自定义）
    main_window.py     # 主窗口、事件分发、菜单、自动计算定时器
    styles.py          # 配色与数字颜色
tests/                 # unittest 用例 + support.py（手工布雷等测试工具）
native/                # frontier_native.cpp：组件枚举的 C++ 实现 + 两个平台构建脚本
tools/                 # 胜率工具、engine 对照探针、启动诊断脚本
docs/KNOWN_ISSUES.md   # 已修缺陷、保留的怪癖、胜率数据
backup/                # 重构前的 mine.py / PyStand.int 原始副本
```

## 分层与数据流

```
UI (ui/main_window.py)
  ├── 用户点击 -> Board.expansion / cycle_flag / mark_mine      (core/board.py)
  ├── 自动计算定时器 -> AutoSolver.actions() -> Action            (solver/strategy.py)
  │     ├── 精确模式（默认）-> FrontierSolver.probabilities()      (solver/frontier.py)
  │     └── 窗口模式（--mode windows）-> LocalSolver / WholeSolver
  └── 辅助计算按钮 -> LocalSolver.probabilities()                 (solver/local.py)
                        └── build_window()                        (solver/window.py)
                              └── Engine.local_cal()              (solver/engine.py)
                                    ├── NativeEngine -> Mat_Cal.pyd
                                    └── ReferenceEngine -> 纯 Python
```

关键约定：

* `core` 层不 import Qt，可以脱离界面单独测试；
* `solver` 层只依赖 `core` 的只读数据，不修改棋盘；
* 原生模块通过 `Engine` 接口注入，测试时可以换成 `ReferenceEngine`（与 C++ 逐行等价）；
* `ui` 层所有配置/战绩路径都从 `paths.py` 取，测试时注入临时目录。

## 内核结构（想改算法看这里）

求解器的数据流固定为五段，每段都能单独替换、单独测试：

```
棋盘 → build_system   → ConstraintSystem（每个已开数字格一条约束：邻域里还剩几颗雷）
     → 连通组件拆分   → 逐组件枚举全部合法布雷 → 按剩余雷数卷积
     → ProbabilityTable（每格的精确是雷概率）
     → AutoSolver.actions() → Action（展开 / 标雷）

--mode windows 时走旧路径：build_window → LocalSolver / WholeSolver → 概率
```

| 想改什么 | 改哪里 |
| --- | --- |
| 精确边际（组件拆分、枚举、卷积、预算） | `solver/frontier.py` |
| 窗口形状、雷数上下界 | `solver/window.py::build_window`（`LocalWindow.check()` 负责"能不能算"） |
| 概率怎么算 | 实现一个新的 `Engine` 子类（`solver/engine.py`），或加一个新的 solver |
| 什么时候升阶/切全局/猜 | `solver/strategy.py::AutoSolver._when_stuck`（阈值在 `SolverConfig`） |
| 猜哪一格 | `AutoSolver._guess` + `solver/probability.py::best_guess` |
| 胜负/展开规则 | `core/board.py` |
| 测一段算法是否变好 | `solver/benchmark.py::run`（同一 `seed` 雷图可复现，`--jobs` 并行） |

几个刻意设计成这样的小决定：

* `ProbabilityTable` 是 `dict` 子类——调用方可以当普通字典用，测试替身也能返回普通 `dict`；
* `EngineResult` 用 `NamedTuple`（`count`/`entries`/`usable`）——既能和旧版
  `(count, entries)` 元组直接比较，又给"这次算没算出来"起了名字（`count <= 0` 都不算）；
* `LocalWindow.check()` 返回"算不了的原因"字符串，而不是让 `LocalSolver` 里堆一排
  `return {}`——以后加约束只要在窗口上加一条；
* 精确边际有预算上限（`frontier.DEFAULT_BUDGET = 400_000` 个枚举节点），超了就
  `warning` 一句退回窗口法——既保证不会卡死，也保证老路径永远可用。
* `neighbours()` / `to_index()` / `to_position()` 收口了所有坐标换算，避免
  "按整盘列数取模"和"按窗口宽度取模"混用。

## 原生加速器（`native/`）

精确边际唯一的热点是组件枚举：纯 Python 约 5 µs/节点，遇到"整个边沿连成一大块"
的局面要 40 万~300 万节点（1.7~15.7 秒）。`native/frontier_native.cpp` 用同一套
算法重写了这一段（**只替换枚举**，约束建模、卷积、概率仍然在 Python 里），
计数用 128 位整数精确累加，所以结果与纯 Python **逐位相同**。

```sh
# Linux / macOS
native/build_linux.sh                      # 产物 frontier_native*.so 放在仓库根

# Windows（32 位嵌入式 Python，x86 Native Tools 命令行）
native\build_windows.bat                   # 产物 frontier_native.pyd 放在仓库根
```

没有编译产物时 `solver/accelerator.py` 自动退回纯 Python 实现，功能和胜率不受影响。
实测（同种子、2000 局高级）：

| | 纯 Python | 原生 | 
| --- | --- | --- |
| 最坏单组件（73 格 / 297 万节点） | 15.7 s | **0.06 s** |
| 2000 局基准（Linux，16 进程） | 48.1 s | **3.6 s** |
| 2000 局基准（Windows 32 位，16 进程） | 152.6 s | **26.0 s** |
| 单步求解 p95 / max | 12.9 ms / 139 ms | **3.1 ms / 4.4 ms** |
| 退回窗口法的次数 | 60 | **0** |
| 胜率 | 49.40% | 49.35%（同一批雷图，差 1 局，噪声范围内） |

装了原生模块后节点预算自动放宽到 `frontier.NATIVE_BUDGET = 20_000_000`，
所以实测 2000 局里一次都不会退回窗口法。

## 旧版对照表

| 旧 `mine.py` | 现在 |
| --- | --- |
| `L18 Status` | `core/enums.py` |
| `L23 base_MineDetection.__init__` 重载 | `core/board.py::Board(rows, cols, mines, rng=None)` |
| `L54 remain_mine` / `L57 get_round` / `L440 win_judge` | `core/board.py` 同名方法（`win_judge` → `is_won`） |
| `L66 gen_mine` / `L122 get_current_spanPos` | `core/board.py::gen_mine` / `flood_open` |
| `L356 get_CalMat` | `solver/window.py::build_window` + `cell_value` |
| `L389 trim_zero_edges` | `solver/window.py::trim_zero_edges` |
| `L142 autoCal_local` | `solver/local.py::LocalSolver` |
| `L178 autoCal_whole` | `solver/whole.py::WholeSolver` |
| `L279 auto_calculate` | `solver/strategy.py::AutoSolver.actions`（yield 两个列表 → `Action`） |
| `L487 SettingsDialog` | `ui/dialogs.py` |
| `L577 CustomButton` | `ui/widgets.py` |
| `L625 MainWindow` | `ui/main_window.py` |
| `L1252 read_config` | `core/storage.py::load_config` |
| `L1271-1276` 顶层启动代码 | `minesweeper/app.py::main` + `mine.py` 的 `__main__` 守卫 |

## 自动计算修复了什么

细化版（胜率构成、并列候选为什么值钱、14 次实验的总账）：[docs/WINRATE_STRUCTURE.md](docs/WINRATE_STRUCTURE.md)

旧版求解器会把"算不了"当成"必然安全"，于是一路踩雷。修掉的都记在
[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)；如果想看"这半年到底试过哪些算法改进、
每个分别赢多少"，看 [docs/ALGORITHM_LOG.md](docs/ALGORITHM_LOG.md) ——
14 种猜法/机制的完整 A/B 记录、对照 EdLogg 求解器的 5000 局同盘数据、以及为什么停在现在的实现。

* `count == -1` 被当成有效解（`abs(0 / -1) == 0`）→ 假"必然安全"，直接踩雷；
* `min_x` 为负时原样塞进 C++ 的 `fill(selector.end() - x, ...)` → 越界写内存；
* `Whole_Mat_Cal` 的雷数可能大于未开格数 → 同样的越界；
* 局部窗口的裁剪上界和判定上界不一致，贴着下/右边界的一行/列被整列漏算；
* 一维化时缺少 `i >= 0` / `j >= 0`，Python 负下标回绕会读到别的格；
* 局部窗口的雷数上界只看"八邻域完整落在窗口内"的数字格，边界数字格旁边的雷被漏算，
  于是枚举排除了真实布局，把真雷报成 0.0（高级局里的残余假确定性）。

另外顺手关掉了一处空转：相邻数字格会把同一批未开格各算一遍，旧版会重复展开
同一格（高级一局 900+ 个动作，实测 480 格根本用不了这么多）。现在按棋盘状态跳过，
动作数降到 241，胜率不变。

## 胜率

**最终版（默认配置：精确边际 + 原生加速器 + `progress` 猜法 + 端局精确搜索）**，
`seed=2026`、首点中心 `(3,3)`、`tools/final_bakeoff.py`：

| 难度 | 胜率 | 样本 | 平均步数 | 耗时 |
| --- | --- | --- | --- | --- |
| 初级 9x9 / 10 雷 | **95.95%** | 2,000 | 26.8 | 0.7 s |
| 中级 16x16 / 40 雷 | **86.95%** | 2,000 | 119.9 | 2.7 s |
| 高级 16x30 / 99 雷 | **51.19%** | 10,000 | 283.5 | 122 s |

同一批 10,000 张高级盘上其它猜法的成绩（`tools/final_bakeoff.py --only ...`）：

| 猜法 | 胜率 | 说明 |
| --- | --- | --- |
| `progress`（默认） | **51.19%** | Hill 的"同风险候选重排"，配对 McNemar +67 局、z=2.42 |
| `min_prob` | 50.52% | 只挑最安全的格 |
| `informed` | 50.52% | 精确条件计数（PERF-19），12 万局 +0.14 点 |
| `adaptive` | 50.51% | Codex 的 Hill 按需加深（PERF-18） |
| `deep` | 49.90% | 并列时挑未知邻格最多的 |
| `gametree` | 50.85%（n=2000） | 完整期望搜索，慢 15 倍 |

早期（窗口法）与历史对照：

| 难度 | 窗口法（`--mode windows`） | 精确边际（默认） |
| --- | --- | --- |
| 初级 9x9 / 10 雷 | 95.8%（n=2000） | **96.3%**（n=2000） |
| 中级 16x16 / 40 雷 | 85.4%（n=1000） | **87.3%**（n=4000） |
| 高级 16x30 / 99 雷 | 42.5%（n=600） | **49.4%**（n=2000；n=600 时 51.3%，属抽样噪声） |

* 缺陷修复前，同一批 100 张高级雷图上只有 33%（`tools\winrate_legacy.py`）；
* 初级已经贴着天花板：约 10% 的盘必须猜（其中约 6% 是精确 50/50），公开的"完美逻辑"
  基准是 96.2%（[MinesweeperHQ](https://minesweeperhq.com/minesweeper-odds/)）；
* 高级的差距主要在"还剩多少步必须靠猜"——精确边际把边沿之外、原先只能当空白处理的
  格子也纳入了总雷数约束，所以少猜几次就把胜率从 42.5% 抬到约 49%，已经接近公开的"完美逻辑 + 最安全格"基准 50.7%；
* **样本量很重要**：100–200 局的差异基本是噪声（初级 1000 局分块胜场在 92~98 之间浮动），
  比较两种算法至少 n≥1000；
* 剩下的失败几乎都是精确 50/50 或小范围多解，属于盘面本身不可解。
* 首点口径：上表用 `random`（随便点一格）。公开数据多用中心开局，加 `--first center`
  复测高级是 **50.7%**（n=1000），与 MinesweeperHQ 的 50.7%（10 万局）一致；
* 同盘对照（[EdLogg/MineSweeper](https://github.com/EdLogg/MineSweeper) 的生成器）：
  `tools/compare_edlogg.py` 把它的 64 位 KISS + `NewGame` 逐位搬过来（随机流与编译出来的
  `rand.cpp` 一致，见 `tests/test_edlogg.py`），用同一个种子造同样的棋盘，再让我们的求解器
  去解。专家档首点 `(3,3)`、每种子 1000 局：

  | seed | 我们 | EdLogg 公布 |
  | --- | --- | --- |
  | 1 | 48.90% | 53.37% |
  | 2 | 50.90% | 54.00% |
  | 3 | 53.00% | 55.48% |
  | 4 | 52.30% | 53.49% |
  | 5 | 51.30% | 54.75% |
  | 合计 | **51.28%**（5000 局） | 54.22% |

  棋盘完全一样，所以差的约 3 个点是**求解器**的差距，不是发牌。把端局门槛放宽到
  40 格 / 1024 雷图 / 4000 节点再测是 51.04%（2500 局）——不是端局预算的问题。

  速度方面我们比他慢得多（他约 4 ms/局，我们当时 144 ms/局，差 35 倍）。为此做过一轮
  纯性能优化（`is_won` 改逐行 `count`、`build_system` 内联八邻域、`comb` 记忆化、复用
  `board_values`）：单进程 400 局 58.1 s → 25.8 s，16 进程 2000 局 4.3 s → 2.8 s，
  **胜负逐局不变**（见 PERF-10）。
* 猜法：**默认 `--guess progress`**（在"最安全格 ±2 个百分点"的候选里按"翻牌结果加权的续局胜率"挑一格，
  这是 Hill 求解器"同风险候选重排"的等价实现；同盘 1 万局 51.19% vs `min_prob` 50.52%，配对 z=2.42）。
  其余十种都实现并实测过，只有它稳定超过基线：
  `--guess fewest`（按"打开后还要猜几次"排序，PERF-7）、`--guess lookahead`（一步前瞻，PERF-2）、
  `--guess progress`（JSMinesweeper 式"进度 + 两拍存活率"，PERF-4）、
  `--guess search`（边沿信念集合上的期望搜索，PERF-5）、
  `--guess rollout`（真的把棋下完再算胜率，PERF-6）、
`--guess gamble`（用 rollout 比较"最安全边沿格"与"最大空区的一次赌博"，PERF-12）、
  `--guess informed`（精确条件计数，PERF-19）、`--guess adaptive`（Hill 的按需加深，PERF-18）。
  细节见 `docs/KNOWN_ISSUES.md`。

## 测试

```
tests/test_board.py     棋盘逻辑：布雷安全区、展开、flood、标雷循环、胜负、重置
tests/test_geometry.py  坐标换算、邻域顺序、矩阵展平、概率表筛选与并列取点
tests/test_guess.py     猜测采样（无偏性）、候选排序、连锁模拟、前瞻/进度/少猜/超级位置猜法
tests/test_informed.py  精确条件计数：观测分布归一、条件系统、候选打分
tests/test_gametree.py   完整期望搜索：世界权重、期望值范围、预算放弃、空白区直跳
tests/test_storage.py   配置校验/回退、results.json 追加与紧凑格式
tests/test_solver.py    取值映射、窗口裁剪、局部/全局概率、原生模块与参考实现对照
tests/test_frontier.py  精确边际：与暴力枚举逐格对照、组件拆分、总雷数卷积、预算回退
tests/test_strategy.py  自动计算状态机：确定性动作、升阶、切全局、猜测、DEV-1
tests/test_winrate.py   "0/1 概率必须与真实雷图一致" + 固定种子的胜率下限
tests/test_endgame.py   端局精确求解：组件枚举与精确边际互证、雷图自洽、价值函数、门槛
tests/test_rollout.py   rollout 猜法：世界构造、模拟胜负、不做棋盘、候选带宽
tests/test_ui.py        offscreen 下的事件分发、菜单动作、自动计算接线、改设置重启、设置对话框
tests/test_entry.py     入口脚本只启动一次、不派生进程、路径工具
```

* 全部用标准库 `unittest`（嵌入式 Python 里没有 pytest）；
* UI 测试用 `QT_QPA_PLATFORM=offscreen`，不需要显示器；
* `NativeParityTest` 会在没有 `Mat_Cal.pyd` 的 64 位 Python 里自动 `skip`。

## 遗留文件

* `test.py`、`test2.py`：早期的 PyQt5 / 扫雷 demo，不被主程序引用，保留作参考。
* `backup/mine_original.py`：重构前的 1276 行单文件版本，用于行为对照
  （`tools/winrate_legacy.py` 直接 exec 它的前 486 行来跑旧算法）。
* `tools/engine_parity_probe.py`：随机矩阵下 `NativeEngine` 与 `ReferenceEngine` 的对照探针。
* `tools/_inspect_exe.py`、`tools/_list_windows.py`：排查启动链时用的诊断脚本。

## PyStand 启动器说明（原 README 摘要）

* `mine.exe` 会自动加载同级 `runtime\` 里的嵌入式 Python，以及同级 `site-packages\`；
* 按 exe 名找脚本：`mine.int` → `mine.py` → `mine.pyw`；都没有才会用 `PyStand.int`；
* 无 Console 窗口；在 `cmd.exe` 里运行可以看到 `print` 输出；
* 脚本里可以调用 `os.MessageBox(msg, title)` 弹提示框。


