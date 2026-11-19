"""开发工具：对比 ``ReferenceEngine`` 与原生 ``Mat_Cal`` 的行为。

用途：确认纯 Python 参考实现（作为测试预言机）和 C++ 实现完全一致。
在 ``runtime\\python.exe`` 下运行::

    runtime\\python.exe tools\\engine_parity_probe.py [样本数]

注意：只生成"合法入参"（min_x >= 0, x <= 零点个数），
因为超出这个范围时 C++ 侧是未定义行为。
"""

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "site-packages")):
    if path not in sys.path:
        sys.path.insert(0, path)

from minesweeper.solver.engine import ReferenceEngine, load_engine  # noqa: E402


def random_matrix(rng, rows, cols):
    """生成一个形状合法的矩阵（随意填充，不要求是真实棋盘）。"""
    alphabet = [0, 0, 0, -1, 1, 2, 3, 5, -10, 4]
    return [rng.choice(alphabet) for _ in range(rows * cols)]


def main(samples=300):
    rng = random.Random(20240517)
    reference = ReferenceEngine()
    native = load_engine()

    mismatches = 0
    for case in range(samples):
        rows = rng.randint(2, 4)
        cols = rng.randint(2, 4)
        matrix = random_matrix(rng, rows, cols)
        zeros = [i for i, v in enumerate(matrix) if v == 0]
        if not zeros:
            continue

        min_x = rng.randint(0, min(3, len(zeros)))
        max_x = rng.randint(min_x, min(4, len(zeros) + 1))
        inner = sorted(rng.sample(zeros, rng.randint(0, min(3, len(zeros)))))

        got_native = native.local_cal(matrix, rows, cols, min_x, max_x, inner)
        got_reference = reference.local_cal(matrix, rows, cols, min_x, max_x, inner)
        if got_native != got_reference:
            mismatches += 1
            print("local_cal 不一致 case={} matrix={} rows={} cols={}".format(case, matrix, rows, cols))
            print("  min_x={} max_x={} inner={}".format(min_x, max_x, inner))
            print("  native   ={}".format(got_native))
            print("  reference={}".format(got_reference))

        x = rng.randint(1, len(zeros))
        got_native = native.whole_cal(matrix, rows, cols, x)
        got_reference = reference.whole_cal(matrix, rows, cols, x)
        if got_native != got_reference:
            mismatches += 1
            print("whole_cal 不一致 case={} matrix={} rows={} cols={} x={}".format(case, matrix, rows, cols, x))
            print("  native   ={}".format(got_native))
            print("  reference={}".format(got_reference))

        grid = random_matrix(rng, rows, cols)
        if native.local_mat_valid(grid, rows, cols, inner) != reference.local_mat_valid(grid, rows, cols, inner):
            mismatches += 1
            print("local_mat_valid 不一致 case={} grid={} inner={}".format(case, grid, inner))
        if native.whole_mat_valid(grid, rows, cols) != reference.whole_mat_valid(grid, rows, cols):
            mismatches += 1
            print("whole_mat_valid 不一致 case={} grid={}".format(case, grid))

    print("完成 {} 组样本，不一致 {} 处".format(samples, mismatches))
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
