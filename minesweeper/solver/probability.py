"""概率表：求解器层唯一的"输出格式"。

约定只有一条：``(row, col) -> 这一格是雷的概率``，取值 0.0 ~ 1.0。

* ``0.0``：在**这张表所依据的约束内**逻辑必然安全；
* ``1.0``：逻辑必然是雷；
* 中间值：按"所有可能总雷数等权"统计出来的频率，属于启发式，
  只在没有 0/1 时用来挑"最不坏"的猜测（见 ``docs/KNOWN_ISSUES.md``）。

为什么直接用 ``dict`` 的子类而不是包一层：调用方本来就该能把它当普通字典用
（``table[(r, c)]``、``table.items()``、``== {}``），多出来的只是几个**有名字**的
操作。这样测试、界面、策略三边都不用关心类型。

这一层同时也是以后扩展"猜测价值评估"的落点：新算法只要产出同一种表，
上层策略不需要改。
"""

from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.geometry import Position
from .engine import EngineResult

#: 概率表的通用接口（用 Mapping 而不是 ProbabilityTable，方便测试注入假实现）
TableLike = Mapping[Position, float]


class ProbabilityTable(dict):
    """``{(row, col): 概率}``，附带常用的筛选方法。"""

    def __init__(self, values: Optional[Mapping[Position, float]] = None) -> None:
        super().__init__(values or {})

    # ------------------------------------------------------------------
    # 筛选
    # ------------------------------------------------------------------
    def safe(self) -> List[Position]:
        """概率为 0 的格子——可以放心展开。"""
        return [position for position, value in self.items() if value <= 0.0]

    def mines(self) -> List[Position]:
        """概率为 1 的格子——可以直接标雷。"""
        return [position for position, value in self.items() if value >= 1.0]

    def uncertain(self) -> List[Position]:
        """既不是 0 也不是 1 的格子——只能猜。"""
        return [
            position for position, value in self.items() if 0.0 < value < 1.0
        ]

    def best_guess(self) -> Optional[Tuple[Position, float]]:
        """概率最低的未确定格子，返回 ``(坐标, 概率)``；没有则返回 ``None``。"""
        return best_guess([self])

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------
    @classmethod
    def from_entries(
        cls,
        entries: Sequence[Tuple[int, int]],
        count: int,
        to_position,
    ) -> "ProbabilityTable":
        """把引擎的累加结果换算成概率。

        :param entries: ``[(一维下标, 被选中次数(负值))]``，即 ``EngineResult.entries``
        :param count: 合法配置总数，必须为正
        :param to_position: 一维下标 -> 绝对坐标的函数（局部窗口用 ``window.absolute``）
        """
        table = cls()
        if count <= 0:
            return table
        for index, accumulated in entries:
            table[to_position(index)] = abs(accumulated) / float(count)
        return table

    @classmethod
    def from_engine_result(cls, result: EngineResult, to_position) -> "ProbabilityTable":
        """引擎结果 -> 概率表；"算不了"（``count <= 0``）时返回空表。"""
        if not result.usable:
            return cls()
        return cls.from_entries(result.entries, result.count, to_position)

    # ------------------------------------------------------------------
    # 调试
    # ------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - 调试用
        body = ", ".join(
            "{}: {:.3f}".format(position, value)
            for position, value in sorted(self.items())
        )
        return "ProbabilityTable({{{}}})".format(body)


def best_guess(tables: Iterable[TableLike]) -> Optional[Tuple[Position, float]]:
    """在多张概率表里挑概率最低的未确定格子。

    并列时取**最后**出现的一个——旧版 ``if value <= min_prob`` 就是这个语义，
    保持它可以让改动前后的走子顺序完全一致（便于用胜率做回归）。
    """
    best: Optional[Tuple[Position, float]] = None
    for table in tables:
        for position, value in table.items():
            if value <= 0.0 or value >= 1.0:
                continue
            if best is None or value <= best[1]:
                best = (position, value)
    return best
