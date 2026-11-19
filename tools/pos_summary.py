"""汇总「首点位置 × Hill 升级版 × 10 万局」的结果，出表 + 出图。

用法：
    python tools/pos_summary.py                 # 用 docs/benchmarks/bigrun/*.csv
输出：
    docs/benchmarks/hill-opening-positions.csv
    docs/benchmarks/hill-opening-positions.png
"""
import argparse
import csv
import math
import os
import sys

NAMES = {
    "p0_0": (0, 0),
    "p0_14": (0, 14),
    "p1_1": (1, 1),
    "p2_2": (2, 2),
    "p3_3": (3, 3),
    "p3_4": (3, 4),
    "p4_3": (4, 3),
    "p4_4": (4, 4),
    "p4_5": (4, 5),
    "p5_5": (5, 5),
    "p8_15": (8, 15),
}


def load(path):
    wins = games = guesses = steps = 0.0
    for row in csv.DictReader(open(path, encoding="utf-8")):
        wins += int(row["wins"])
        games += int(row["games"])
        guesses += float(row["guesses_per_game"]) * int(row["games"])
        steps += float(row["steps_per_game"]) * int(row["games"])
    return wins, games, guesses / games, steps / games


def z_test(p1, n1, p2, n2):
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return (p1 - p2) / se if se else 0.0


def font(size, bold=False):
    from PIL import ImageFont
    for name in ("msyhbd.ttc" if bold else "msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_chart(rows, grid_rate, out):
    from PIL import Image, ImageDraw
    rows = sorted(rows, key=lambda r: r["rate"])
    cell_h, pad_t, pad_b, pad_l, pad_r = 34, 92, 46, 150, 96
    width = 1160
    height = pad_t + pad_b + cell_h * len(rows)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    tfont, lfont, sfont = font(17, True), font(12), font(11)

    lo = math.floor(min(r["rate"] for r in rows) * 1000) / 10.0 - 0.6
    hi = math.ceil(max(r["rate"] for r in rows) * 1000) / 10.0 + 0.6
    span = hi - lo
    x_of = lambda rate: pad_l + (rate * 100 - lo) / span * (width - pad_l - pad_r)

    draw.text((pad_l, 16), "高级 16×30/99 · Hill 升级版 · 首点位置 × 10 万局", font=tfont, fill=(20, 20, 20))
    draw.text((pad_l, 44), "误差棒 = 95%% 置信区间（±1.96σ）；竖虚线 = 全盘网格均值 {:.2f}%%".format(grid_rate * 100),
              font=sfont, fill=(90, 90, 90))

    for rate in range(int(math.ceil(lo)), int(lo + span) + 1):
        x = x_of(rate / 100.0)
        if pad_l <= x <= width - pad_r:
            draw.line((x, pad_t - 6, x, height - pad_b + 6), fill=(232, 232, 232), width=1)
            draw.text((x - 8, pad_t - 24), "{}%%".format(rate), font=sfont, fill=(120, 120, 120))

    gx = x_of(grid_rate)
    for y in range(pad_t, height - pad_b, 8):
        draw.line((gx, y, gx, y + 4), fill=(120, 120, 120), width=2)

    for i, row in enumerate(rows):
        y0 = pad_t + i * cell_h
        cy = y0 + cell_h // 2
        rate, half = row["rate"], row["ci"]
        draw.text((12, cy - 8), "(%d,%d)" % row["pos"], font=lfont, fill=(30, 30, 30))
        draw.text((70, cy - 8), "{} 局".format(row["games"]), font=sfont, fill=(120, 120, 120))
        x0, x1 = x_of(rate - half), x_of(rate + half)
        lum = int(max(0, min(255, 255 - (rate - 0.48) / 0.09 * 255)))
        color = (30 + lum // 3, 120, 220 - lum // 4)
        draw.rectangle((pad_l, cy - 9, x_of(rate), cy + 9), fill=color)
        draw.line((x0, cy, x1, cy), fill=(60, 60, 60), width=1)
        draw.line((x0, cy - 5, x0, cy + 5), fill=(60, 60, 60), width=1)
        draw.line((x1, cy - 5, x1, cy + 5), fill=(60, 60, 60), width=1)
        draw.text((x1 + 10, cy - 8), "{:.2f}%%  (z={:+.1f})".format(rate * 100, row["z"]), font=lfont,
                  fill=(30, 30, 30))

    draw.text((12, height - 30), "z 相对中心 (8,15)；|z|>2.8 才在 10 次比较的多重检验下视作显著",
              font=sfont, fill=(90, 90, 90))
    img.save(out)
    print("saved %s (%dx%d)" % (out, width, height))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="docs/benchmarks/bigrun")
    ap.add_argument("--out-csv", default="docs/benchmarks/hill-opening-positions.csv")
    ap.add_argument("--out-png", default="docs/benchmarks/hill-opening-positions.png")
    args = ap.parse_args()

    grid_path = os.path.join(args.dir, "grid10000.csv")
    _, grid_games, _, _ = load(grid_path)
    grid_wins = sum(int(r["wins"]) for r in csv.DictReader(open(grid_path, encoding="utf-8")))
    grid_rate = grid_wins / grid_games

    rows = []
    for name, pos in NAMES.items():
        path = os.path.join(args.dir, name + ".csv")
        if not os.path.exists(path):
            print("missing %s" % path, file=sys.stderr)
            continue
        wins, games, guesses, steps = load(path)
        rate = wins / games
        rows.append({"name": name, "pos": pos, "wins": wins, "games": games, "rate": rate,
                     "ci": 1.96 * math.sqrt(rate * (1 - rate) / games),
                     "guesses": guesses, "steps": steps})

    center = next(r for r in rows if r["pos"] == (8, 15))
    for r in rows:
        r["z"] = z_test(r["rate"], r["games"], center["rate"], center["games"])

    rows.sort(key=lambda r: -r["rate"])
    print("%-8s %-8s %9s %10s %8s %9s %7s %5s" %
          ("pos", "games", "wins", "rate", "95%CI", "guesses", "steps", "z"))
    for r in rows:
        print("%-8s %-8d %9d %9.3f%% %7.2fpp %9.3f %7.2f %+5.1f" %
              ("(%d,%d)" % r["pos"], r["games"], r["wins"], r["rate"] * 100, r["ci"] * 100,
               r["guesses"], r["steps"], r["z"]))
    print("grid   %-8d %9d %9.3f%%" % (grid_games, grid_wins, grid_rate * 100))

    with open(args.out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["row", "col", "games", "wins", "win_rate", "ci95_pp",
                         "guesses_per_game", "steps_per_game", "z_vs_center"])
        for r in rows:
            writer.writerow([r["pos"][0], r["pos"][1], r["games"], r["wins"],
                             round(r["rate"], 5), round(r["ci"] * 100, 2),
                             round(r["guesses"], 3), round(r["steps"], 2), round(r["z"], 2)])
    print("saved %s" % args.out_csv)
    draw_chart(rows, grid_rate, args.out_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
