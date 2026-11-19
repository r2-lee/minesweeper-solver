#!/usr/bin/env bash
set -e
rm -rf ~/mine_adaptive
mkdir -p ~/mine_adaptive
tar -xzf ~/adaptive_deploy.tar.gz -C ~/mine_adaptive
cd ~/mine_adaptive
bash native/build_linux.sh >/dev/null 2>&1 || true
ls frontier_native*.so 2>/dev/null || echo NO_SO
python3 -c 'import sys; sys.path.insert(0,"."); import minesweeper.solver.accelerator as a; print("accelerator:", a.describe())'
