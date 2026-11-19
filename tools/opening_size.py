"""量化「首点位置 → 首点能翻开多大一片」——解释 (3,3) 为什么好。"""
import random, statistics, sys, os
sys.path.insert(0, os.path.abspath("."))
from minesweeper.core.board import Board

POS = [(0,0),(0,14),(1,1),(2,2),(3,3),(3,4),(4,3),(4,4),(4,5),(5,5),(8,15)]
RATE = {(0,0):48.57,(0,14):52.14,(1,1):51.89,(2,2):54.24,(3,3):54.57,(3,4):53.67,
        (4,3):53.92,(4,4):53.42,(4,5):53.26,(5,5):53.37,(8,15):53.38}
N = 4000
print("%-8s %8s %8s %8s %8s %8s %7s" % ("pos","open_mean","open_med","p>=20","p>=40","guesses_est","win%"))
rows = []
for row, col in POS:
    rng = random.Random(20261119)
    sizes = []
    for i in range(N):
        b = Board(16, 30, 99, rng=rng)
        b.gen_mine((row, col))
        status, opened = b.expansion(row, col)
        sizes.append(len(opened))
    mean = statistics.mean(sizes); med = statistics.median(sizes)
    p20 = sum(1 for s in sizes if s >= 20) / N
    p40 = sum(1 for s in sizes if s >= 40) / N
    print("%-8s %8.1f %8.0f %7.1f%% %7.1f%% %8s %6.2f" %
          ("(%d,%d)" % (row, col), mean, med, p20*100, p40*100, "-", RATE[(row,col)]))
    rows.append((row, col, mean, med, p20, RATE[(row,col)]))
print()
xs = [r[2] for r in rows]; ys = [r[5] for r in rows]
n = len(xs); mx = statistics.mean(xs); my = statistics.mean(ys)
cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
sx = statistics.pstdev(xs); sy = statistics.pstdev(ys)
print("corr(首点翻开格数, 胜率) = %.3f" % (cov/(sx*sy)))
