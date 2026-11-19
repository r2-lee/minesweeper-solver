#!/bin/bash
cd ~/minesweeper_ab || exit 1
[ -f /tmp/fn_backup.so ] && mv -f /tmp/fn_backup.so frontier_native.cpython-314-x86_64-linux-gnu.so
python3 -c 'import sys; sys.path.insert(0,"."); from minesweeper.solver import accelerator; print("accelerator:", accelerator.describe())'
for i in 1 2 3; do
  python3 tools/full_ab.py --games 3000 --jobs 16 --out /tmp/t_on.tsv --only endgame_off,superloc,gamble > /tmp/ron_$i.log 2>&1
  echo "round $i exit=$?"
done
