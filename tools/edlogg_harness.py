"""Run the compiled EdLogg harness (ed.exe) over a seed chain.

Usage:  python tools/edlogg_harness.py <ed.exe> <count> <startSeed> [jobs]
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


def chain(exe, count, seed):
    out = subprocess.run([exe, "chain", str(count), str(seed)], capture_output=True, text=True, timeout=600)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def one(exe, seed):
    proc = subprocess.run([exe, "one", seed], capture_output=True, text=True, timeout=600)
    text = proc.stdout.strip()
    if not text:
        return seed, None, proc.returncode
    win, guesses, prob, layout = text.split(" ", 3)
    return seed, (int(win), int(guesses), float(prob), layout), proc.returncode


def main():
    exe, count, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    jobs = int(sys.argv[4]) if len(sys.argv) > 4 else 16

    seeds = chain(exe, count, seed)
    wins = 0
    faults = 0
    guesses = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for index, (seed_value, result, code) in enumerate(pool.map(lambda s: one(exe, s), seeds)):
            if result is None:
                faults += 1
                continue
            win, guess_count, prob, layout = result
            wins += win
            guesses += guess_count
            print(f"{index} {seed_value} {win} {guess_count} {prob:.6f} {layout}", flush=True)

    played = count - faults
    rate = wins / played * 100 if played else 0.0
    print(f"\ngames={count} played={played} faults={faults} wins={wins} rate={rate:.2f}% guesses/game={guesses / played if played else 0:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
