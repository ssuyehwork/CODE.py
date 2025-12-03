from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QGridLayout, QPushButton, QLineEdit)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QSettings

class ColorSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("颜色选择")
        self.setMinimumSize(400, 500)
        self.selected_color = None

        # 应用深色主题
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; color: #cdd6f4; }
            QLabel { color: #a6adc8; font-size: 13px; font-weight: bold; margin-top: 10px; }
            QPushButton { border: none; border-radius: 4px; }
            QPushButton:hover { border: 2px solid #89b4fa; }
            QLineEdit {
                background-color: #11111b; border: 1px solid #313244;
                border-radius: 4px; padding: 8px; color: #cdd6f4;
            }
        """)

        self.init_ui()
        self.load_history()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # 1. 推荐颜色 (莫兰迪/柔和色系)
        layout.addWidget(QLabel("🎨 推荐颜色"))
        grid_rec = QGridLayout()
        grid_rec.setSpacing(8)

        rec_colors = [
            "#ffadad", "#ffd6a5", "#fdffb6", "#caffbf", "#9bf6ff", "#a0c4ff", "#bdb2ff", "#ffc6ff",
            "#ef476f", "#ffd166", "#06d6a0", "#118ab2", "#073b4c", "#f72585", "#7209b7", "#3a0ca3"
        ]

        for i, color in enumerate(rec_colors):
            btn = self.create_color_btn(color)
            grid_rec.addWidget(btn, i // 8, i % 8)
        layout.addLayout(grid_rec)

        # 2. 最近使用/常用颜色
        layout.addWidget(QLabel("🕒 最近使用"))
        self.grid_history = QGridLayout()
        self.grid_history.setSpacing(8)
        layout.addLayout(self.grid_history)

        # 3. 自定义颜色
        layout.addWidget(QLabel("✏️ 自定义"))
        custom_layout = QHBoxLayout()
        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("#RRGGBB")
        self.hex_input.textChanged.connect(self.update_preview)
        custom_layout.addWidget(self.hex_input)

        self.preview_btn = QPushButton()
        self.preview_btn.setFixedSize(36, 36)
        self.preview_btn.setStyleSheet("background-color: transparent; border: 1px solid #45475a;")
        custom_layout.addWidget(self.preview_btn)

        btn_pick = QPushButton("调色板")
        btn_pick.setStyleSheet("background-color: #313244; color: white; padding: 8px 12px;")
        btn_pick.clicked.connect(self.open_color_dialog)
        custom_layout.addWidget(btn_pick)

        layout.addLayout(custom_layout)

        layout.addStretch()

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("清除颜色")
        btn_clear.setStyleSheet("background-color: #313244; color: #f38ba8; padding: 8px 16px;")
        btn_clear.clicked.connect(self.clear_color)
        btn_layout.addWidget(btn_clear)

        btn_layout.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: #313244; color: white; padding: 8px 16px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("background-color: #89b4fa; color: #1e1e2e; padding: 8px 16px;")
        btn_ok.clicked.connect(self.accept_custom)
        btn_layout.addWidget(btn_ok)

        layout.addLayout(btn_layout)

    def create_color_btn(self, color):
        btn = QPushButton()
        btn.setFixedSize(32, 32)
        btn.setStyleSheet(f"background-color: {color}; border-radius: 16px;")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.select_color(color))
        return btn

    def load_history(self):
        # 从QSettings加载历史
        settings = QSettings("ClipboardApp", "ColorHistory")
        history = settings.value("colors", [])
        if not history: history = ["#ffffff", "#000000", "#808080"]

        # 清除旧的
        for i in reversed(range(self.grid_history.count())):
            self.grid_history.itemAt(i).widget().setParent(None)

        for i, color in enumerate(history[:16]): # 最多显示16个
            btn = self.create_color_btn(color)
            self.grid_history.addWidget(btn, i // 8, i % 8)

    def save_history(self, color):
        settings = QSettings("ClipboardApp", "ColorHistory")
        history = settings.value("colors", [])
        if color in history: history.remove(color)
        history.insert(0, color)
        settings.setValue("colors", history[:16])

    def select_color(self, color):
        self.selected_color = color
        self.save_history(color)
        self.accept()

    def update_preview(self, text):
        if QColor(text).isValid():
            self.preview_btn.setStyleSheet(f"background-color: {text}; border-radius: 4px;")

    def open_color_dialog(self):
        from PyQt5.QtWidgets import QColorDialog
        color = QColorDialog.getColor()
        if color.isValid():
            self.hex_input.setText(color.name())
            self.selected_color = color.name()

    def accept_custom(self):
        text = self.hex_input.text()
        if QColor(text).isValid():
            self.select_color(text)
        elif self.selected_color:
            self.select_color(self.selected_color)
        else:
            self.reject()

    def clear_color(self):
        self.selected_color = "" # 空字符串表示清除
        self.accept()
