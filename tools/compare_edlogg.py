"""用 EdLogg 的棋盘生成器造盘，让我们的求解器去解——同盘对照。

生成器来源：https://github.com/EdLogg/MineSweeper

* ``rand.cpp``：64 位 KISS 伪随机数，``RandomSeed(seed)`` 之后每次
  ``Random(n)`` 返回 ``((rand & 0xFFFFFFFF) * n) >> 32``；
* ``game.cpp::NewGame``：重复 ``y = Random(height)``、``x = Random(width)``，
  落在首点 3x3 里的重抽，已经在同一格则重抽，其余落雷；最后从首点连锁展开。

本文件里的 :class:`Kiss` 与编译出来的 ``rand.cpp`` **逐位一致**（seed 1 的
前 8 个 ``Random(16)`` 是 ``7 7 5 12 8 2 6 14``），:func:`edlogg_layouts`
也按"同一个随机流连续生成"的方式复刻了它的测试流程（一个 seed 跑 N 局）。

用法::

    python tools/compare_edlogg.py --seeds 1,2,3,4,5 --games 1000 --jobs 16
"""

import argparse
import multiprocessing
import os
import sys
import time
from typing import Dict, Iterator, List, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.solver import benchmark
from minesweeper.solver.engine import resolve_engine
from minesweeper.solver.strategy import SolverConfig

MASK = (1 << 64) - 1

#: EdLogg 在 ReadMe.txt 里公布的专家（30x16x99、首点 3,3、v1.1、10000 局）胜率
PUBLISHED = {
    1: 0.5337,
    2: 0.5400,
    3: 0.5548,
    4: 0.5349,
    5: 0.5475,
}


class Kiss(object):
    """``rand.cpp`` 里的 64 位 KISS 生成器。"""

    def __init__(self, seed: int) -> None:
        self.x = (seed | 1) & MASK
        self.c = (seed | 2) & MASK
        self.y = (seed | 4) & MASK
        self.z = (seed | 8) & MASK
        self.t = 0

    def next(self, n: int = 0) -> int:
        t = ((self.x << 58) + self.c) & MASK
        c = (self.x >> 6) & MASK
        x = (self.x + t) & MASK
        c = (c + (1 if x < t else 0)) & MASK

        y = self.y
        y = (y ^ ((y << 13) & MASK)) & MASK
        y = (y ^ (y >> 17)) & MASK
        y = (y ^ ((y << 43) & MASK)) & MASK

        z = (6906969069 * self.z + 1234567) & MASK

        self.x, self.c, self.y, self.z, self.t = x, c, y, z, t
        r = (x + y + z) & MASK
        if n == 0:
            return r
        return ((r & 0xFFFFFFFF) * n) >> 32


def edlogg_layouts(
    seed: int,
    rows: int,
    cols: int,
    mines: int,
    start: Tuple[int, int],
    count: int,
) -> Iterator[List[List[int]]]:
    """按 EdLogg 的 ``NewGame`` 连续生成 *count* 张雷图（1=雷）。

    一个 seed 只初始化一次随机流——它的测试菜单就是"设一个种子，连续跑 N 局"，
    所以第 2 局接着第 1 局用掉的那些随机数往下走。
    """

    rng = Kiss(seed)
    sy, sx = start
    for _ in range(count):
        grid = [[0] * cols for _ in range(rows)]
        for _ in range(mines):
            while True:
                y = rng.next(rows)
                x = rng.next(cols)
                if grid[y][x]:
                    continue
                if y < sy - 1 or y > sy + 1 or x < sx - 1 or x > sx + 1:
                    break
            grid[y][x] = 1
        yield grid


_ENGINE = None


def _worker_init() -> None:
    global _ENGINE
    _ENGINE = resolve_engine("auto")


def _play(task) -> Tuple[bool, int]:
    layout, start, rows, cols, mines, config = task
    outcome = benchmark.play_game(
        _ENGINE, rows, cols, mines, layout=layout, first=start, config=config
    )
    return outcome.won, outcome.steps


def play_seed(
    seed: int,
    games: int,
    rows: int,
    cols: int,
    mines: int,
    start: Tuple[int, int],
    jobs: int,
    config=None,
) -> Dict[str, object]:
    layouts = list(edlogg_layouts(seed, rows, cols, mines, start, games))
    tasks = [(layout, start, rows, cols, mines, config) for layout in layouts]

    started = time.time()
    if jobs > 1 and len(tasks) > 1:
        pool = multiprocessing.Pool(processes=jobs, initializer=_worker_init)
        try:
            results = list(pool.imap(_play, tasks, max(1, len(tasks) // (jobs * 4))))
        finally:
            pool.close()
            pool.join()
    else:
        _worker_init()
        results = [_play(task) for task in tasks]

    wins = sum(1 for won, _ in results if won)
    steps = sum(step for _, step in results)
    return {
        "seed": seed,
        "games": games,
        "wins": wins,
        "steps": steps,
        "elapsed": time.time() - started,
    }


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="在 EdLogg 的棋盘上测我们的求解器（同盘对照）"
    )
    parser.add_argument("--seeds", default="1,2,3,4,5", help="逗号分隔的种子")
    parser.add_argument("-n", "--games", type=int, default=1000, help="每个种子跑几局")
    parser.add_argument("--rows", type=int, default=16)
    parser.add_argument("--cols", type=int, default=30)
    parser.add_argument("--mines", type=int, default=99)
    parser.add_argument("--start", default="3,3", help="首点坐标 row,col")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--endgame-cells", type=int, default=None, help="端局求解的未知格上限"
    )
    parser.add_argument(
        "--endgame-worlds", type=int, default=None, help="端局求解的一致雷图上限"
    )
    parser.add_argument(
        "--endgame-nodes", type=int, default=None, help="端局求解的搜索节点上限"
    )
    parser.add_argument("--guess", default=None, help="猜法：min_prob/lookahead/progress/search")
    parser.add_argument("--guess-depth", type=int, default=None, help="搜索猜法的深度")
    args = parser.parse_args(argv)

    config = None
    if (
        args.endgame_cells is not None
        or args.endgame_worlds is not None
        or args.endgame_nodes is not None
    ):
        overrides = {}
        if args.endgame_cells is not None:
            overrides["endgame_cells"] = args.endgame_cells
        if args.endgame_worlds is not None:
            overrides["endgame_worlds"] = args.endgame_worlds
        if args.endgame_nodes is not None:
            overrides["endgame_nodes"] = args.endgame_nodes
        config = SolverConfig(**overrides)
    if args.guess is not None or args.guess_depth is not None:
        base = config or SolverConfig()
        kwargs = dict(
            guess_policy=args.guess or base.guess_policy,
            guess_depth=args.guess_depth or base.guess_depth,
        )
        config = SolverConfig(**kwargs) if config is None else \
            SolverConfig(**{**{field: getattr(config, field) for field in config.__dataclass_fields__}, **kwargs})

    seeds = [int(part) for part in args.seeds.split(",") if part.strip()]
    start = tuple(int(part) for part in args.start.split(","))

    total_wins = 0
    total_games = 0
    started = time.time()
    print(
        "EdLogg 棋盘 %dx%d / %d 雷，首点 %s，每种子 %d 局"
        % (args.rows, args.cols, args.mines, start, args.games)
    )
    for seed in seeds:
        result = play_seed(
            seed,
            args.games,
            args.rows,
            args.cols,
            args.mines,
            start,
            args.jobs,
            config,
        )
        wins = int(result["wins"])
        games = int(result["games"])
        total_wins += wins
        total_games += games
        published = PUBLISHED.get(seed)
        extra = (
            "   EdLogg 公布 %.2f%%" % (published * 100.0) if published else ""
        )
        print(
            "seed %-3d 我们 %4d/%-5d = %6.2f%%   平均 %6.1f 步  %5.1f s%s"
            % (
                seed,
                wins,
                games,
                100.0 * wins / games,
                result["steps"] / float(games),
                result["elapsed"],
                extra,
            )
        )

    if total_games:
        print(
            "合计 %d/%d = %.2f%%   %d 局共 %.1f s"
            % (
                total_wins,
                total_games,
                100.0 * total_wins / total_games,
                total_games,
                time.time() - started,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
