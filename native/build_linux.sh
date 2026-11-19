#!/bin/sh
# Build the native accelerator for the Python that runs this script.
#
#   ./build_linux.sh            -> ../frontier_native<EXT_SUFFIX>
#   PYTHON=python3.14 ./build_linux.sh out/
set -e
PY=${PYTHON:-python3}
OUT=${1:-..}
cd "$(dirname "$0")"
INC=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['include'])")
EXT=$("$PY" -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")
mkdir -p "$OUT"
g++ -O2 -std=c++17 -shared -fPIC -I"$INC" frontier_native.cpp -o "$OUT/frontier_native$EXT"
echo "built $OUT/frontier_native$EXT"
