"""组合穷举引擎：原生 ``Mat_Cal.pyd`` 的适配层 + 纯 Python 参考实现。

为什么要有这一层
----------------
旧版 ``mine.py`` 直接 ``import Mat_Cal`` 并在业务代码里到处调用，结果：

* 没有 pyd 就跑不了任何逻辑，也没法测试；
* 没人能验证"原生模块到底算出了什么"；
* 组合穷举这种数值细节和棋盘状态纠缠在一起。

现在把它收成一个最小接口 :class:`Engine`：

* :class:`NativeEngine` —— 生产环境的 pybind11 实现；
* :class:`ReferenceEngine` —— 与 ``MineCal.cpp`` 逐行等价的纯 Python 实现，
  既能在没有 pyd 时兜底，也是测试的预言机（两者逐值对照，见
  ``tests/test_solver.py::NativeParityTest``）。

矩阵约定（与 C++ 一致）
-----------------------
``matrix`` 是**行主序展平**的列表，长度 ``>= rows * cols``：

=====  ==========================================================
取值    含义
=====  ==========================================================
``0``   未知格，穷举时可能被假设成雷
``-1``  已确定/已标记的雷
``1..8``已展开的数字格
``-10`` 已展开的空白格（对校验函数透明：既不算雷也不算未知）
=====  ==========================================================

注意原生模块在**非法入参**下会越界写内存（C++ 未定义行为），
所以策略层必须先做范围检查；:class:`ReferenceEngine` 遇到这些入参会显式报错，
而不是像 C++ 那样"返回垃圾值"。相关 bug 见 ``docs/KNOWN_ISSUES.md`` 的 KI-1~KI-3。
"""

import itertools
from typing import Callable, Iterable, List, NamedTuple, Optional, Sequence, Tuple

#: 八邻域，顺序与 C++ 完全一致（顺序不影响结果，只影响阅读时的对照）
_CPP_DIRECTIONS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


class EngineResult(NamedTuple):
    """引擎的原始输出。

    ``count`` 是合法配置数：``-1`` 表示"算不了"（没有候选格 / 范围非法），
    ``0`` 表示"一个合法配置都没有"（约束自相矛盾）。两种都不能当成"有解"。

    ``entries`` 与矩阵里的未知格一一对应：``(一维下标, 被选中次数(负值))``。
    """

    count: int
    entries: List[Tuple[int, int]]

    @property
    def usable(self) -> bool:
        """是否算出了至少一个合法配置。"""
        return self.count > 0


class EngineUnavailable(ImportError):
    """原生模块不可用（通常是在 64 位 Python 里跑，或 pyd 不在 sys.path 上）。"""


def as_result(value) -> EngineResult:
    """把引擎返回值统一成 :class:`EngineResult`。

    原生模块和参考实现都返回 ``(count, entries)``；测试里的替身引擎有时只返回
    普通 tuple，这里顺手兼容一下，调用方就不用关心具体类型了。
    """
    if isinstance(value, EngineResult):
        return value
    count, entries = value
    return EngineResult(count, list(entries))


class Engine:
    """组合穷举引擎接口。

    实现者只需要回答两个问题："在所有可能布局里，哪些满足约束？"
    （:meth:`local_cal` / :meth:`whole_cal`），以及"这个布局合法吗？"
    （:meth:`local_mat_valid` / :meth:`whole_mat_valid`）。
    """

    #: 用于日志和测试输出
    name = "engine"

    def local_cal(
        self,
        matrix: Sequence[int],
        rows: int,
        cols: int,
        min_mines: int,
        max_mines: int,
        strict_positions: Sequence[int],
    ) -> EngineResult:
        """统计"雷数在 ``min_mines..max_mines`` 之间"的所有合法布局。

        ``strict_positions`` 里的数字格要求"已标雷数**恰好**等于数字"，
        其余的只要求"已标雷数不超过数字"（窗口边界上的数字格看不到全部邻域，
        只能做单侧约束）。
        """
        raise NotImplementedError

    def whole_cal(
        self, matrix: Sequence[int], rows: int, cols: int, mines: int
    ) -> EngineResult:
        """统计"恰好 ``mines`` 颗雷"的所有合法布局（每个数字格都要精确满足）。"""
        raise NotImplementedError

    def local_mat_valid(
        self, grid: Sequence[int], rows: int, cols: int, strict_positions: Iterable[int]
    ) -> bool:
        """局部校验：``strict_positions`` 内的数字格精确相等，其余只做上界检查。"""
        raise NotImplementedError

    def whole_mat_valid(self, grid: Sequence[int], rows: int, cols: int) -> bool:
        """全局校验：每个数字格都必须精确等于周围已标雷数。"""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<{}>".format(self.name)


# ----------------------------------------------------------------------
# 生产实现：Mat_Cal.pyd
# ----------------------------------------------------------------------
class NativeEngine(Engine):
    """把 ``Mat_Cal`` 这个 pybind11 模块包装成 :class:`Engine`。"""

    name = "native"

    def __init__(self, module: object) -> None:
        self._module = module

    def local_cal(
        self, matrix, rows, cols, min_mines, max_mines, strict_positions
    ) -> EngineResult:
        count, entries = self._module.Local_Mat_Cal(
            list(matrix), rows, cols, min_mines, max_mines, list(strict_positions)
        )
        return EngineResult(int(count), [(int(i), int(j)) for i, j in entries])

    def whole_cal(self, matrix, rows, cols, mines) -> EngineResult:
        count, entries = self._module.Whole_Mat_Cal(list(matrix), rows, cols, mines)
        return EngineResult(int(count), [(int(i), int(j)) for i, j in entries])

    def local_mat_valid(self, grid, rows, cols, strict_positions) -> bool:
        # C++ 侧的参数类型是 unordered_set<int>，pybind11 只接受 set（传 list 会 TypeError）。
        strict = {int(index) for index in strict_positions}
        return bool(self._module.local_mat_valid(list(grid), rows, cols, strict))

    def whole_mat_valid(self, grid, rows, cols) -> bool:
        return bool(self._module.Whole_Mat_Valid(list(grid), rows, cols))


# ----------------------------------------------------------------------
# 参考实现：与 C++ 源码逐行等价
# ----------------------------------------------------------------------
class ReferenceEngine(Engine):
    """纯 Python 组合穷举，行为对齐 ``MineCal.cpp``。

    复杂度与 C++ 相同（组合数指数级），只用于测试和小窗口，
    正式跑图请用 :class:`NativeEngine`。
    """

    name = "reference"

    # -- 校验 ----------------------------------------------------------
    def local_mat_valid(self, grid, rows, cols, strict_positions) -> bool:
        strict = (
            strict_positions
            if isinstance(strict_positions, (set, frozenset))
            else set(strict_positions)
        )
        return self._validate(grid, rows, cols, strict)

    def whole_mat_valid(self, grid, rows, cols) -> bool:
        # strict=None 表示"每个数字格都要精确相等"
        return self._validate(grid, rows, cols, None)

    def _validate(self, grid, rows, cols, strict: Optional[set]) -> bool:
        """统一的两个校验函数（C++ 里是两份几乎一样的循环）。

        :param strict: ``None`` -> 全局校验（精确相等）；
                       集合 -> 局部校验（集合内精确相等，其余只查上界）。
        """
        for row in range(rows):
            for col in range(cols):
                index = row * cols + col
                value = grid[index]
                if value < 1 or value > 8:
                    continue
                marked = self._count_marked_neighbours(grid, rows, cols, row, col)
                if strict is None:
                    if marked != value:
                        return False
                elif index in strict:
                    if marked != value:
                        return False
                elif marked > value:
                    return False
        return True

    @staticmethod
    def _count_marked_neighbours(grid, rows, cols, row: int, col: int) -> int:
        marked = 0
        for d_row, d_col in _CPP_DIRECTIONS:
            n_row, n_col = row + d_row, col + d_col
            if 0 <= n_row < rows and 0 <= n_col < cols:
                if grid[n_row * cols + n_col] == -1:
                    marked += 1
        return marked

    # -- 穷举 ----------------------------------------------------------
    def local_cal(
        self, matrix, rows, cols, min_mines, max_mines, strict_positions
    ) -> EngineResult:
        zeros = [index for index in range(rows * cols) if matrix[index] == 0]
        if not zeros or min_mines > max_mines or max_mines <= 0:
            return EngineResult(-1, [(0, 0)] * len(zeros))
        if min_mines < 0:
            # C++ 里 fill(selector.end() - min_x, ...) 在 min_x < 0 时越界写内存，
            # 属于未定义行为；这里拒绝执行，避免"看起来有结果"。
            raise ValueError(
                "min_mines 不能为负（原生模块在此处是未定义行为，见 KNOWN_ISSUES KI-2）"
            )

        strict = set(strict_positions)
        keys = range(min_mines, min(max_mines, len(zeros)) + 1)
        return self._search(
            matrix,
            rows,
            cols,
            keys,
            lambda grid: self._validate(grid, rows, cols, strict),
        )

    def whole_cal(self, matrix, rows, cols, mines) -> EngineResult:
        zeros = [index for index in range(rows * cols) if matrix[index] == 0]
        if not zeros or mines <= 0:
            return EngineResult(-1, [(0, 0)] * len(zeros))
        if mines > len(zeros):
            # C++ 同样没有防护（实测返回 (0, 全零)），这里按实测行为对齐：
            # 上层只会看到"算不了"，不会因为异常中断整局。
            return EngineResult(0, [(0, 0)] * len(zeros))
        return self._search(
            matrix,
            rows,
            cols,
            (mines,),
            lambda grid: self._validate(grid, rows, cols, None),
        )

    def _search(
        self,
        matrix: Sequence[int],
        rows: int,
        cols: int,
        mine_counts: Iterable[int],
        is_valid: Callable[[List[int]], bool],
    ) -> EngineResult:
        """在所有未知格里枚举"恰好 k 颗雷"的布局，统计每个格子被选中的次数。

        ``mine_counts`` 是允许的总雷数；对每个 k 枚举 ``C(n, k)`` 种组合。
        """
        zeros = [index for index in range(rows * cols) if matrix[index] == 0]
        hits = [0] * len(zeros)
        count = 0

        for k in mine_counts:
            for combo in itertools.combinations(range(len(zeros)), k):
                grid = list(matrix[: rows * cols])
                for position in combo:
                    grid[zeros[position]] = -1
                if is_valid(grid):
                    count += 1
                    for position in combo:
                        hits[position] += 1

        if count == 0:
            # 与 C++ 一致：没有合法配置时，下标字段保持初始化值 (0, 0)。
            return EngineResult(0, [(0, 0)] * len(zeros))
        return EngineResult(
            count, [(zeros[index], -hits[index]) for index in range(len(zeros))]
        )


# ----------------------------------------------------------------------
# 工厂
# ----------------------------------------------------------------------
def _import_native() -> object:
    """导入 ``Mat_Cal``（只有 32 位 runtime 环境里有）。"""
    try:
        import Mat_Cal  # type: ignore
    except ImportError as error:  # pragma: no cover - 依赖运行环境
        raise EngineUnavailable(
            "无法导入原生模块 Mat_Cal（{}）。请确认使用 runtime\\python.exe "
            "（32 位 Python 3.8）运行，并把 site-packages 加入 sys.path。".format(error)
        ) from error
    return Mat_Cal


def load_engine(module: Optional[object] = None) -> Engine:
    """返回可用的引擎；默认加载原生模块，失败时抛 :class:`EngineUnavailable`。

    :param module: 已导入的 ``Mat_Cal`` 模块（测试时可注入假模块）
    """
    if module is not None:
        return NativeEngine(module)
    return NativeEngine(_import_native())


def resolve_engine(name: str = "auto") -> Engine:
    """按名字创建引擎。

    ``native`` 强制用 ``Mat_Cal``（没有就抛 ``EngineUnavailable``），
    ``reference`` 用纯 Python 参考实现（Linux / 无原生模块时用），
    ``auto`` 优先原生、失败自动退回参考实现。
    """
    if name == "reference":
        return ReferenceEngine()
    if name == "native":
        return NativeEngine(_import_native())
    if name != "auto":
        raise ValueError("未知引擎: {!r}".format(name))
    try:
        return NativeEngine(_import_native())
    except EngineUnavailable:
        return ReferenceEngine()


def engine_class(name: str) -> type:
    """按名字取引擎类，方便测试参数化。"""
    engines = {"native": NativeEngine, "reference": ReferenceEngine}
    try:
        return engines[name]
    except KeyError:
        raise ValueError("未知引擎: {!r}".format(name))
