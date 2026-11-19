import random
import Mat_Cal 
class MineSweeper:
    def __init__(self, width=10, height=10, num_mines=15):
        """
        初始化扫雷游戏
        :param width: 雷区宽度 (默认10)
        :param height: 雷区高度 (默认10)
        :param num_mines: 地雷数量 (默认15)
        """
        self.width = width
        self.height = height
        self.num_mines = num_mines
        self.game_over = False  # 游戏状态标志
        self.mine_Matrix = []  # 雷区矩阵（-1=雷, 0-8=周围雷数）
        self.mark_Matrix = [[0] * width for _ in range(height)]  # 标记矩阵（0=未打开, 1=标记雷, 2=标记问号, 10=已打开）
        
    def gen_mine(self, first_click):
        """
        生成扫雷矩阵，确保首次点击位置为0（周围无雷）
        :param first_click: 首次点击坐标元组(row, col)
        """
        # 1. 初始化全0矩阵
        self.mine_Matrix = [[0] * self.width for _ in range(self.height)]
        total_cells = self.width * self.height
        
        # 2. 计算安全区域（首次点击+周围8格）
        safe_zone = self._get_safe_zone(first_click)
        
        # 3. 检查雷数是否超过可用位置
        available_cells = total_cells - len(safe_zone)
        if self.num_mines > available_cells:
            raise ValueError(f"雷数过多！最大可布置数: {available_cells}")
        
        # 4. 生成布雷候选位置（排除安全区）
        all_positions = [i for i in range(total_cells) if i not in safe_zone]
        mine_positions = random.sample(all_positions, self.num_mines)
        
        # 5. 布置地雷
        for pos in mine_positions:
            row = pos // self.width
            col = pos % self.width
            self.mine_Matrix[row][col] = -1
        
        # 6. 计算每个格子的周围雷数
        for row in range(self.height):
            for col in range(self.width):
                if self.mine_Matrix[row][col] != -1:
                    self.mine_Matrix[row][col] = self._count_adjacent_mines(row, col)
        
        # 7. 标记首次点击位置为打开状态
        self.update_mark(first_click[0], first_click[1], 'open')
        self.first_click_done = True
    
    def _get_safe_zone(self, first_click):
        """计算首次点击的安全区域（包含点击位置及其周围8格）"""
        safe_zone = set()
        click_row, click_col = first_click
        
        # 遍历3x3区域
        for r in range(max(0, click_row-1), min(self.height, click_row+2)):
            for c in range(max(0, click_col-1), min(self.width, click_col+2)):
                # 将坐标转换为线性索引
                index = r * self.width + c
                safe_zone.add(index)
                
        return safe_zone

    def _count_adjacent_mines(self, row, col):
        """计算指定位置周围的地雷数量"""
        count = 0
        for r in range(max(0, row-1), min(self.height, row+2)):
            for c in range(max(0, col-1), min(self.width, col+2)):
                if (r != row or c != col) and self.mine_Matrix[r][c] == -1:
                    count += 1
        return count

    def update_mark(self, row, col, action_type):
        """
        更新格子状态（核心逻辑）
        :param row: 行坐标 (0 ≤ row < height)
        :param col: 列坐标 (0 ≤ col < width)
        :param action_type: 操作类型 ("open"=打开, "flag"=标记)
        """
        # 边界检查与游戏状态校验
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise IndexError(f"坐标({row}, {col})超出雷区范围")
        if self.game_over:
            raise RuntimeError("游戏已结束，无法操作")
        if self.mark_Matrix[row][col] == 10:
            return  # 已打开的格子不响应操作

        # 打开操作逻辑
        if action_type == "open":
            if self.mine_Matrix[row][col] == -1:  # 踩中地雷
                self.game_over = True
                self.mark_Matrix[row][col] = 10  # 显示触雷位置
                raise ValueError("游戏失败！踩中地雷")
            else:  # 安全格子
                self.mark_Matrix[row][col] = 10  # 标记为已打开
                # 可选：自动展开空白区域（需扩展DFS实现）
                if self.mine_Matrix[row][col] == 0:
                    for dr in [-1, 0, 1]:
                        for dc in [-1, 0, 1]:
                            nr, nc = row + dr, col + dc
                            if 0 <= nr < self.height and 0 <= nc < self.width:
                                if self.mark_Matrix[nr][nc] != 10:
                                    self.update_mark(nr, nc, "open")

        # 标记操作逻辑（循环切换0→1→2→0）
        elif action_type == "flag":
            current_mark = self.mark_Matrix[row][col]
            self.mark_Matrix[row][col] = (current_mark + 1) % 3  # 0→1→2→0循环

        else:
            raise ValueError(f"无效操作类型，仅支持 'open' 或 'flag'，输入：'{action_type}'")
        
    def print_board(self, show_mines=False):
        """
        可视化当前游戏状态
        :param show_mines: 是否显示地雷位置（调试用）
        """
        symbols = {

            -1: '💣', 0: ' ', 1: '1', 2: '2', 3: '3', 4: '4',
            5: '5', 6: '6', 7: '7', 8: '8'
        }
        
        print("\n雷区状态:")
        for r in range(self.height):
            row_str = ""
            for c in range(self.width):
                if self.mark_Matrix[r][c] == 10:  # 已打开格子
                    val = self.mine_Matrix[r][c]
                    row_str += symbols.get(val, ' ') + " "
                elif self.mark_Matrix[r][c] == 1:  # 标记为雷
                    row_str += "🚩 "
                elif self.mark_Matrix[r][c] == 2:  # 标记问号
                    row_str += "❓ "
                else:  # 未打开
                    if show_mines and self.mine_Matrix[r][c] == -1:
                        row_str += "💣 "
                    else:
                        row_str += "■ "
            print(row_str)

    def helpCal(self,col,row,L):
        start_r = max(0, row - L)
        start_c = max(0, col - L)
        submatrix,valid_coords = self.get_submatrix(self.mine_Matrix, row, col, L)
        submatrix1,_ = self.get_submatrix(self.mark_Matrix, row, col, L)
        submatrix = self.modify_matrix(submatrix, submatrix1)
        submatrix,origin_position = self.trim_zero_edges(submatrix)
        top = start_r + origin_position[0]
        left = start_c + origin_position[1]
        rows = len(submatrix)          # 获取行数
        cols = len(submatrix[0])       # 获取第一行的列数（假设为矩形矩阵）
        for i in range(rows):
            for j in range(cols):
                submatrix[i][j] = submatrix[i][j] if submatrix[i][j] != -10 else 0

        inner_pos = [i * cols + j for i, j in valid_coords]
        flattened_list = [item for sublist in submatrix for item in sublist]

        count,result = Mat_Cal.Local_Mat_Cal(flattened_list, rows, cols, 1,1, inner_pos)
        dict = {((i // cols + top, i % cols + left)) : abs(j / count) for (i,j) in result}
        return dict

    def get_submatrix(self,matrix, center_row, center_col, L):
        """
        获取中心坐标的指定层级子矩阵及有效坐标集合
        
        参数:
        matrix: 二维列表表示的矩阵
        center_row, center_col: 中心坐标索引 (从0开始计数)
        L: 层级 (子矩阵半径)
        
        返回:
        (submatrix, valid_coords)
        submatrix: 二维列表表示的子矩阵
        valid_coords: 满足条件的坐标集合 [(row, col), ...]
        """
        rows = len(matrix)
        cols = len(matrix[0]) if rows > 0 else 0
        
        # 1. 计算子矩阵边界 (自动处理矩阵边缘)
        row_start = max(0, center_row - L)
        row_end = min(rows, center_row + L + 1)
        col_start = max(0, center_col - L)
        col_end = min(cols, center_col + L + 1)
        
        # 2. 提取子矩阵
        submatrix = [
            row[col_start:col_end] 
            for row in matrix[row_start:row_end]
        ]
        
        # 3. 筛选有效坐标 (要求该坐标的L=1子矩阵完全包含在原子矩阵内)
        valid_coords = []
        for r_rel in range(len(submatrix)):
            for c_rel in range(len(submatrix[0])):
                # 计算绝对坐标
                r_abs = row_start + r_rel
                c_abs = col_start + c_rel
                
                # 检查该坐标的L=1子矩阵是否在边界内
                if (submatrix[r_rel][c_rel] > 0 and  row_start <= r_abs - 1 <= r_abs + 1 < row_end and
                    col_start <= c_abs - 1 <= c_abs + 1 < col_end ):
                    valid_coords.append((r_abs, c_abs))
        
        return submatrix, valid_coords

    def modify_matrix(self,a, b):
        c = a.copy()
    # 遍历矩阵 b 的每个元素
        for i in range(len(b)):
            for j in range(len(b[0])):
                # 条件 1: b 中值为 0 或 2 的位置，将 a 对应位置设为 -10
                if b[i][j] in (0, 2):
                    c[i][j] = -10
                # 条件 2: b 中值为 1 的位置，将 a 对应位置设为 -1
                elif b[i][j] == 1:
                    c[i][j] = -1
        return c

    def trim_zero_edges(self,matrix):
        """
        删除矩阵四边连续的 L-1 行/列全0边界（L≥2），保留最内侧一行全0
        同时返回新矩阵第一个元素在原矩阵中的坐标 (row_idx, col_idx)
        参数：
            matrix: 二维列表表示的矩阵（元素为整数）
        返回：
            (裁剪后的新矩阵, 新矩阵[0][0]在原矩阵的位置)
        """
        if not matrix or not matrix[0]:
            return matrix, (0, 0)

        rows = len(matrix)
        cols = len(matrix[0])
        
        # 检测上边界连续全0行数
        top = 0
        while top < rows and all(x == 0 for x in matrix[top]):
            top += 1
        top_trim = max(0, top - 1) if top >= 2 else 0

        # 检测下边界连续全0行数
        bottom = 0
        while bottom < rows and all(x == 0 for x in matrix[rows - 1 - bottom]):
            bottom += 1
        bottom_trim = max(0, bottom - 1) if bottom >= 2 else 0

        # 检测左边界连续全0列数
        left = 0
        while left < cols and all(matrix[i][left] == 0 for i in range(rows)):
            left += 1
        left_trim = max(0, left - 1) if left >= 2 else 0

        # 检测右边界连续全0列数
        right = 0
        while right < cols and all(matrix[i][cols - 1 - right] == 0 for i in range(rows)):
            right += 1
        right_trim = max(0, right - 1) if right >= 2 else 0

        # 计算裁剪后的新矩阵和首个元素位置
        new_matrix = [
            row[left_trim : cols - right_trim]
            for row in matrix[top_trim : rows - bottom_trim]
        ]
        
        # 新矩阵[0][0]在原矩阵中的坐标 (行, 列)
        origin_position = (top_trim, left_trim)
        
        return new_matrix, origin_position

if __name__ == "__main__":
    # 初始化游戏 (9x9网格，10个雷)
    game = MineSweeper(9, 9, 10)
    game.gen_mine(first_click=(4, 4))
    d = game.helpCal(2,3,1)
    # # 标记操作示例
    # game.update_mark(2, 3, "flag")  # 标记为雷 (0→1)
    # game.update_mark(2, 3, "flag")  # 改为问号 (1→2)
    # game.update_mark(2, 3, "flag")  # 取消标记 (2→0)

    # # 打开格子示例
    # game.update_mark(4, 4, "open")  # 安全打开
    # try:
    #     game.update_mark(0, 0, "open")  # 若(0,0)是雷则触发失败
    # except ValueError as e:
    #     print(e)  # 输出: "游戏失败！踩中地雷"

    # 打印状态
    game.print_board()
    print(d)