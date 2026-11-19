import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout
import Mat_Cal 
class SimpleApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()  # 初始化界面

    def initUI(self):
        # 设置窗口标题和尺寸
        self.setWindowTitle('简易PyQt5程序')
        self.setGeometry(300, 300, 300, 150)  # (x, y, width, height)

        # 创建标签和按钮
        self.label = QLabel('欢迎使用PyQt5!', self)
        self.button = QPushButton('点击我', self)
        
        # 连接按钮点击信号到槽函数
        self.button.clicked.connect(self.on_button_click)

        # 使用垂直布局管理控件
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def on_button_click(self):
        self.label.setText(f"asf")  # 更新标签文本
        grid = [0, 1, -10,
        0, 2, -10,
        0, 1, -10
        ]
        row, col = 3, 3
        inner_pos = []

        count,result = Mat_Cal.Local_Mat_Cal(grid, row, col, 1,1, inner_pos)
        # count,result = Mat_Cal.Whole_Mat_Cal(grid, row, col, 1)
        print(result)  # 输出 True/False
        print(count)  # 输出符合条件的元素个数
        self.label.setText(f"{count}")  # 更新标签文本

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = SimpleApp()
    ex.show()  # 显示窗口
    sys.exit(app.exec_())  # 进入事件循环