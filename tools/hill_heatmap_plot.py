"""Render the first-click win-rate heatmap from the sweep CSV."""
import argparse, csv, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ANCHORS = np.array([
    [0.192, 0.212, 0.584], [0.235, 0.318, 0.706], [0.251, 0.435, 0.800],
    [0.290, 0.549, 0.749], [0.408, 0.635, 0.639], [0.596, 0.698, 0.502],
    [0.796, 0.702, 0.376], [0.937, 0.639, 0.251], [0.980, 0.482, 0.180],
    [0.870, 0.290, 0.122],
])


def colormap(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0) * (len(ANCHORS) - 1)
    lo = np.floor(t).astype(int); hi = np.minimum(lo + 1, len(ANCHORS) - 1)
    frac = (t - lo)[..., None]
    return ((1 - frac) * ANCHORS[lo] + frac * ANCHORS[hi]) * 255.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="docs/benchmarks/hill-opening-heatmap.csv")
    ap.add_argument("--out", default="docs/benchmarks/hill-opening-heatmap.png")
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--smooth", type=int, default=0)
    ap.add_argument("--decimals", type=int, default=0)
    ap.add_argument("--label", default="高级 16×30/99")
    args = ap.parse_args()

    rows = max(int(r["row"]) for r in csv.DictReader(open(args.csv, encoding="utf-8"))) + 1
    cols = max(int(r["col"]) for r in csv.DictReader(open(args.csv, encoding="utf-8"))) + 1
    rate = np.full((rows, cols), np.nan)
    guesses = np.full((rows, cols), np.nan)
    with open(args.csv, encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            r, c = int(rec["row"]), int(rec["col"])
            rate[r, c] = float(rec["win_rate"])
            guesses[r, c] = float(rec["guesses_per_game"])
    if np.isnan(rate).any():
        print("incomplete csv: %d cells missing" % int(np.isnan(rate).sum())); return 1

    if args.smooth > 1:
        k = args.smooth // 2
        pad = np.pad(rate, k, mode="reflect")
        acc = np.zeros_like(rate)
        for dr in range(args.smooth):
            for dc in range(args.smooth):
                acc += pad[dr:dr + rows, dc:dc + cols]
        rate_raw = rate
        rate = acc / (args.smooth * args.smooth)

    lo, hi = float(rate.min()), float(rate.max())
    cell, pad_l, pad_t, bar_w = 34, 50, 96, 132
    width = pad_l + cols * cell + bar_w
    height = pad_t + rows * cell + 46
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    def font(size, bold=False):
        for name in ("msyhbd.ttc" if bold else "msyh.ttc", "simhei.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    title_font = font(17, bold=True)
    label_font = font(11)
    cell_font = font(10)
    small_font = font(10)

    colors = colormap((rate - lo) / max(hi - lo, 1e-9)).astype(np.uint8)
    for r in range(rows):
        for c in range(cols):
            x0 = pad_l + c * cell; y0 = pad_t + r * cell
            rgb = tuple(int(v) for v in colors[r, c])
            draw.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], fill=rgb)
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            fg = (255, 255, 255) if lum < 140 else (20, 20, 20)
            dec = 1 if (args.smooth > 1 or args.decimals) else 0
            text = ("%." + str(dec) + "f") % (rate[r, c] * 100)
            if args.smooth > 1 or args.decimals:
                fg = (255, 255, 255) if lum < 140 else (20, 20, 20)
            tw = draw.textlength(text, font=cell_font)
            draw.text((x0 + (cell - tw) / 2, y0 + cell / 2 - 6), text, font=cell_font, fill=fg)

    for c in range(cols):
        if c % 5 == 0 or c == cols - 1:
            draw.text((pad_l + c * cell + 4, pad_t - 15), str(c), font=label_font, fill=(40, 40, 40))
    for r in range(rows):
        if r % 4 == 0 or r == rows - 1:
            draw.text((10, pad_t + r * cell + 10), str(r), font=label_font, fill=(40, 40, 40))
    draw.text((pad_l, pad_t - 34), "列 col →", font=small_font, fill=(60, 60, 60))
    draw.text((6, pad_t - 34), "行 row ↓", font=small_font, fill=(60, 60, 60))

    bx = pad_l + cols * cell + 26
    by0, by1 = pad_t, pad_t + rows * cell
    grad = np.linspace(1.0, 0.0, by1 - by0)[:, None]
    gcols = colormap(grad).astype(np.uint8)
    for i in range(by1 - by0):
        rgb = tuple(int(v) for v in gcols[i, 0])
        draw.line([(bx, by0 + i), (bx + 18, by0 + i)], fill=rgb)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = int(by1 - frac * (by1 - by0))
        value = lo + frac * (hi - lo)
        draw.line([(bx + 18, y), (bx + 23, y)], fill=(60, 60, 60))
        draw.text((bx + 27, y - 6), "%.1f%%" % (value * 100), font=small_font, fill=(40, 40, 40))
    draw.text((bx, by0 - 20), "胜率", font=label_font, fill=(40, 40, 40))

    overall = float(rate.mean())
    draw.text((pad_l, 12), args.label + " · Hill 升级版 · 首点位置胜率", font=title_font, fill=(20, 20, 20))
    smooth_note = "" if args.smooth <= 1 else "；%d×%d 邻域平滑（每格有效 %d 局）" % (
        args.smooth, args.smooth, args.games * args.smooth * args.smooth)
    draw.text((pad_l, 38), "每格 %d 局，seed 2026，保护首点九宫格；总平均 %.2f%%，区间 %.1f%%–%.1f%%%s"
              % (args.games, overall * 100, lo * 100, hi * 100, smooth_note), font=label_font, fill=(70, 70, 70))

    img.save(args.out)
    print("saved", args.out, img.size, "min %.3f max %.3f mean %.3f" % (lo, hi, overall))
    return 0


if __name__ == "__main__":
    sys.exit(main())
