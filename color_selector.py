
# -*- coding: utf-8 -*-
import sys
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                             QPushButton, QGridLayout, QLabel, QFrame, QComboBox, QAction)
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtCore import Qt, QSize, QSettings

class ColorSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_color = ""

        self.setWindowTitle("设置颜色标签")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(320, 250)

        # 使用QSettings来存储和读取历史颜色
        self.settings = QSettings("ClipboardApp", "ColorHistory")

        self.apply_stylesheet()
        self.init_ui()
        self.load_history_colors()

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: "Segoe UI", "Microsoft YaHei";
            }
            QLabel {
                color: #cdd6f4;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#ColorButton {
                width: 32px;
                height: 32px;
                border: 2px solid #45475a;
                border-radius: 16px;
            }
            QPushButton#ColorButton:hover {
                border-color: #89b4fa;
            }
            QPushButton#ActionButton {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 16px;
                color: #cdd6f4;
                font-size: 13px;
            }
            QPushButton#ActionButton:hover {
                background-color: #45475a;
                border-color: #89b4fa;
            }
            QComboBox {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 12px;
                color: #cdd6f4;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #313244;
                border: 1px solid #45475a;
                color: #cdd6f4;
                selection-background-color: #89b4fa;
                selection-color: #11111b;
            }
        """)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # === 常用颜色 ===
        main_layout.addWidget(QLabel("常用颜色"))

        common_colors_layout = QGridLayout()
        common_colors_layout.setSpacing(15)

        self.common_colors = [
            "#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#89b4fa",
            "#cba6f7", "#f5c2e7", "#94e2d5", "#b4befe", "#74c7ec"
        ]

        positions = [(i, j) for i in range(2) for j in range(5)]
        for pos, color in zip(positions, self.common_colors):
            btn = self.create_color_button(color)
            common_colors_layout.addWidget(btn, pos[0], pos[1])

        main_layout.addLayout(common_colors_layout)

        # === 分割线 ===
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #45475a;")
        main_layout.addWidget(line)

        # === 底部操作区 ===
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(15)

        # 历史颜色
        self.history_combo = QComboBox()
        self.history_combo.setObjectName("ActionButton")
        self.history_combo.setIcon(self.create_icon(":/icons/history.png", "🕒"))
        self.history_combo.setItemDelegate(self.history_combo.itemDelegate(self.history_combo))
        self.history_combo.activated.connect(self.on_history_color_selected)
        bottom_layout.addWidget(self.history_combo)

        bottom_layout.addStretch()

        # 清除颜色
        clear_btn = QPushButton("清除颜色")
        clear_btn.setObjectName("ActionButton")
        clear_btn.setIcon(self.create_icon(":/icons/clear.png", "🚫"))
        clear_btn.clicked.connect(self.clear_color)
        bottom_layout.addWidget(clear_btn)

        main_layout.addLayout(bottom_layout)

    def create_color_button(self, color_hex):
        button = QPushButton()
        button.setObjectName("ColorButton")
        button.setStyleSheet(f"background-color: {color_hex};")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: self.select_color(color_hex))
        return button

    def create_icon(self, path, fallback_text):
        """Helper to create an icon, with a text fallback."""
        if QIcon.hasThemeIcon(path):
             return QIcon.fromTheme(path)
        # In a real app, you might use QRC resources. Here we use a fallback.
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.drawText(pixmap.rect(), Qt.AlignCenter, fallback_text)
        p.end()
        return QIcon(pixmap)

    def create_color_icon(self, color_hex, size=16):
        """Creates a square QIcon from a hex color."""
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(color_hex))
        return QIcon(pixmap)

    def select_color(self, color_hex):
        self.selected_color = color_hex
        self.add_color_to_history(color_hex)
        self.accept()

    def clear_color(self):
        self.selected_color = "" # Empty string signifies clearing
        self.accept()

    def add_color_to_history(self, color_hex):
        history = self.settings.value("recentColors", [], type=list)
        if color_hex in history:
            history.remove(color_hex)
        history.insert(0, color_hex)
        # Keep history to a reasonable size, e.g., 10
        history = history[:10]
        self.settings.setValue("recentColors", history)
        self.load_history_colors()

    def load_history_colors(self):
        self.history_combo.clear()
        self.history_combo.addItem("历史颜色")
        history = self.settings.value("recentColors", [], type=list)
        for i, color in enumerate(history):
            self.history_combo.addItem(self.create_color_icon(color), f"  {color.upper()}")
            # Store the color hex in the item's UserRole data
            self.history_combo.setItemData(i + 1, color, Qt.UserRole)

    def on_history_color_selected(self, index):
        # Index 0 is the placeholder "历史颜色"
        if index > 0:
            color = self.history_combo.itemData(index, Qt.UserRole)
            if color:
                self.select_color(color)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    dialog = ColorSelectorDialog()
    if dialog.exec_() == QDialog.Accepted:
        print(f"Selected color: '{dialog.selected_color}'")
    sys.exit(app.exec_())
