"""自动计算胜率测量（命令行入口）。

本地（Windows 32 位 runtime，能用原生 ``Mat_Cal``）::

    runtime\\python.exe tools\\winrate.py -n 100 --seed 2026
    runtime\\python.exe tools\\winrate.py --rows 9 --cols 9 --mines 10 -n 1000

Linux / 任意 Python 3（没有 ``Mat_Cal`` 也能跑，用纯 Python 参考引擎）::

    python3 tools/winrate.py -n 500 --jobs 8
    python3 tools/winrate.py --mode windows -n 200 --jobs 4   # 旧窗口法，A/B 用

同一 ``--seed`` 下每一局的雷图都是确定的（见 ``benchmark.game_seeds``），
所以不同机器、不同实现之间可以直接对比。
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, "site-packages"), _ROOT):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

from minesweeper.solver.benchmark import format_summary, run  # noqa: E402
from minesweeper.solver.strategy import SolverConfig  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="自动计算胜率测量")
    parser.add_argument(
        "--first",
        choices=("random", "center"),
        default="random",
        help="首点方式：random=随机（默认），center=棋盘中心（与公开数据同口径）",
    )
    parser.add_argument("-n", "--games", type=int, default=20)
    parser.add_argument("--rows", type=int, default=16)
    parser.add_argument("--cols", type=int, default=30)
    parser.add_argument("--mines", type=int, default=99)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--mode",
        choices=("exact", "windows"),
        default="exact",
        help="exact=全盘精确边际（默认）, windows=旧的局部窗口启发式",
    )
    parser.add_argument(
        "--guess",
        choices=("adaptive", "blank", "coin", "deep", "fewest", "gamble", "gametree", "living", "pinned",
                 "informed", "lookahead",
                 "min_prob", "progress", "rollout", "search", "superloc"),
        default="progress",
        help="必须猜时的选格策略：min_prob=只挑雷概率最低的（默认）, fewest=少猜优先, "
        "gametree=复刻 EdLogg 的完整期望搜索, lookahead=一步前瞻, "
        "progress=两拍存活率, search=边沿信念集合期望搜索",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.0,
        help="前瞻猜法的概率容差（0=只比完全打平的格子）",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "native", "reference"),
        default="auto",
        help="auto=有 Mat_Cal 就用、没有就用纯 Python（默认）",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="并行进程数（每局互相独立）"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="逐局打印（默认只打印汇总）"
    )
    args = parser.parse_args(argv)

    config = SolverConfig(
        exact_marginals=(args.mode == "exact"),
        guess_policy=args.guess,
        guess_tolerance=args.tolerance,
    )
    result = run(
        rows=args.rows,
        cols=args.cols,
        mines=args.mines,
        games=args.games,
        seed=args.seed,
        config=config,
        engine_name=args.engine,
        jobs=args.jobs,
        first_click=args.first,
        progress=args.verbose,
    )
    print("-" * 46)
    print(format_summary(result))
    print(
        "模式: {mode}   引擎: {engine}   进程: {jobs}".format(
            mode=args.mode, engine=args.engine, jobs=result["jobs"]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

