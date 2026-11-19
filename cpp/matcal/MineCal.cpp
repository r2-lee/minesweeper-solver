#include <vector>
#include <algorithm>
#include <unordered_set>
using namespace std;

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>  // 支持 STL 容器（如 vector）

namespace py = pybind11;

bool Local_Mat_Valid(
    const vector<int>& grid,
    int row, int col,
    const unordered_set<int>& strictPos // 严格验证坐标集合（一维索引）
);

std::pair<int, vector<pair<int, int>>>  Local_Mat_Cal(
    const vector<int>& matrix,
    int rows,
    int cols,
    int min_x,  // 最小选取数量
    int max_x,  // 最大选取数量
    const vector<int>& InnerPos // 严格验证坐标集合（一维索引）
);

bool Whole_Mat_Valid(
    const vector<int>& grid,
    int row, int col
);

std::pair<int, vector<pair<int, int>>>  Whole_Mat_Cal(
    const vector<int>& matrix,
    int rows,
    int cols,
    int x
);

// 封装为 Python 模块
PYBIND11_MODULE(Mat_Cal, m) {
    m.def("local_mat_valid", &Local_Mat_Valid,
        py::arg("grid"),
        py::arg("row"),
        py::arg("col"),
        py::arg("inner_pos"),
        "local Validate grid positions"
    );
    m.def("Local_Mat_Cal", &Local_Mat_Cal,
        py::arg("matrix"),
        py::arg("rows"),
        py::arg("cols"),
        py::arg("min_x"),
        py::arg("max_x"),
        py::arg("inner_pos"),
        "calcute matrix locally"
    );
    m.def("Whole_Mat_Valid", &Whole_Mat_Valid,
        py::arg("grid"),
        py::arg("row"),
        py::arg("col"),
        "global Validate grid positions"
    );
    m.def("Whole_Mat_Cal", &Whole_Mat_Cal,
        py::arg("grid"),
        py::arg("row"),
        py::arg("col"),
        py::arg("x"),
        "calcute matrix globally"
    );
}



bool Local_Mat_Valid(
    const vector<int>& grid,
    int row, int col,
    const unordered_set<int>& strictPos // 严格验证坐标集合（一维索引）
) {
    // 八邻域方向偏移量
    const vector<pair<int, int>> dirs = { {-1,-1}, {-1,0}, {-1,1},
                                        {0,-1},           {0,1},
                                        {1,-1},  {1,0},   {1,1} };

    for (int i = 0; i < row; ++i) {
        for (int j = 0; j < col; ++j) {
            int idx = i * col + j;
            int val = grid[idx];

            // 仅验证数字格 (1-8)
            if (val < 1 || val > 8) continue;

            // 统计周围：标雷(-1) + 未打开(0)
            int markedMines = 0, unopened = 0;
            for (const auto& dir : dirs) {
                int ni = i + dir.first, nj = j + dir.second;
                if (ni >= 0 && ni < row && nj >= 0 && nj < col) {
                    int neighborVal = grid[ni * col + nj];
                    if (neighborVal == -1) markedMines++;
                    else if (neighborVal == 0) unopened++;
                }
            }
            int actualMines = markedMines; // 实际确定雷数

            // 根据坐标类型选择验证逻辑
            if (strictPos.count(idx) && actualMines != val) return false;
            else if (actualMines > val) return false;
        }
    }
    return true;
}


std::pair<int, vector<pair<int, int>>>  Local_Mat_Cal(
    const vector<int>& matrix,
    int rows,
    int cols,
    int min_x,  // 最小选取数量
    int max_x,  // 最大选取数量
    const vector<int>& InnerPos // 严格验证坐标集合（一维索引）
) {
    int count = 0;
    unordered_set<int> strictPos(InnerPos.begin(), InnerPos.end());
    // 1. 获取所有0的位置索引
    vector<int> zeroPositions;
    for (int idx = 0; idx < rows * cols; ++idx)
        if (matrix[idx] == 0) zeroPositions.push_back(idx);
    int totalZeros = zeroPositions.size();
    vector<pair<int, int>> result(totalZeros);
    // 2. 边界检查
    if (totalZeros == 0 || min_x > max_x || max_x <= 0) return std::make_pair(-1, result);

    // 3. 遍历范围[min_x, max_x]
    for (int x = min_x; x <= min(max_x, totalZeros); ++x) { // 限制x不超过k
        vector<bool> selector(totalZeros, false);
        fill(selector.end() - x, selector.end(), true); // 后x位设为true

        do {
            vector<int> newMatrix = matrix; // 复制原矩阵
            for (int i = 0; i < totalZeros; ++i)
                if (selector[i]) newMatrix[zeroPositions[i]] = -1; // 修改选中位置
            // 3. 验证扫雷板规则
            if (Local_Mat_Valid(newMatrix, rows, cols, strictPos)) {
                count++;
                for (int ind = 0; ind < totalZeros; ind++) {
                    int index = zeroPositions[ind];
                    result[ind].first = index;
                    result[ind].second += newMatrix[index]; // 等价于累加-1
                }
            }
        } while (next_permutation(selector.begin(), selector.end()));
    }
    return std::make_pair(count, result);
}

bool Whole_Mat_Valid(
    const vector<int>& grid,
    int row, int col
) {
    // 八邻域方向偏移量
    const vector<pair<int, int>> dirs = { {-1,-1}, {-1,0}, {-1,1},
                                        {0,-1},           {0,1},
                                        {1,-1},  {1,0},   {1,1} };

    for (int i = 0; i < row; ++i) {
        for (int j = 0; j < col; ++j) {
            int idx = i * col + j;
            int val = grid[idx];

            // 仅验证数字格 (1-8)
            if (val < 1 || val > 8) continue;

            // 统计周围：标雷(-1) + 未打开(0)
            int markedMines = 0, unopened = 0;
            for (const auto& dir : dirs) {
                int ni = i + dir.first, nj = j + dir.second;
                if (ni >= 0 && ni < row && nj >= 0 && nj < col) {
                    int neighborVal = grid[static_cast<std::vector<int, std::allocator<int>>::size_type>(ni) * col + nj];
                    if (neighborVal == -1) markedMines++;
                    else if (neighborVal == 0) unopened++;
                }
            }
            if (markedMines != val) return false;
        }
    }
    return true;
}



std::pair<int, vector<pair<int, int>>> Whole_Mat_Cal(
    const vector<int>& matrix,
    int rows,
    int cols,
    int x
) {
    // 1. 检查指针有效性
    int count = 0;
    // 1. 获取所有0的位置索引
    vector<int> zeroPositions;
    for (int idx = 0; idx < rows * cols; ++idx)
        if (matrix[idx] == 0) zeroPositions.push_back(idx);
    int totalZeros = zeroPositions.size();
    vector<pair<int, int>> result(totalZeros);
    // 2. 边界检查
    if (totalZeros == 0 || x <= 0) return std::make_pair(-1, result);

    vector<bool> selector(totalZeros, false);
    fill(selector.end() - x, selector.end(), true); // 后x位设为true

    do {
        vector<int> newMatrix = matrix; // 复制原矩阵
        for (int i = 0; i < totalZeros; ++i)
            if (selector[i]) newMatrix[zeroPositions[i]] = -1; // 修改选中位置
        // 3. 验证扫雷板规则
        if (Whole_Mat_Valid(newMatrix, rows, cols)) {
            count++;
            for (int ind = 0; ind < totalZeros; ind++) {
                int index = zeroPositions[ind];
                result[ind].first = index;
                result[ind].second += newMatrix[index]; // 等价于累加-1
            }
        }
    } while (next_permutation(selector.begin(), selector.end()));
        return std::make_pair(count, result);
  }
