#!/bin/bash
cd ~/minesweeper_ab || exit 1
pkill -f '[f]ull_ab.py'
sleep 1
[ -f ~/ab_results.tsv ] || printf 'name\tgames\twins\twin_rate\tsteps_per_game\telapsed_s\treasons\tconfig\n' > ~/ab_results.tsv
exec python3 tools/full_ab.py --games 20000 --jobs 16 --out ~/ab_results.tsv --only search_d2,lookahead,living,rollout_3,pinned,plan,fewest,progress,gametree,search_d3,endgame_wide