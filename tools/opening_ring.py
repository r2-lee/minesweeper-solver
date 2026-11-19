"""首点开出的区域是否"切断"了未开区（角上切开 vs 中间围成环）。"""
import random, statistics, sys, os
sys.path.insert(0, os.path.abspath("."))
from minesweeper.core.board import Board
from minesweeper.core.enums import Mark
POS = [(0,0),(0,14),(1,1),(2,2),(3,3),(4,4),(5,5),(8,15)]
RATE = {(0,0):48.57,(0,14):52.14,(1,1):51.89,(2,2):54.24,(3,3):54.57,(4,4):53.42,(5,5):53.37,(8,15):53.38}
N = 2000
print("%-8s %9s %9s %9s %9s %6s" % ("pos","touchTop","touchLeft","touch3+","ring%","win%"))
for row, col in POS:
    rng = random.Random(99)
    top = left = three = ring = 0
    for _ in range(N):
        b = Board(16, 30, 99, rng=rng)
        b.gen_mine((row, col)); b.expansion(row, col)
        opened = {(r, c) for r in range(16) for c in range(30) if b.mark_matrix[r][c] == Mark.OPENED}
        touches = sum([any(r == 0 for r, c in opened), any(r == 15 for r, c in opened),
                       any(c == 0 for r, c in opened), any(c == 29 for r, c in opened)])
        if touches == 0: ring += 1
        top += any(r == 0 for r, c in opened); left += any(c == 0 for r, c in opened)
        three += touches >= 3
    print("%-8s %8.1f%% %8.1f%% %8.1f%% %8.1f%% %6.2f" %
          ("(%d,%d)" % (row, col), 100*top/N, 100*left/N, 100*three/N, 100*ring/N, RATE[(row,col)]))
