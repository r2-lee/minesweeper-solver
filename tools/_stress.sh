#!/bin/bash
# 压力测试：先关掉原生加速器跑，再打开跑，对比是否崩。
cd ~/minesweeper_ab || exit 1
MODE="$1"
SO=$(ls frontier_native*.so 2>/dev/null | head -1)
if [ "$MODE" = "off" ]; then
  [ -n "$SO" ] && mv "$SO" /tmp/fn_backup.so
else
  [ -f /tmp/fn_backup.so ] && mv /tmp/fn_backup.so "$SO"
fi
python3 -c 'import sys; sys.path.insert(0,"."); from minesweeper.solver import accelerator; print("accelerator:", accelerator.describe())'
for i in 1 2 3; do
  python3 tools/full_ab.py --games 3000 --jobs 16 --out /tmp/t_$MODE.tsv --only endgame_off,superloc,gamble >/tmp/r_$MODE_$i.log 2>&1
  echo "round $i exit=$?"
done
