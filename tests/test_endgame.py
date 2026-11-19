"""端局精确求解（:mod:`minesweeper.solver.endgame`）的测试。

端局求解把"所有与已知数字自洽的完整雷图"枚举出来（worlds），再在信念集合上做
期望最大化搜索，所以它的价值函数能直接回答"这一步最后能赢的概率是多少"。
测试分四类：

* 组件枚举与 ``frontier._enumerate_component`` 的结果必须互相对得上（同一个局面
  的合法配置数不能有两种答案）；
* ``_worlds`` 必须真的自洽：每张雷图的雷数、以及每个已开数字格的数字都要对得上；
* 价值函数在能人工推理的小局面上要给出正确的数字（例如 3x3 单雷局 = 7/8）；
* 超过门槛时返回 ``None``，让调用方安全地退回启发式。
"""

from __future__ import annotations

import itertools
import unittest

from minesweeper.core import Mark, Status
from minesweeper.solver import endgame
from minesweeper.solver.frontier import (
    Constraint,
    _enumerate_component,
    _split_components,
    build_system,
)
from minesweeper.solver.strategy import AutoSolver, SolverConfig

from . import support


def _configurations(cells, constraints, limit=100_000):
    """独立实现一遍组件枚举，作为 ``endgame`` 实现的预言机。"""

    index = {cell: position for position, cell in enumerate(cells)}
    touch = [[] for _ in cells]
    for number, constraint in enumerate(constraints):
        for position in constraint.positions:
            touch[index[position]].append(number)

    placed = [0] * len(constraints)
    undecided = [len(constraint.positions) for constraint in constraints]
    found = []

    def walk(depth, chosen):
        if depth == len(cells):
            if all(placed[i] == constraints[i].required for i in range(len(constraints))):
                found.append(frozenset(chosen))
            return True
        if len(found) > limit:
            return False
        cell = cells[depth]
        for mine in (False, True):
            for number in touch[depth]:
                undecided[number] -= 1
                placed[number] += mine
            possible = all(
                placed[n] <= constraints[n].required
                and placed[n] + undecided[n] >= constraints[n].required
                for n in touch[depth]
            )
            if possible and not walk(depth + 1, chosen + [cell] if mine else chosen):
                return False
            for number in touch[depth]:
                undecided[number] += 1
                placed[number] -= mine
        return True

    assert walk(0, [])
    return found


class ConfigurationTest(unittest.TestCase):
    """端局里的组件枚举必须和精确边际用到的枚举结果一致。"""

    def test_configurations_match_the_marginal_solver(self):
        for rows, cols, mine_at in [
            (3, 3, (0, 0)),
            (4, 4, (1, 2)),
            (5, 4, (4, 0)),
            (4, 5, (0, 4)),
        ]:
            with self.subTest(size=(rows, cols)):
                board = support.make_board(rows, cols, [mine_at], opened_at=[(2, 2)])
                system = build_system(board)
                for positions, group in _split_components(system.constraints):
                    component = _enumerate_component(positions, group, 200_000)
                    found = _configurations(positions, group)
                    self.assertEqual(len(found), component.configurations())
                    by_size = {}
                    for world in found:
                        by_size[len(world)] = by_size.get(len(world), 0) + 1
                    self.assertEqual(component.ways, by_size)


class WorldTest(unittest.TestCase):
    """``_worlds`` 生成的每张雷图都必须与已知信息自洽。"""

    def test_every_world_is_consistent(self):
        board = support.make_board(
            4, 4, [(0, 0), (3, 3)], opened_at=[(0, 1), (2, 1), (1, 2)]
        )
        system = build_system(board)
        worlds = endgame._worlds(system, 10_000)
        self.assertIsNotNone(worlds)
        self.assertTrue(worlds)
        for world in worlds:
            self.assertLessEqual(len(world), system.total_mines)
            for constraint in system.constraints:
                mines = sum(1 for position in constraint.positions if position in world)
                self.assertEqual(mines, constraint.required)

    def test_worlds_count_matches_the_combinatorics(self):
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        system = build_system(board)
        worlds = endgame._worlds(system, 10_000)
        self.assertEqual(len(worlds), 8)
        for world in worlds:
            self.assertEqual(len(world), 1)
            self.assertIn(world, [{cell} for cell in system.frontier])

    def test_missing_room_returns_none(self):
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        system = build_system(board)
        self.assertIsNone(endgame._worlds(system, 2))


class ValueTest(unittest.TestCase):
    """价值函数在能人工推理的局面里必须给出正确的概率。"""

    def test_three_by_three_single_mine_is_seven_eighths(self):
        # 3x3、单雷在 (0,0)、只开了中心（显示 1）：
        # 未知的 8 格里恰好 1 颗雷；开任意一格有 1/8 概率直接死，
        # 否则连锁展开铺满全盘、雷的位置立刻确定 → 胜率 7/8。
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        result = endgame.solve(board, cell_limit=20, world_limit=128, node_limit=2000)
        self.assertIsNotNone(result)
        position, value = result
        self.assertIn(position, board.get_round(1, 1) + [(2, 2)])
        self.assertAlmostEqual(value, 7.0 / 8.0, places=3)

    def test_known_layout_is_certain(self):
        # 只剩一颗雷、且已经被标出来：任何一格都安全，价值为 1。
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(2, 2)])
        board.mark_mine(0, 0)
        self.assertAlmostEqual(board.remain_mine(), 0)
        result = endgame.solve(board, cell_limit=20, world_limit=128, node_limit=2000)
        if result is not None:
            self.assertAlmostEqual(result[1], 1.0, places=6)

    def test_limits_reject_large_positions(self):
        board = support.make_board(6, 6, [(5, 5)], opened_at=[(0, 0)])
        self.assertIsNone(endgame.solve(board, cell_limit=4))
        self.assertIsNone(endgame.solve(board, world_limit=1))
        self.assertIsNone(endgame.solve(board, cell_limit=0, world_limit=0, node_limit=0))


class StrategyIntegrationTest(unittest.TestCase):
    """策略层要能安全地调用端局求解，并在关闭时完全跳过它。"""

    def _solver(self, board, **kwargs):
        return AutoSolver(board, config=SolverConfig(exact_marginals=True, **kwargs))

    def test_endgame_can_produce_a_move(self):
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        solver = self._solver(board)
        actions = list(itertools.islice(solver.actions(), 1))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind.value, "open")

    def test_endgame_off_still_works(self):
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        solver = self._solver(board, endgame=False)
        actions = list(itertools.islice(solver.actions(), 1))
        self.assertEqual(len(actions), 1)

    def test_solve_does_not_mutate_the_board(self):
        board = support.make_board(3, 3, [(0, 0)], opened_at=[(1, 1)])
        before = [row[:] for row in board.mark_matrix]
        endgame.solve(board, cell_limit=20, world_limit=128, node_limit=2000)
        self.assertEqual(board.mark_matrix, before)
        self.assertTrue(all(mark != Mark.OPENED or board.mine_matrix[r][c] >= 0
                            for r, row in enumerate(before) for c, mark in enumerate(row)))


if __name__ == "__main__":
    unittest.main()
