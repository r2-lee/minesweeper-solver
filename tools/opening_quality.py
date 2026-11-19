"""首点位置的「信息质量」度量：翻开面积、前沿数字个数、平均未知邻格、边上的数字、立即可推出数。"""
import random, statistics, sys, os
sys.path.insert(0, os.path.abspath("."))
from minesweeper.core.board import Board
from minesweeper.core.enums import DIRECTIONS, Mark

POS = [(0,0),(0,14),(1,1),(2,2),(3,3),(4,4),(4,5),(5,5),(8,15)]
RATE = {(0,0):48.57,(0,14):52.14,(1,1):51.89,(2,2):54.24,(3,3):54.57,
        (4,4):53.42,(4,5):53.26,(5,5):53.37,(8,15):53.38}
N = 3000
print("%-8s %7s %7s %8s %7s %7s %6s" % ("pos","open","front","unk/nbr","edge%%","forced","win%%"))
for row, col in POS:
    rng = random.Random(777)
    opens = []; fronts = []; unk = []; edges = []; forced = []
    for _ in range(N):
        b = Board(16, 30, 99, rng=rng)
        b.gen_mine((row, col))
        b.expansion(row, col)
        n_open = sum(1 for r in range(16) for c in range(30) if b.mark_matrix[r][c] == Mark.OPENED)
        f = 0; u_tot = 0; e = 0; fc = 0
        for r in range(16):
            for c in range(30):
                if b.mark_matrix[r][c] != Mark.OPENED or b.mine_matrix[r][c] <= 0:
                    continue
                nbrs = [(r + dr, c + dc) for dr, dc in DIRECTIONS
                        if 0 <= r + dr < 16 and 0 <= c + dc < 30]
                cov = [p for p in nbrs if b.mark_matrix[p[0]][p[1]] == Mark.COVERED]
                if not cov:
                    continue
                f += 1; u_tot += len(cov)
                if r in (0, 15) or c in (0, 29):
                    e += 1
                if len(cov) == b.mine_matrix[r][c]:
                    fc += 1
        opens.append(n_open); fronts.append(f); unk.append(u_tot / f if f else 0)
        edges.append(e / f if f else 0); forced.append(fc)
    print("%-8s %7.1f %7.1f %7.2f %6.1f%% %7.1f %6.2f" %
          ("(%d,%d)" % (row, col), statistics.mean(opens), statistics.mean(fronts),
           statistics.mean(unk), statistics.mean(edges) * 100, statistics.mean(forced),
           RATE[(row, col)]))
