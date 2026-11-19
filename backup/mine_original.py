import sys
import os
import json
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append(r".\site-packages")
from datetime import datetime
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout,QDialog, QVBoxLayout,QButtonGroup,QRadioButton,QActionGroup,\
QPushButton, QGridLayout, QSizePolicy,QToolButton,QToolBar,QMainWindow,QMenuBar, QAction, QLCDNumber, QLabel,QStyle,QSpinBox
from PyQt5.QtCore import Qt,QEvent,QTimer,QTime,QCoreApplication
from PyQt5.QtGui import QColor, QPainter, QPen, QPalette, QFont

import random
from enum import Enum
import Mat_Cal

class Status(Enum):
    NORMAL = 1
    FAIL = 2
    WIN = 3

class base_MineDetection: 
    def __init__(self,*args):
        #默认开高级
        if len(args) == 0:
            self.__init(16,30,99)
        elif len(args) == 1:
            if args[0].lower() in 'low':
                self.__init(9,9,10)
            elif args[0].lower() in 'middle':
                self.__init(16,16,40)
            elif args[0].lower() in 'high':
                self.__init(16,30,99)
            else:
                self.__init(16,30,99)
        elif len(args) == 2:
            self.__init(args[0],args[1],10)
        elif len(args) == 3:
            self.__init(args[0],args[1],args[2])
        else:
            raise TypeError("Too many input args")
            
    def __init(self,Height,Width,Num_Mine):
        self.Height = Height
        self.Width = Width
        self.Num_Mine = Num_Mine
        
        self.mine_Matrix = []
        self.index_Matrix = [[1] * Width for _ in range(Height)]  
        self.mark_Matrix = [[0] * Width for _ in range(Height)]  
        #状态矩阵 0为未展开 1为标记雷 -10为展开地格
        
    def remain_mine(self):
        return self.Num_Mine - len([self.mark_Matrix[i][j] for i in range(len(self.mark_Matrix)) for j in range(len(self.mark_Matrix[0])) if self.mark_Matrix[i][j]==1])
      
    def get_round(self,x,y):
        pos = []
        directions = [[0,1],[0,-1],[-1,0],[1,0],[1,1],[1,-1],[-1,1],[-1,-1]];
        for j in directions:
            #确保索引没有出边界
            if x+j[0] >= 0 and x+j[0]<= self.Height-1 and y+j[1]>=0 and y+j[1]<= self.Width-1:
                pos.append( (x+j[0],y+j[1]) )
        return pos
    
    def gen_mine(self, first_click):
        """
        生成扫雷矩阵，确保首次点击位置为0（周围无雷）
        :param first_click: 首次点击坐标元组(row, col)
        """
        # 1. 初始化全0矩阵
        self.mine_Matrix = [[0] * self.Width for _ in range(self.Height)]
        total_cells = self.Width * self.Height
        
        # 2. 计算安全区域（首次点击+周围8格）
        safe_zone = self._get_safe_zone(first_click)
        
        # 3. 检查雷数是否超过可用位置
        available_cells = total_cells - len(safe_zone)
        if self.Num_Mine > available_cells:
            raise ValueError(f"雷数过多！最大可布置数: {available_cells}")
        
        # 4. 生成布雷候选位置（排除安全区）
        all_positions = [i for i in range(total_cells) if i not in safe_zone]
        mine_positions = random.sample(all_positions, self.Num_Mine)
        
        # 5. 布置地雷
        for pos in mine_positions:
            row = pos // self.Width
            col = pos % self.Width
            self.mine_Matrix[row][col] = -1
        
        # 6. 计算每个格子的周围雷数
        for row in range(self.Height):
            for col in range(self.Width):
                if self.mine_Matrix[row][col] != -1:
                    self.mine_Matrix[row][col] = self._count_adjacent_mines(row, col)

    def _get_safe_zone(self, first_click):
        """计算首次点击的安全区域（包含点击位置及其周围8格）"""
        safe_zone = set()
        click_row, click_col = first_click
        
        # 遍历3x3区域
        for r in range(max(0, click_row-1), min(self.Height, click_row+2)):
            for c in range(max(0, click_col-1), min(self.Width, click_col+2)):
                # 将坐标转换为线性索引
                index = r * self.Width + c
                safe_zone.add(index)
                
        return safe_zone
    
    def _count_adjacent_mines(self, row, col):
        """计算指定位置周围的地雷数量"""
        count = 0
        for r in range(max(0, row-1), min(self.Height, row+2)):
            for c in range(max(0, col-1), min(self.Width, col+2)):
                if (r != row or c != col) and self.mine_Matrix[r][c] == -1:
                    count += 1
        return count
    
    def get_current_spanPos(self,Pos):
        state = False
        for x,y in Pos:
            if self.index_Matrix[x][y] and self.mine_Matrix[x][y] == 0:
                state = True
        if state:
            directions = [[0,1],[0,-1],[-1,0],[1,0],[1,1],[1,-1],[-1,1],[-1,-1]];
            for x,y in Pos:
                if self.index_Matrix[x][y] and self.mine_Matrix[x][y] == 0:#首先确保这个元素可见
                    self.index_Matrix[x][y] = False
                    for j in directions:
                        #确保索引没有出边界
                        if x+j[0] >= 0 and x+j[0]<= self.Height-1 and y+j[1]>=0 and y+j[1]<= self.Width-1:
                            Pos.append( (x+j[0],y+j[1]) )
            
            Pos = list(set(Pos))
            return self.get_current_spanPos(Pos)
        else:
            return Pos
        
    def autoCal_local(self,x:int,y:int,Level:int =2):
        top = max(x-Level,0)
        left = max(y-Level,0)
        
        submatrix,valid_coords = self.get_CalMat(x, y, Level)
        submatrix,origin_position = self.trim_zero_edges(submatrix)
        
        top = top + origin_position[0]
        left = left + origin_position[1]
        
        ax = len(submatrix)          # 获取行数
        ay = len(submatrix[0])       # 获取第一行的列数（假设为矩形矩阵）
        
        flat_list = [item for sublist in submatrix for item in sublist]
        valid_coords1 = [(i-top,j-left) for i,j in valid_coords]

#        pos_info_whole_open = [i * ay + j for i, j in valid_coords1]
        pos_info_whole_uncover = [i * ay + j for i, j in valid_coords1 if i<ax and j<ay and submatrix[i][j] == 0]
        pos_info_whole_open = [i * ay + j for i, j in valid_coords1 if i<ax and j<ay and submatrix[i][j] > 0]
        
        markMine = 0
        for r in range(max(0, x-1), min(self.Height, x+2)):
            for c in range(max(0, y-1), min(self.Width, y+2)):
                if (r != x or c != y) and self.mark_Matrix[r][c] == 1:
                    markMine += 1

        x1 = self.mine_Matrix[x][y] - markMine
        x2 = sum(submatrix[px][py] for px,py in valid_coords1 if px<ax and py<ay)
#        print(submatrix,submark_Matrix,ax,ay,x1,x2,valid_coords)
        count,result = Mat_Cal.Local_Mat_Cal(flat_list, ax, ay, x1, x2, pos_info_whole_open)
        if count != 0:
            infoDict = {(i // ay + top , i % ay + left) : abs(j / count) for (i,j) in result if abs(j)==count or j==0 or i in pos_info_whole_uncover}
        else:
            infoDict = {}
        return infoDict
         
    def autoCal_whole(self):
        cal_mat,_ = self.get_CalMat(0, 0, 100)
        flat_cal_mat = [item for sublist in cal_mat for item in sublist]
        count,result = Mat_Cal.Whole_Mat_Cal(flat_cal_mat,self.Height,self.Width,self.remain_mine())
        if count != 0:
            infoDict = {(i // self.Width, i % self.Width) : abs(j / count) for (i,j) in result}
        else:
            infoDict = {}
        return infoDict

#    def auto_calculate(self):
#        directions = [[0,1],[0,-1],[-1,0],[1,0],[1,1],[1,-1],[-1,1],[-1,-1]];
#        L = 1
#        randomOpen_Flag = False
#        WholeCal_Flag = False
#  
#        randomOpen = []
#        randomMine = []
#        
#        for i in range(1000):
#            cal_mat,_ = self.get_CalMat(0, 0, 100)
#            
#            maxProb = 0  #最大为雷可能性
#            minProb = 1  #最小为雷可能性
#            expansionList = []
#            mineMarkList = []
#            dictlist = []
#            if WholeCal_Flag:
#                print("-------使用全局计算--------")
#                infoDict = self.autoCal_whole()
#                dictlist.append(infoDict)
#            else:
#                print(f"------使用局部计算,iteration={i}，L={L}-------")
#                for indx in range(len(self.mark_Matrix)):
#                    for indy in range(len(self.mark_Matrix[0])):
#                        if cal_mat[indx][indy]<=0:
#                            continue
#                        neighbor = [(ni+indx,nj+indy) for ni,nj in directions if 0<=ni+indx< self.Height and 0<=nj+indy< self.Width and\
#                                    (cal_mat[ni+indx][nj+indy] == -1 or cal_mat[ni+indx][nj+indy] == 0) ] 
#                        markedMines = abs(sum(cal_mat[nx][ny] for nx,ny in neighbor if cal_mat[nx][ny]==-1))
#                        unopened = len(neighbor) - markedMines
#                        if unopened == 0 and markedMines != cal_mat[indx][indy]:
#                            print("Pos",indx,indy,"markedMines",markedMines,cal_mat[indx][indy],"unopened",unopened)
#                            yield [],[],[(nx,ny) for nx,ny in neighbor if cal_mat[nx][ny]==-1]
#                        elif unopened != 0:
#                            infoDict = self.autoCal_local(indx, indy, L)
#                            dictlist.append(infoDict)
#
#            for d in dictlist:
#                for p, value in d.items():
#                    if value == 0:
#                        yield [p], [],[]
#                        expansionList.append(p)
#                    elif value == 1:
#                        yield [], [p],[]
#                        mineMarkList.append(p)
##                    elif p not in randomMine or p not in randomOpen:
#                    else:
#                        if value >= maxProb:
#                            maxProb = value
#                            minePos = p
#                        elif value <= minProb:
#                            minProb = value
#                            openPos = p
#
#            # #没有找到可以打开或标雷的格子，则先升阶查找，如果还找不到，则试图全局计算
#            # #如果升阶或全局计算都不行，则找到概率最低的位置打开
#            if len(expansionList) + len(mineMarkList) == 0: #此次计算没有可以打开或标记的
#                print("此次没有可以打开的")
#                if L < 2:
#                    print("升阶尝试")
#                    L = L + 1
#                elif not WholeCal_Flag:    #如果已经升阶，判断是否可以进行全局计算
#                    
#                    n = len([item for list in cal_mat for item in list if item==0])
#                    k = self.remain_mine()
#                    print(f"已经升阶，计算是否可以全局计算,n={n},k={k}")
#                    if n < 28 and k < 14:
#                        WholeCal_Flag = True
#                    else: #如果升阶或全局计算都不行，则找到概率最低的位置打开
#                        print("无法全局计算，随机位置打开")
#                        randomOpen_Flag = True
#                else:
#                    print("全局计算和升阶均不行，随机位置打开")
#                    randomOpen_Flag = True
#                    
#            if ( len(expansionList) or len(mineMarkList) ) and L > 1:
#                L = 1
#
#            if randomOpen_Flag:
#                print(f"随机打开,maxprob={maxProb},minProb={minProb},minePos={minePos},openPos={openPos}")
#                randomOpen_Flag = False
#                if maxProb >= 1-minProb: #判断为雷的把握大于判断为空的把握，标一个雷
#                    randomMine.append(minePos)
#                    yield  [], [minePos],[]
#                else:
#                    randomOpen.append(openPos)
#                    yield  [openPos], [],[]
##            else:
##                yield  expansionList, mineMarkList,[]
       
    def auto_calculate(self):
        directions = [[0,1],[0,-1],[-1,0],[1,0],[1,1],[1,-1],[-1,1],[-1,-1]];
        L = 1
        randomOpen_Flag = False
        WholeCal_Flag = False
  
        randomOpen = []
        
        for i in range(1000):
            cal_mat,_ = self.get_CalMat(0, 0, 100)
            
            minProb = 1  #最小为雷可能性
            expansionList = []
            mineMarkList = []
            dictlist = []
            if WholeCal_Flag:
                print("-------使用全局计算--------")
                infoDict = self.autoCal_whole()
                dictlist.append(infoDict)
            else:
                print(f"------使用局部计算,iteration={i}，L={L}-------")
                for indx in range(len(self.mark_Matrix)):
                    for indy in range(len(self.mark_Matrix[0])):
                        if cal_mat[indx][indy]<=0:
                            continue
                        neighbor = [(ni+indx,nj+indy) for ni,nj in directions if 0<=ni+indx< self.Height and 0<=nj+indy< self.Width and\
                                    (cal_mat[ni+indx][nj+indy] == -1 or cal_mat[ni+indx][nj+indy] == 0) ] 
                        markedMines = abs(sum(cal_mat[nx][ny] for nx,ny in neighbor if cal_mat[nx][ny]==-1))
                        unopened = len(neighbor) - markedMines
                        if unopened != 0:
                            infoDict = self.autoCal_local(indx, indy, L)
                            dictlist.append(infoDict)

            for d in dictlist:
                for p, value in d.items():
                    if value == 0:
                        yield [p], []
                        expansionList.append(p)
                    elif value == 1:
                        yield [], [p]
                        mineMarkList.append(p)
#                    elif p not in randomMine or p not in randomOpen:
                    else:
                        if value <= minProb:
                            minProb = value
                            openPos = p

            # #没有找到可以打开或标雷的格子，则先升阶查找，如果还找不到，则试图全局计算
            # #如果升阶或全局计算都不行，则找到概率最低的位置打开
            if len(expansionList) + len(mineMarkList) == 0: #此次计算没有可以打开或标记的
                print("此次没有可以打开的")
                if L < 2:
                    print("升阶尝试")
                    L = L + 1
                elif not WholeCal_Flag:    #如果已经升阶，判断是否可以进行全局计算
                    
                    n = len([item for list in cal_mat for item in list if item==0])
                    k = self.remain_mine()
                    print(f"已经升阶，计算是否可以全局计算,n={n},k={k}")
                    if n < 28 and k < 14:
                        WholeCal_Flag = True
                    else: #如果升阶或全局计算都不行，则找到概率最低的位置打开
                        print("无法全局计算，随机位置打开")
                        randomOpen_Flag = True
                else:
                    print("全局计算和升阶均不行，随机位置打开")
                    randomOpen_Flag = True
                    
            if ( len(expansionList) or len(mineMarkList) ) and L > 1:
                L = 1

            if randomOpen_Flag:
                print(f"随机打开,minProb={minProb},openPos={openPos}")
                randomOpen_Flag = False
                randomOpen.append(openPos)
                yield  [openPos], []
    
    def get_CalMat(self,x,y,Level):
        row_start = max(x-Level,0)
        row_end = min(x+1+Level,self.Height+1)
        col_start = max(y-Level,0)
        col_end = min(y+1+Level,self.Width+1)
        
        submatrix = [
            row[col_start:col_end] 
            for row in self.mark_Matrix[row_start:row_end]
        ]
        
        valid_coords = []
        for r_rel in range(len(submatrix)):
            for c_rel in range(len(submatrix[0])):
                # 计算绝对坐标
                r_abs = row_start + r_rel
                c_abs = col_start + c_rel
                
                if self.mark_Matrix[r_abs][c_abs] == 0 or self.mark_Matrix[r_abs][c_abs] == 2:
                    submatrix[r_rel][c_rel] = 0
                elif self.mark_Matrix[r_abs][c_abs] == 1:
                    submatrix[r_rel][c_rel] = -1
                elif self.mark_Matrix[r_abs][c_abs] == -10 and self.mine_Matrix[r_abs][c_abs] == 0:
                    submatrix[r_rel][c_rel] = -10
                elif self.mark_Matrix[r_abs][c_abs] == -10 and self.mine_Matrix[r_abs][c_abs] > 0:
                    submatrix[r_rel][c_rel] = self.mine_Matrix[r_abs][c_abs]
                
                # 检查该坐标的L=1子矩阵是否在边界内
                if (submatrix[r_rel][c_rel] >= 0 and  row_start <= max(r_abs - 1,0) <= min(r_abs + 1,row_end) < row_end and
                    col_start <= max(c_abs - 1,0) <= min(c_abs + 1,col_end) < col_end ):
                    valid_coords.append((r_abs, c_abs))
        return submatrix,valid_coords
    
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
    
    
    def win_judge(self):
        Num01 = \
   len( [self.mark_Matrix[i][j] for i in range(len(self.mark_Matrix)) for j in range(len(self.mark_Matrix[0])) 
   if self.mark_Matrix[i][j]==1 or self.mark_Matrix[i][j]==0] )
        if Num01 == self.Num_Mine:
            return True
        else:
            return False
    
    def ramdomPos(self):
        return (random.randint(0,self.Height-1),random.randint(0,self.Width-1))
    
    def new_game(self):
        self.mine_Matrix = []
        self.index_Matrix = [[1] * self.Width for _ in range(self.Height)]  
        self.mark_Matrix = [[0] * self.Width for _ in range(self.Height)] 
        
    def reset(self):
        self.index_Matrix = [[1] * self.Width for _ in range(self.Height)]  
        self.mark_Matrix = [[0] * self.Width for _ in range(self.Height)] 
    
    def expansion(self,x,y):
        expansionPos = []
        state = self.mine_Matrix[x][y];
        info = Status.NORMAL
        if state == 0:
            Pos = self.get_current_spanPos([(x,y)])
            expansionPos = Pos
            for x,y in Pos:
                self.mark_Matrix[x][y] = -10
        elif state > 0:
            expansionPos = [(x,y)]
            self.mark_Matrix[x][y] = -10
        else:
            info = Status.FAIL
        if self.win_judge():
            info = Status.WIN
        
        return info,expansionPos
            
    def mine_mark(self,x,y):
        self.mark_Matrix[x][y] = 1
        info = Status.NORMAL
        if self.win_judge():
            info = Status.WIN
        return info
    
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)
        self.setWindowTitle("设置对话框")

        main_layout = QVBoxLayout()

        level_layout = QVBoxLayout()
        self.level_group = QButtonGroup(self)

        # 创建初级、中级、高级和自定义的单选按钮
        self.beginner_radio = QRadioButton("初级")
        self.intermediate_radio = QRadioButton("中级")
        self.advanced_radio = QRadioButton("高级")
        self.custom_radio = QRadioButton("自定义")

        # 将单选按钮添加到水平布局1
        level_layout.addWidget(self.beginner_radio)
        level_layout.addWidget(self.intermediate_radio)
        level_layout.addWidget(self.advanced_radio)
        # level_layout.addWidget(self.custom_radio)

        # 将单选按钮添加到按钮组
        self.level_group.addButton(self.beginner_radio)
        self.level_group.addButton(self.intermediate_radio)
        self.level_group.addButton(self.advanced_radio)
        self.level_group.addButton(self.custom_radio)

        # 创建自定义设置的垂直布局
        custom_layout = QGridLayout()

        # 创建自定义设置的标签和 SpinBox
        self.height_label = QLabel("高度")
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(9, 24)

        self.width_label = QLabel("宽度")
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(9, 30)

        self.mine_label = QLabel("雷数")
        self.mine_spinbox = QSpinBox()
        self.mine_spinbox.setRange(10, 668)

        # 将标签和 SpinBox 添加到垂直布局
        custom_layout.addWidget(self.custom_radio,1,1)
        custom_layout.addWidget(self.height_label,2,1)
        custom_layout.addWidget(self.height_spinbox,2,2)
        custom_layout.addWidget(self.width_label,3,1)
        custom_layout.addWidget(self.width_spinbox,3,2)
        custom_layout.addWidget(self.mine_label,4,1)
        custom_layout.addWidget(self.mine_spinbox,4,2)

        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("退出")
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        # 创建一个垂直布局，包含水平布局1和自定义设置布局
        layout1 = QHBoxLayout()
        layout1.addLayout(level_layout)
        layout1.addLayout(custom_layout)
        main_layout.addLayout(layout1)
        main_layout.addLayout(button_layout)
        # 设置对话框的主布局
        self.setLayout(main_layout)

    def get_settings(self):
        settings = {}
        if self.beginner_radio.isChecked():
            settings = {"rows": 9,
                        "cols": 9,
                        "mines": 10}
        elif self.intermediate_radio.isChecked():
            settings = {"rows": 16,
                        "cols": 16,
                        "mines": 40}
        elif self.advanced_radio.isChecked():
            settings = {"rows": 16,
                        "cols": 30,
                        "mines": 99}
        elif self.custom_radio.isChecked():
            settings = {"rows": self.height_spinbox.value(),
                        "cols": self.width_spinbox.value(),
                        "mines": self.mine_spinbox.value()}
        return settings

class CustomButton(QPushButton):
    def __init__(self, parent=None):
        super(CustomButton, self).__init__(parent)
#        self.clicked.connect(self.start_flash)
        self.flash_count = 0
        self.is_flashing = False
        self.show_x = False

    def start_flash(self):
        self.is_flashing = True
        self.flash_count = 0
        self.show_x = True
        self.update()
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.flash)
        self.flash_timer.start(100)  # 500 milliseconds

    def flash(self):
        self.flash_count += 1
        self.show_x = not self.show_x
        self.update()
        if self.flash_count >= 4:  # 4 times (2 on, 2 off)
            self.flash_timer.stop()
            self.is_flashing = False
            self.show_x = False
            self.flash_count = 0
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.is_flashing and self.show_x:
            self.paintX()
    
    def paintX(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(255, 0, 0), 2)
        painter.setPen(pen)
        
        # Calculate the center of the button
        center_x = self.width() // 2
        center_y = self.height() // 2
        side_length = min(self.width(), self.height()) // 2
        
        # Draw the X centered in the button
        painter.drawLine(center_x - side_length, center_y - side_length, center_x + side_length, center_y + side_length)
        painter.drawLine(center_x + side_length, center_y - side_length, center_x - side_length, center_y + side_length)

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.rows = config['rows']
        self.cols = config['cols']
        self.mineClass = base_MineDetection(self.rows,self.cols,config['mines'])
        self.first_click = True
        self.cheatTime = 0
        self.isFinish = False  #用来判断游戏是否结束
        self.isReset = False
        self._GameState = Status.NORMAL
        #这2个是用来鼠标中键按下时候确认状态的
        self.current_button = None
        self.checkState = False
        
        #设置自动计算速度的
        self.autocalSpeed = 30
        self.AutoCaltimer = QTimer(self)
        self.AutoCaltimer.timeout.connect(self.update_view)
        self.Timer = QTimer(self)
        self.time = QTime(0, 0, 0)
        self.Timer.timeout.connect(self.update_time)
        
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("扫雷")
        font = QFont("Arial Black", 12)
        font.setBold(True)
        # 创建一个网格布局
        grid_layout = QGridLayout()
        grid_layout.setSpacing(0)  # 设置按钮之间的间隔

        # 创建按钮并添加到网格布局中
        self.ButtonList = [[None for _ in range(self.cols)] for _ in range(self.rows)]

        for i in range(self.rows):
            for j in range(self.cols):
                button = CustomButton()
                button.setStyleSheet(self.style_uncover)
                button.setFont(font)
                button.setMinimumSize(20, 20)  # 设置按钮的固定大小
                button.installEventFilter(self)  # 安装事件过滤器
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                grid_layout.addWidget(button, i, j)
                self.ButtonList[i][j] = button
                button.row = i
                button.col = j
        
        for row in range(self.rows):
            grid_layout.setRowStretch(row, 1)
        for col in range(self.cols):
            grid_layout.setColumnStretch(col, 1)
            
        # 设置主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setLayout(grid_layout)
        
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        # 创建标签
        self.label = QLabel("剩余雷数")
        toolbar.addWidget(self.label)

        # 添加数字显示器
        self.lcd_number = QLCDNumber()
        self.lcd_number.setSegmentStyle(QLCDNumber.Flat)
        self.lcd_number.display(self.mineClass.remain_mine())

        # 设置数字显示器的背景颜色为黑色
        palette = self.lcd_number.palette()
        palette.setColor(palette.Window, QColor(0, 0, 0))
        palette.setColor(palette.WindowText, QColor(255, 255, 255))
        self.lcd_number.setPalette(palette)
        self.lcd_number.setStyleSheet("background-color: black; color: white;")
        
        self.cheatlcd_number = QLCDNumber()
        self.cheatlcd_number.setSegmentStyle(QLCDNumber.Flat)
        self.cheatlcd_number.display(self.cheatTime)
        self.cheatlcd_number.setPalette(palette)
        self.cheatlcd_number.setStyleSheet("background-color: black; color: white;")    

        self.timelcd = QLCDNumber()
        self.timelcd.setSegmentStyle(QLCDNumber.Flat)
        self.timelcd.display(self.time.toString('mm:ss'))
        self.timelcd.setPalette(palette)
        self.timelcd.setStyleSheet("background-color: black; color: white;") 

        toolbar.addWidget(self.lcd_number)

        # 创建按钮并设置图标
        self.startButton = QToolButton()
        self.startButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        
        self.resetButton = QToolButton()
        self.resetButton.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
#        self.startButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.showButton = QToolButton()
        self.showButton.setIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
        self.showButton.setText("全部展开")
        self.showButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
#        self.startButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.helpButton = QToolButton()
        self.helpButton.setIcon(self.style().standardIcon(QStyle.SP_DialogNoButton))
        self.helpButton.setCheckable(True)
        self.helpButton.setText("辅助计算 阶数:")
        self.helpButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        
        self.autoCalButton = QToolButton()
        self.autoCalButton.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self.autoCalButton.setCheckable(True)
        self.autoCalButton.setText("自动计算")
        self.autoCalButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
#        self.startButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.cheatButton = QToolButton()
        self.cheatButton.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.cheatButton.setCheckable(True)
        self.cheatButton.setText("作弊一次")
        self.cheatButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
#        self.startButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.helpspinbox = QSpinBox()
        self.helpspinbox.setRange(1, 6)  # 设置范围为 1 到 3
#        self.startButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        toolbar.addWidget(self.startButton)
        toolbar.addWidget(self.resetButton)
        toolbar.addWidget(self.showButton)
        
        container = QWidget()
        layout = QHBoxLayout()
        layout.addWidget(self.helpButton)
        layout.addWidget(self.helpspinbox)
        container.setLayout(layout)
#        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        toolbar.addWidget(container)
        toolbar.addWidget(self.autoCalButton)
        toolbar.addWidget(self.cheatButton)
        toolbar.addWidget(self.cheatlcd_number)
        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar.addWidget(spacer)
        label1 = QLabel("时间：")  
        toolbar.addWidget(label1)
        toolbar.addWidget(self.timelcd)

        # 连接按钮的点击事件
        self.startButton.clicked.connect(self.newstart)
        self.resetButton.clicked.connect(self.reset)
        self.showButton.clicked.connect(self.showall)
        self.autoCalButton.toggled.connect(self.autocalculate)
        # 创建菜单栏
        menu_bar = QMenuBar()
        self.setMenuBar(menu_bar)

        # 添加文件菜单
        settingMenu = menu_bar.addMenu("设置")
        set_action = QAction("游戏设置",self)
        set_action.triggered.connect(self.Game_Set)
        settingMenu.addAction(set_action)
        setspeed_menu = settingMenu.addMenu("自动计算速度")
        action_group = QActionGroup(self)
        speed_action1 = QAction("非常慢", self, checkable=True,checked=False)
        speed_action2 = QAction("慢", self, checkable=True,checked=False)
        speed_action3 = QAction("中等", self, checkable=True,checked=False)
        speed_action4 = QAction("快", self, checkable=True,checked=True)
        speed_action5 = QAction("非常快", self, checkable=True,checked=False)
        setspeed_menu.addAction(speed_action1)
        setspeed_menu.addAction(speed_action2)
        setspeed_menu.addAction(speed_action3)
        setspeed_menu.addAction(speed_action4)
        setspeed_menu.addAction(speed_action5)
        
        action_group.addAction(speed_action1)
        action_group.addAction(speed_action2)
        action_group.addAction(speed_action3)
        action_group.addAction(speed_action4)
        action_group.addAction(speed_action5)
        
        speed_action1.triggered.connect(lambda : self.set_speed(1000))
        speed_action2.triggered.connect(lambda : self.set_speed(300))
        speed_action3.triggered.connect(lambda : self.set_speed(100))
        speed_action4.triggered.connect(lambda : self.set_speed(30))
        speed_action5.triggered.connect(lambda : self.set_speed(1))

        start_action = QAction("新游戏", self)
        start_action.triggered.connect(self.newstart)
        reset_action = QAction("重置本次游戏", self)
        reset_action.triggered.connect(self.reset)
        show_action = QAction("全部展开", self)
        show_action.triggered.connect(self.showall)
        cal_action = QAction("自动计算", self)
        cal_action.triggered.connect(self.autocalculate)
        self.continue_action = QAction("连续计算", self)
        self.continue_action.setCheckable(True)  # 设置为可勾选
        self.continue_action.setChecked(False)   # 初始状态为未勾选
        
        # statistic_action = QAction("统计信息", self)
        # statistic_action.triggered.connect(self.autocalculate)
        
        
        settingMenu.addAction(start_action)
        settingMenu.addAction(reset_action)
        settingMenu.addAction(show_action)
        settingMenu.addAction(cal_action)
        settingMenu.addAction(self.continue_action)
        # settingMenu.addAction(statistic_action)

    @property
    def GameState(self):
        return self._GameState
    @GameState.setter
    def GameState(self, new_value):
        if self._GameState != new_value:
            self._GameState = new_value
            self.handleValueChanged(new_value)
            
    def set_speed(self, speed):
        self.autocalSpeed = speed
        
    def handleValueChanged(self, value):
        if value == Status.WIN:
            self.isFinish = True
            self.Timer.stop()
            self.startButton.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            self.log_function_call(1)
        elif value == Status.FAIL:
            self.isFinish = True
            self.Timer.stop()
            self.startButton.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
            self.log_function_call(0)
    
    def log_function_call(self,state):
        file_path = 'results.json'
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            # 文件不存在或格式错误，使用默认配置
            data = {}
        
        current_time = datetime.now()
        formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
        infoState = {'state':state,'time':self.time.toString('mm:ss'),'currenttime':formatted_time,'cheat':self.cheatTime}
        key = f"{self.rows}_{self.cols}_{self.config['mines']}"
        if key in data:
            data[key].append(infoState)
        else:
            data[key] = [infoState]
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file)
    
    def eventFilter(self, obj, event):
        if any(button == obj for row in self.ButtonList for button in row):
            if event.type() == QEvent.MouseButtonPress:
                if event.buttons() == (Qt.LeftButton | Qt.RightButton) or event.buttons() == Qt.MiddleButton and not self.isFinish:# 左右键一起按或中键按下
                    self.checkState = True
                    self.current_button = obj
                    self.update_surrounding_buttons(obj, self.style_open)
                elif event.button() == Qt.LeftButton and event.buttons() & Qt.LeftButton:# 左键点击
                    self.on_left_button_clicked(obj)
                elif event.button() == Qt.RightButton and event.buttons() & Qt.RightButton:# 右键点击
                    self.on_right_button_clicked(obj)

            elif event.type() == QEvent.MouseButtonRelease:
                if self.checkState and (event.button() == Qt.MiddleButton or event.button() == Qt.LeftButton or  event.button() == Qt.RightButton) :
                    self.on_middle_button_clicked(self.current_button)
                    self.current_button = None
                    self.checkState = False

            elif event.type() == QEvent.MouseMove:
                if event.buttons() == (Qt.LeftButton | Qt.RightButton) or event.buttons() == Qt.MiddleButton:
                    button = QApplication.widgetAt(event.globalPos())
                    if isinstance(button, QPushButton) and button != self.current_button and not self.isFinish:
                        if self.current_button:
                            self.update_surrounding_buttons(self.current_button, self.style_uncover)
                        self.current_button = button
                        self.update_surrounding_buttons(button, self.style_open)

            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:# 左键双击
                    self.on_middle_button_clicked(obj)
#                    self.current_button = None
#                    self.checkState = False
 
        return super().eventFilter(obj, event)
    
    def update_surrounding_buttons(self, button, style):
        for i in range(-1, 2):
            for j in range(-1, 2):
                if 0 <= button.row + i < self.rows and 0 <= button.col + j < self.cols\
        and self.mineClass.mark_Matrix[button.row+i][button.col+j] == 0:
                    self.ButtonList[button.row + i][button.col + j].setStyleSheet(style)

    def expansion(self,x,y):
        State,expansionList = self.mineClass.expansion(x,y)
        if State == Status.NORMAL or State == Status.WIN:
            for px,py in expansionList:
                btn = self.ButtonList[px][py]
                self.update_button_text(btn, self.mineClass.mine_Matrix[px][py])
            self.GameState = State
        else:
            self.show_mines(x,y)
            self.GameState = State
            
    def mine_mark(self,x,y):
        self.GameState = self.mineClass.mine_mark(x,y)
        btn = self.ButtonList[x][y]
        btn.setText("★")
        btn.setStyleSheet(self.style_uncover)
        self.lcd_number.display(self.mineClass.remain_mine())
        
    def show_mines(self,x,y):
        for i in range(self.mineClass.Height):
            for j in range(self.mineClass.Width):
                if self.mineClass.mark_Matrix[i][j] == 1 or self.mineClass.mine_Matrix[i][j] == -1:
                    btn = self.ButtonList[i][j]
                    if self.mineClass.mark_Matrix[i][j] == 1 \
                    and self.mineClass.mine_Matrix[i][j] != -1:  # 雷被标错
                        btn.setText('X')
                    elif self.mineClass.mark_Matrix[i][j] == 1 \
                    and self.mineClass.mine_Matrix[i][j] == -1:  # 雷被标记且标对
                        btn.setStyleSheet("""
                        QPushButton {
                            background-color: rgb(36, 169, 102);
                            border: 1px solid black;
                            padding: 5px;
                        }
                    """)
                        btn.setText('⚡')
                    else:  # 雷没被标记
                        btn.setStyleSheet("""
                        QPushButton {
                            background-color: yellow;
                            border: 1px solid black;
                            padding: 5px;
                        }
                    """)
                        btn.setText('⚡')
                        
        clickedBtn = self.ButtonList[x][y]
        clickedBtn.setStyleSheet("""
                        QPushButton {
                            background-color: red;
                            border: 1px solid black;
                            padding: 5px;
                        }
                    """)
        clickedBtn.setText('⚡')
        
    def on_left_button_clicked(self, button):
        if self.isFinish:
            return
        x,y=button.row,button.col
        if self.mineClass.mark_Matrix[x][y] == 1:  # 如果按钮显示为 ★，则禁用左键点击
            return
        if self.first_click: #初始化整个矩阵
            self.mineClass.gen_mine((x,y))
            self.expansion(x,y)
            self.first_click = False
            self.Timer.start(1000)  # 每秒更新一次
        else:
            self.expansion(x, y)

    def on_right_button_clicked(self, button):
        if self.isFinish:
            return
        x,y=button.row,button.col
        if self.first_click:
            return
        if self.mineClass.mark_Matrix[x][y] == 0:  #未标记状态
            self.mine_mark(x,y)
        elif self.mineClass.mark_Matrix[x][y] == 1:
            self.mineClass.mark_Matrix[x][y] =2 #标记为问号
            button.setText("?")
        elif self.mineClass.mark_Matrix[x][y] == 2:
            self.mineClass.mark_Matrix[x][y] = 0 #从问号标记为无
            button.setText("")

    def on_middle_button_clicked(self, button):
        if self.isFinish:
            return
        x,y=button.row,button.col
        if self.mineClass.mark_Matrix[x][y] == -10:  #如果该区域已打开
            pos = self.mineClass.get_round(x,y)
            if self.cheatButton.isChecked():
                for px,py in pos:
                    if self.mineClass.mark_Matrix[px][py] != 10:
                        if self.mineClass.mine_Matrix[px][py] >= 0:
                            self.expansion(px,py)
                        else:
                            self.mine_mark(px,py)
                            
                self.cheatButton.setChecked(False)
                self.cheatTime = self.cheatTime + 1
                self.cheatlcd_number.display(self.cheatTime)
                return
            
            if self.helpButton.isChecked():
                infoDict = self.mineClass.autoCal_local(x, y, self.helpspinbox.value())
                try:
                    for p, value in infoDict.items():
                        if value == 0:
                            self.expansion(p[0],p[1])
                        elif value == 1:
                            self.mine_mark(p[0],p[1])
                except IndexError:
                    print("Error")

            count = 0 #标记为雷且确实为雷数
            count1 = 0 #标记为雷数
            for px,py in pos:
                if self.mineClass.mark_Matrix[px][py] == 1 : #该点被标记
                    count1 = count1 + 1
                    if self.mineClass.mine_Matrix[px][py] == -1:  
                        count = count + 1

            if count1 == self.mineClass.mine_Matrix[x][y] and count == count1: #可以展开
                for px,py in pos:
                    if self.mineClass.mark_Matrix[px][py] == 0 or self.mineClass.mark_Matrix[px][py] == 2:
                        self.expansion(px,py)   

            elif count1 == self.mineClass.mine_Matrix[x][y] and count != count1: #标雷错误，认定失败
                self.show_mines(x,y)
                
            else:#恢复原样
                button.start_flash()
                self.update_surrounding_buttons(self.ButtonList[x][y], self.style_uncover)
        else:
            self.update_surrounding_buttons(self.current_button, self.style_uncover)

    def update_button_text(self, button, number):
        button.setStyleSheet(self.style_open)
        if number == 0:
            button.setText("")
        else:
            button.setText(f"{number}")
            
        if number == 1:
            color = Qt.blue
        elif number == 2:
            color = QColor(23, 106, 3)
        elif number == 3:
            color = Qt.red
        elif number == 4:
            color = Qt.darkBlue
        elif number == 5:
            color = Qt.darkRed
        elif number == 6:
            color = QColor(85, 0, 127)
        else: 
            color = Qt.black
        palette = button.palette()
        palette.setColor(QPalette.ButtonText, color)
        button.setPalette(palette)

    def Game_Set(self):
        settings_dialog = SettingsDialog(self)
        if settings_dialog.exec_() == QDialog.Accepted:
            settings = settings_dialog.get_settings()
            self.reinitialize_game(settings)
    
    def reinitialize_game(self,settings):
        try:
            with open('config.json', 'r', encoding='utf-8') as file:
                data = json.load(file)
        except FileNotFoundError:
            data = {"rows": self.rows,
                    "cols": self.cols,
                    "mines": self.mineClass.Num_Mine}
            
        ChangeFLAG = False
        for key in settings.keys():
            if data[key] != settings[key]:
                ChangeFLAG = True
                data[key] = settings[key]
        
        if ChangeFLAG:
            with open('config.json', 'w', encoding='utf-8') as file:
                json.dump(settings, file, indent=4, ensure_ascii=False)
            
        script_path = os.path.abspath(sys.argv[0])
        print(script_path)
        self.close()
        # Restart the application using subprocess

        subprocess.Popen(f"{current_dir}\main.exe")
            

    def newstart(self):
        flat_list = (element for row in self.ButtonList for element in row)
        for btn in flat_list:
            btn.setStyleSheet(self.style_uncover)
            btn.setText("")
        self.first_click = True
        self.Cheat_Once_acvive = False
        self.cheatTime = 0
        self.isFinish = False
        self.isReset = False
        self.time = QTime(0, 0, 0)
        self.Timer.stop()
        self.mineClass.new_game()
        self.lcd_number.display(self.mineClass.remain_mine())
        self.cheatlcd_number.display(self.cheatTime)
        self.timelcd.display(self.time.toString('mm:ss'))
        self.startButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
    
    def reset(self):
        flat_list = (element for row in self.ButtonList for element in row)
        for btn in flat_list:
            btn.setStyleSheet(self.style_uncover)
            btn.setText("")
        self.first_click = False
        self.Cheat_Once_acvive = False
        self.cheatTime = 0
        self.isFinish = False
        self.isReset = True
        self.time = QTime(0, 0, 0)
        self.Timer.stop()
        self.mineClass.reset()
        self.lcd_number.display(self.mineClass.remain_mine())
        self.cheatlcd_number.display(self.cheatTime)
        self.timelcd.display(self.time.toString('mm:ss'))
        self.startButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        
    def showall(self):
        if self.first_click:
            return
        for i in range(self.mineClass.Height):
            for j in range(self.mineClass.Width):
                btn = self.ButtonList[i][j]
                state = self.mineClass.mine_Matrix[i][j]
                if state == -1:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: red;
                            border: 1px solid black;
                            padding: 5px;
                        }
                    """)
                    btn.setText('⚡')
                else:
                    self.update_button_text(btn,state)
        self.first_click = False
        self.isFinish = True

    def autocalculate(self, checked):
        if self.isFinish or self.isReset:
            self.autoCalButton.setChecked(False)
            return
        if checked:
            if self.first_click: #初始化整个矩阵
                px,py = self.mineClass.ramdomPos()
                self.mineClass.new_game()
                self.mineClass.gen_mine((px,py))
                self.first_click = False
                self.expansion(px,py)
                self.Timer.start(1000)
            
            self.generator = self.mineClass.auto_calculate()
            print(self.autocalSpeed)
            self.AutoCaltimer.setInterval(self.autocalSpeed)
            self.AutoCaltimer.start()
            self.update_view()
        else:
            self.AutoCaltimer.stop()

    def update_view(self):
        if self.autoCalButton.isChecked():
            try:
                expansionList, mineMarkList = next(self.generator)
                for px,py in expansionList:
                    self.expansion(px,py)
                    if self.isFinish:
                        raise StopIteration
                for px,py in mineMarkList:
                    self.mine_mark(px,py)
                    if self.isFinish:
                        raise StopIteration
                    
                if self.mineClass.win_judge():
                    raise StopIteration
            except StopIteration:
                self.autoCalButton.setChecked(False)
                self.generator = self.mineClass.auto_calculate()
                if self.continue_action.isChecked():
                    self.newstart()
                    self.autocalculate(True)
                    self.autoCalButton.setChecked(True)

    def update_time(self):
        self.time = self.time.addSecs(1)
        self.timelcd.display(self.time.toString('mm:ss'))

    @property
    def style_uncover(self):
        return """
            QPushButton {
                background-color: rgb(65, 163, 255);
                border: 1px solid black;
                padding: 5px;
        }
        """
    @property
    def style_open(self):
        return """
            QPushButton {
                background-color: white;
                border: 1px solid black;
                padding: 5px;
            }
        """
    
default_config = {
    "rows": 16,
    "cols": 16,
    "mines": 99,
}

def read_config(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            config = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        # 文件不存在或格式错误，使用默认配置
        config = default_config
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
    else:
        # 验证配置内容
        if not ( (9 <= config.get('rows', 0) <= 24) and \
            (9 <= config.get('cols', 0) <= 30) and (10 <= config.get('mines', 0) <= 668) ):
            print("Invalid window_width, using default configuration.")
            config = default_config
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(config, file, indent=4, ensure_ascii=False)
    return config

QCoreApplication.addLibraryPath(r".\site-packages\PyQt5\Qt5\plugins")
app = QApplication(sys.argv)
config = read_config('config.json')
window = MainWindow(config)
window.show()
sys.exit(app.exec_())