cmake_minimum_required(VERSION 3.15)
project(matcal LANGUAGES CXX)

# Mat_Cal：旧「窗口法」求解器用的原生模块（pybind11）。
# 现在默认的精确边际求解器是纯 Python，不需要它；保留这里是为了可复现历史对照。
#
# 用 32 位 Python 时，请用 32 位工具链配置（Windows 上是 `-A Win32`，Linux 上是
# `-m32`），否则 Python 会报 "DLL load failed / wrong ELF class"。

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(Mat_Cal MineCal.cpp)

# 旧版本里这个模块名叫 Mat_Cal，被 `minesweeper/solver/engine.py` 以 `import Mat_Cal` 调用。
