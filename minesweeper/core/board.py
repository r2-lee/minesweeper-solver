"""扫雷棋盘状态（纯逻辑层）。

从旧版 mine.py 的 ``base_MineDetection`` 中拆出，只负责"棋盘状态 + 展开/标记规则"，
**不包含任何自动计算逻辑**（那部分在 ``minesweeper.solver`` 里），也不依赖 Qt。

与旧版的对应关系：

    旧属性            新属性
    ----------------  -----------------------------------------
    Height            rows
    Width             cols
    Num_Mine          mines
    mine_Matrix       mine_matrix      (-1 雷, 0~8 周围雷数, 未生成时为空列表)
    mark_Matrix       mark_matrix      (取值见 Mark)
    index_Matrix      已删除，展开时用局部 visited 集合代替（见 flood_open）

注意：``mine_matrix`` 在 ``gen_mine()`` 之前保持为空列表，与旧版行为一致。
"""

import random
from collections import deque
from typing import Deque, List, Optional, Set, Tuple

from .enums import MINE, Mark, Status
from .geometry import Position, neighbours, to_index


class Board:
    """一局扫雷的棋盘状态。"""

    def __init__(
        self,
        rows: int,
        cols: int,
        mines: int,
        rng: Optional[random.Random] = None,
    ) -> None:
        """创建棋盘。

        :param rows: 行数（旧版 Height）
        :param cols: 列数（旧版 Width）
        :param mines: 雷数（旧版 Num_Mine）
        :param rng: 随机源，默认使用 ``random`` 模块本身，
            因此 ``random.seed()`` 依然可以复现旧版行为；测试里可注入 ``random.Random(seed)``。
        """
        if rows <= 0 or cols <= 0:
            raise ValueError("rows/cols 必须为正整数")
        if mines < 0:
            raise ValueError("mines 不能为负数")

        self.rows = rows
        self.cols = cols
        self.mines = mines

        # 与旧版一致：布雷之前 mine_matrix 是空列表。
        self.mine_matrix: List[List[int]] = []
        self.mark_matrix: List[List[Mark]] = [
            [Mark.COVERED] * cols for _ in range(rows)
        ]

        self._rng = rng if rng is not None else random

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    @property
    def size(self) -> Tuple[int, int]:
        return self.rows, self.cols

    @property
    def is_generated(self) -> bool:
        """是否已经布雷（等价于首次点击之后）。"""
        return bool(self.mine_matrix)

    def count_flags(self) -> int:
        """已标记为雷的格子数。"""
        return sum(row.count(Mark.FLAG) for row in self.mark_matrix)

    def remain_mine(self) -> int:
        """剩余雷数 = 总雷数 - 已标记数（问号不计入）。"""
        return self.mines - self.count_flags()

    def get_round(self, x: int, y: int) -> List[Position]:
        """返回 (x, y) 八邻域中未越界的坐标（顺序同旧版 DIRECTIONS）。"""
        return list(neighbours((x, y), self.rows, self.cols))

    def adjacent_flags(self, x: int, y: int) -> int:
        """(x, y) 周围（不含自身）已标雷的格子数。"""
        return sum(
            1 for nx, ny in self.get_round(x, y) if self.mark_matrix[nx][ny] == Mark.FLAG
        )

    def adjacent_numbers(self, x: int, y: int) -> List[Position]:
        """(x, y) 八邻域中已展开的数字格。"""
        return [
            (nx, ny)
            for nx, ny in self.get_round(x, y)
            if self.mark_matrix[nx][ny] == Mark.OPENED and self.mine_matrix[nx][ny] > 0
        ]

    def is_won(self) -> bool:
        """是否胜利：未展开 + 已标记 的格子总数等于雷数。

        等价于"所有非雷格子都已展开"。

        用 ``list.count`` 而不是 Python 级循环：这个函数在自动计算里每走一步都要
        调一次（性能剖析里占 40% 的时间），逐行 count 走的是 C 层循环，比生成器
        快一个数量级。
        """
        closed = 0
        for row in self.mark_matrix:
            closed += row.count(Mark.COVERED) + row.count(Mark.FLAG)
        return closed == self.mines

    def random_position(self) -> Position:
        """随机取一个坐标（旧版 ramdomPos，拼写错误一并修正）。"""
        return (self._rng.randint(0, self.rows - 1), self._rng.randint(0, self.cols - 1))

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def gen_mine(self, first_click: Position) -> None:
        """生成雷区，保证首次点击的 3x3 区域为安全区。

        :param first_click: 首次点击坐标 (row, col)
        :raises ValueError: 雷数超过可用格子数
        """
        self.mine_matrix = [[0] * self.cols for _ in range(self.rows)]

        safe_zone = self._get_safe_zone(first_click)
        total_cells = self.rows * self.cols
        available_cells = total_cells - len(safe_zone)
        if self.mines > available_cells:
            raise ValueError(f"雷数过多！最大可布置数: {available_cells}")

        candidates = [i for i in range(total_cells) if i not in safe_zone]
        for flat in self._rng.sample(candidates, self.mines):
            self.mine_matrix[flat // self.cols][flat % self.cols] = MINE

        for r in range(self.rows):
            for c in range(self.cols):
                if self.mine_matrix[r][c] != MINE:
                    self.mine_matrix[r][c] = self._count_adjacent_mines(r, c)

    def new_game(self) -> None:
        """开新局：清空雷区，重置所有标记。"""
        self.mine_matrix = []
        self.mark_matrix = [[Mark.COVERED] * self.cols for _ in range(self.rows)]

    def reset(self) -> None:
        """重置本局：保留雷区，清空所有标记。"""
        self.mark_matrix = [[Mark.COVERED] * self.cols for _ in range(self.rows)]

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def expansion(self, x: int, y: int) -> Tuple[Status, List[Position]]:
        """展开 (x, y)。

        :return: (状态, 本次状态发生变化的坐标列表)
                 - 空白格：展开整片连通区域（受 flood_open 影响）
                 - 数字格：只展开自己
                 - 雷：返回 Status.FAIL，不改变标记
        """
        state = self.mine_matrix[x][y]
        status = Status.NORMAL
        positions: List[Position] = []

        if state == 0:
            positions = self.flood_open(x, y)
            for px, py in positions:
                self.mark_matrix[px][py] = Mark.OPENED
        elif state > 0:
            positions = [(x, y)]
            self.mark_matrix[x][y] = Mark.OPENED
        else:
            status = Status.FAIL

        # 旧版在 FAIL 之后同样会检查一次胜利条件，这里保持一致。
        if self.is_won():
            status = Status.WIN
        return status, positions

    def flood_open(self, x: int, y: int) -> List[Position]:
        """从 (x, y) 出发做广度优先展开，返回受影响的坐标。

        规则与旧版 ``get_current_spanPos`` 等价：空白格继续向八邻域扩散，
        数字格只被收集不再扩散；已展开的格子不再重复扩散。
        """
        visited: Set[Position] = set()
        ordered: List[Position] = []
        queue: Deque[Position] = deque([(x, y)])

        while queue:
            cx, cy = queue.popleft()
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            ordered.append((cx, cy))

            if self.mine_matrix[cx][cy] == 0 and self.mark_matrix[cx][cy] != Mark.OPENED:
                for neighbour in self.get_round(cx, cy):
                    if neighbour not in visited:
                        queue.append(neighbour)

        return ordered

    def mark_mine(self, x: int, y: int) -> Status:
        """把 (x, y) 标记为雷（自动计算使用，不做 0->1->2 循环）。"""
        self.mark_matrix[x][y] = Mark.FLAG
        return Status.WIN if self.is_won() else Status.NORMAL

    def cycle_flag(self, x: int, y: int) -> Tuple[Mark, Status]:
        """右键循环标记：未展开 -> 雷 -> 问号 -> 未展开。

        :return: (新标记, 状态)。只有"变成雷"这一跳才检查胜利条件，与旧版一致。
        """
        current = self.mark_matrix[x][y]

        if current == Mark.COVERED:
            self.mark_matrix[x][y] = Mark.FLAG
            return Mark.FLAG, (Status.WIN if self.is_won() else Status.NORMAL)
        if current == Mark.FLAG:
            self.mark_matrix[x][y] = Mark.QUESTION
            return Mark.QUESTION, Status.NORMAL
        if current == Mark.QUESTION:
            self.mark_matrix[x][y] = Mark.COVERED
            return Mark.COVERED, Status.NORMAL

        # 已展开的格子不响应标记。
        return Mark.OPENED, Status.NORMAL

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _get_safe_zone(self, first_click: Position) -> Set[int]:
        """首次点击的安全区（3x3，返回一维索引集合）。"""
        cells = [first_click]
        cells.extend(neighbours(first_click, self.rows, self.cols))
        return {to_index(cell, self.cols) for cell in cells}

    def _count_adjacent_mines(self, row: int, col: int) -> int:
        """(row, col) 八邻域中的雷数（要求 mine_matrix 已布好雷）。"""
        return sum(
            1
            for r, c in neighbours((row, col), self.rows, self.cols)
            if self.mine_matrix[r][c] == MINE
        )

    # ------------------------------------------------------------------
    # 调试辅助
    # ------------------------------------------------------------------
    def as_text(self, show_mines: bool = False) -> str:
        """把棋盘渲染成文本，供测试失败时排查使用。"""
        symbols = {-1: "X", 0: ".", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8"}
        lines = []
        for r in range(self.rows):
            cells = []
            for c in range(self.cols):
                mark = self.mark_matrix[r][c]
                if mark == Mark.OPENED:
                    cells.append(symbols.get(self.mine_matrix[r][c], "?"))
                elif mark == Mark.FLAG:
                    cells.append("F")
                elif mark == Mark.QUESTION:
                    cells.append("?")
                else:
                    cells.append("X" if show_mines and self.mine_matrix[r][c] == MINE else "#")
            lines.append("".join(cells))
        return "\n".join(lines)
