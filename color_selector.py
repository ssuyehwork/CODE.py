# color_selector.py
# -*- coding: utf-8 -*-

import sys
from PyQt5.QtWidgets import (QDialog, QWidget, QGridLayout, QPushButton, QHBoxLayout,
                             QVBoxLayout, QLabel, QFrame, QMenu)
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtCore import Qt, QSize, QSettings

class ColorSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_color = ""
        self.setWindowTitle("设置颜色标签")
        self.setMinimumSize(320, 200)
        self.setModal(True) # 模态对话框

        # 应用与主窗口相似的深色主题
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: "Segoe UI", "Microsoft YaHei";
            }
            QLabel {
                font-size: 14px;
                color: #a6adc8;
                padding-bottom: 5px;
            }
            QPushButton {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 16px;
                color: #cdd6f4;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #45475a;
                border-color: #89b4fa;
            }
            QPushButton#colorBtn {
                border: 2px solid #45475a;
                border-radius: 15px; /* 圆形按钮 */
                width: 30px;
                height: 30px;
                padding: 0;
            }
            QPushButton#colorBtn:hover {
                border-color: #89b4fa;
            }
            QPushButton#clearBtn {
                background-color: #45475a;
            }
            QPushButton#clearBtn:hover {
                background-color: #585b70;
            }
        """)

        self.init_ui()
        self.load_history_colors()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # === 常用颜色 ===
        common_label = QLabel("常用颜色")
        main_layout.addWidget(common_label)

        self.common_colors_layout = QGridLayout()
        self.common_colors_layout.setSpacing(10)

        # 预定义一组柔和且对比度足够的颜色
        self.common_colors = [
            "#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#89b4fa",
            "#cba6f7", "#f5c2e7", "#94e2d5", "#b4befe", "#74c7ec"
        ]

        # 每行最多显示5个颜色
        cols = 5
        for i, color_hex in enumerate(self.common_colors):
            btn = QPushButton()
            btn.setObjectName("colorBtn")
            btn.setFixedSize(30, 30)
            btn.setStyleSheet(f"background-color: {color_hex};")
            btn.setToolTip(color_hex)
            btn.clicked.connect(lambda _, c=color_hex: self.select_color(c))
            self.common_colors_layout.addWidget(btn, i // cols, i % cols)

        main_layout.addLayout(self.common_colors_layout)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #45475a;")
        main_layout.addWidget(separator)

        # === 历史颜色和操作按钮 ===
        bottom_layout = QHBoxLayout()

        # 历史颜色按钮
        self.history_btn = QPushButton("🕓 历史颜色")
        self.history_menu = QMenu(self)
        self.history_menu.setStyleSheet("""
            QMenu {
                background-color: #313244;
                color: white;
                border: 1px solid #45475a;
            }
            QMenu::item:selected {
                background-color: #89b4fa;
                color: #11111b;
            }
        """)
        self.history_btn.setMenu(self.history_menu)
        bottom_layout.addWidget(self.history_btn)

        bottom_layout.addStretch()

        # 清除颜色按钮
        clear_btn = QPushButton("🚫 清除颜色")
        clear_btn.setObjectName("clearBtn")
        clear_btn.clicked.connect(lambda: self.select_color(""))
        bottom_layout.addWidget(clear_btn)

        main_layout.addLayout(bottom_layout)

    def create_color_icon(self, color_hex):
        """创建一个带有颜色圆点的图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 16, 16)
        painter.end()
        return QIcon(pixmap)

    def load_history_colors(self):
        """从QSettings加载历史颜色"""
        settings = QSettings("ClipboardApp", "ColorHistory")
        self.history_colors = settings.value("history", [], type=list)

        self.history_menu.clear()
        for color in self.history_colors:
            if color:
                action = self.history_menu.addAction(color)
                action.setIcon(self.create_color_icon(color))
                action.triggered.connect(lambda _, c=color: self.select_color(c))

    def save_history_colors(self, new_color):
        """保存历史颜色到QSettings"""
        if not new_color or new_color in self.history_colors:
            return

        self.history_colors.insert(0, new_color)
        # 最多保存10个历史颜色
        self.history_colors = self.history_colors[:10]

        settings = QSettings("ClipboardApp", "ColorHistory")
        settings.setValue("history", self.history_colors)

    def select_color(self, color_hex):
        """选择颜色,关闭对话框"""
        self.selected_color = color_hex
        if color_hex: # 只有选择了有效颜色才保存历史
            self.save_history_colors(color_hex)
        self.accept() # 发送Accepted信号并关闭

if __name__ == '__main__':
    # 用于独立测试
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dialog = ColorSelectorDialog()
    if dialog.exec_() == QDialog.Accepted:
        print(f"选择的颜色: '{dialog.selected_color}'")
    sys.exit(app.exec_())
