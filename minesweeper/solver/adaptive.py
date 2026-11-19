"""按需加深的猜测（复刻 Hill / JSMinesweeper 的 LARGE_ADAPTIVE_ANALYSIS）。

Hill 的原始做法：当"全盘深搜"因为预算被跳过或没算完、只能回退成单格猜测时，
枚举至多 4 万张一致雷图，用同一个便宜的续局策略给"原选点"和候选打分；只有当某个
候选取胜原选点至少 0.5 个百分点时，才启用最多 130 万节点的加深分析，并且**能证明**
候选更优时才改点。实测收益 +0.08 个百分点（1 万盘，95% 区间 −0.02 ~ +0.19）。

这里的 Python 版本沿用同样的"按需 + 必须证明"结构，但为了在 10 万盘量级跑得动，
把规模压到：未知格 ≤ ``CELL_LIMIT``、雷图 ≤ ``WORLD_LIMIT``、搜索节点 ≤ ``NODE_LIMIT``。
超出就直接放弃（返回 ``None``，调用方继续用原来那一手），这与 Hill"预算不足就不改点"
的语义一致。

雷图用"等权的自洽布局"（不再按空白格组合数加权），这正是 Hill 的口径；世界集合
用 Python 的大整数当位集，分区/计数都是 C 级位运算，单次分析通常在毫秒级。
"""

from typing import Dict, List, Optional, Sequence, Tuple

from ..core.enums import DIRECTIONS, MINE, Mark
from ..core.geometry import Position
from . import endgame
from . import frontier as frontier_module

#: 一张盘上最多同时考虑的未知格数量；超过就放弃加深。
CELL_LIMIT = 20
#: 最多枚举多少张等权雷图；超过就放弃加深。
WORLD_LIMIT = 256
#: 单次分析最多展开多少个搜索节点；超过视为"没证明"，不改点。
NODE_LIMIT = 400
#: 候选要赢过原选点多少（胜率绝对值）才值得改点——Hill 用的是 0.5 个百分点。
DEFAULT_MARGIN = 0.005
#: 观测值里表示"这格是雷"的哨兵（数字 0..8 之外）。
MINE_CLUE = 9


class _Budget(Exception):
    """展开节点超过预算：这不算"没收益"，只算"没证明"。"""


def _popcount(value: int) -> int:
    return bin(value).count("1")


def _clues(
    board, cells: Sequence[Position], worlds: Sequence[frozenset]
) -> Dict[Position, Tuple[int, ...]]:
    """每个候选格在每张雷图里"翻开会看到什么"（雷 = ``MINE_CLUE``）。"""
    rows, cols = board.rows, board.cols
    table: Dict[Position, List[int]] = {cell: [] for cell in cells}
    for world in worlds:
        for cell in cells:
            if cell in world:
                table[cell].append(MINE_CLUE)
                continue
            row, col = cell
            digits = 0
            for d_row, d_col in DIRECTIONS:
                near = row + d_row
                side = col + d_col
                if 0 <= near < rows and 0 <= side < cols and (near, side) in world:
                    digits += 1
            table[cell].append(digits)
    return {cell: tuple(values) for cell, values in table.items()}


class _Analysis:
    """在等权雷图上做期望最大搜索，带节点预算与位集加速。"""

    def __init__(self, cells: Sequence[Position], clues: Dict[Position, Tuple[int, ...]],
                 nodes: int) -> None:
        self.cells = list(cells)
        self.nodes = nodes
        self.used = 0
        self.memo: Dict[Tuple[int, int], float] = {}
        # ``digit_masks[i][d]`` = 在第 i 个候选格看到数字 d 的那些雷图（位集）。
        self.digit_masks: List[List[int]] = []
        for cell in self.cells:
            masks = [0] * MINE_CLUE
            for index, digit in enumerate(clues[cell]):
                if digit != MINE_CLUE:
                    masks[digit] |= 1 << index
            self.digit_masks.append(masks)

    def _count(self, mask: int) -> int:
        return _popcount(mask)

    def value(self, mask: int, remaining: int) -> float:
        """给定候选雷图集合与还没翻的格子，返回"从这里打到终局的胜率"。"""
        if self._count(mask) <= 1:
            return 1.0
        cached = self.memo.get((mask, remaining))
        if cached is not None:
            return cached
        self.used += 1
        if self.used > self.nodes:
            raise _Budget()

        total = self._count(mask)
        best = 0.0
        index = 0
        bits = remaining
        while bits:
            if bits & 1:
                masks = self.digit_masks[index]
                safe = 0
                for digit_mask in masks:
                    safe |= digit_mask
                if mask & safe == mask:
                    # 在所有候选雷图里都安全：开它必胜。
                    self.memo[(mask, remaining)] = 1.0
                    return 1.0
                score = 0.0
                for digit_mask in masks:
                    branch = mask & digit_mask
                    if not branch:
                        continue
                    hits = self._count(branch)
                    score += hits / total * self.value(branch, remaining & ~(1 << index))
                    if score + (total - hits) / total <= best:
                        break  # 上界已经追不上当前最优
                if score > best:
                    best = score
            bits >>= 1
            index += 1
        self.memo[(mask, remaining)] = best
        return best

    def expectation(self, mask: int, remaining: int, column: int) -> float:
        """固定先开 ``column`` 这一格时的期望胜率。"""
        masks = self.digit_masks[column]
        total = self._count(mask)
        score = 0.0
        for digit_mask in masks:
            branch = mask & digit_mask
            if not branch:
                continue
            score += self._count(branch) / total * self.value(
                branch, remaining & ~(1 << column)
            )
        return score


def choose_open_adaptive(
    board, table, system=None, margin: float = DEFAULT_MARGIN,
    worlds: int = WORLD_LIMIT, cells: int = CELL_LIMIT, nodes: int = NODE_LIMIT,
    log=None,
) -> Optional[Tuple[Position, float]]:
    """按需加深：只有在能证明候选比"最安全格"更好时才改点。

    返回 ``(position, value)`` 表示改点；返回 ``None`` 表示保持原选点（也包含所有
    "规模太大/没算完"的放弃情形）。
    """
    if not table:
        return None
    baseline, low = min(table.items(), key=lambda item: (item[1], item[0]))
    if low >= 1.0:
        return None  # 有确定安全格，用不着猜

    if system is None:
        system = frontier_module.build_system(board)
    unknown = list(system.unknown)
    if len(unknown) > cells:
        return None
    worlds_list = endgame._worlds(system, worlds)  # noqa: SLF001 - 复用组件的等权枚举
    if not worlds_list or len(worlds_list) > worlds:
        return None

    clues = _clues(board, unknown, worlds_list)
    # 只保留"翻开后观测不止一种"的格子——和 Hill 一样，观测唯一的格子没有信息量。
    useful = [cell for cell in unknown if len(set(clues[cell])) > 1]
    if len(useful) < 2:
        return None

    analysis = _Analysis(useful, {cell: clues[cell] for cell in useful}, nodes)
    full = (1 << len(worlds_list)) - 1
    remaining = (1 << len(useful)) - 1
    index = {cell: offset for offset, cell in enumerate(useful)}
    try:
        best_value = analysis.value(full, remaining)
        original = analysis.expectation(full, remaining, index[baseline]) \
            if baseline in index else 0.0
    except _Budget:
        if log is not None:
            log.debug("自适应加深超出预算，保持原选点")
        return None

    if best_value < original + margin or best_value >= 1.0:
        return None
    for cell in useful:
        if cell == baseline:
            continue
        try:
            score = analysis.expectation(full, remaining, index[cell])
        except _Budget:
            return None
        if score + 1e-12 >= best_value:
            if log is not None:
                log.info(
                    "自适应加深改点：%s（期望胜率 %.3f，原选点 %.3f）", cell, score, original
                )
            return cell, score
    return None
