set -e
cd ~/mine_fc
bash native/build_linux.sh > /tmp/fc_build.log 2>&1 || { tail -20 /tmp/fc_build.log; exit 1; }
ls frontier_native*.so
python3 -c 'import sys; sys.path.insert(0, "."); import minesweeper; import minesweeper.solver.accelerator as a; print("version", minesweeper.__version__, "accelerator", a.describe())'
