# G:\PYthon\AssetManager\ui\styles.py

DARK_THEME = """
/* === 1. 全局架构 === */
QMainWindow {
    background-color: #1e1e1e;
    border: 4px solid #2b2b2b;
}

QWidget {
    color: #cccccc;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 12px;
}

/* === 2. 元数据表格 (重点修复) === */
QTableWidget {
    background-color: #252525;
    alternate-background-color: #2a2a2a; /* 斑马纹颜色 */
    border: none;
    gridline-color: #222;
}

/* 表头 (绝对去白) */
QHeaderView::section {
    background-color: #2d2d2d; /* 深色背景 */
    color: #aaaaaa;            /* 浅色文字 */
    padding: 6px;
    border: none;
    border-bottom: 1px solid #000;
    border-right: 1px solid #000;
}

/* 表格内容项 */
QTableWidget::item {
    padding: 4px;
    color: #ddd;
}

/* 【核心】点击时不显示任何高亮颜色 */
QTableWidget::item:selected {
    background-color: transparent; /* 透明，即保持原背景 */
    color: #ddd;                   /* 保持文字颜色不变 */
    border: none;
}
QTableWidget::item:hover {
    background-color: transparent; /* 甚至悬停也不变色，保持极简 */
}

/* === 3. 核心列表视图 (中间栏 & 左侧栏) === */
/* 这里的选中依然需要高亮，因为要操作文件 */
QTreeView, QListView {
    background-color: #252525;
    border: none;
    outline: none;
    alternate-background-color: #2a2a2a;
}
QTreeView::item, QListView::item { padding: 4px; color: #ccc; }
QTreeView::item:hover, QListView::item:hover {
    background-color: #333;
}
QTreeView::item:selected, QListView::item:selected {
    background-color: #0078d7; /* 只有文件列表保留蓝色高亮 */
    color: white;
}

/* === 4. 标题栏与导航 === */
QFrame#TitleBar { background-color: #1f1f1f; border-bottom: 1px solid #000; }
QFrame#NavBar { background-color: #252525; border-bottom: 1px solid #000; }

QFrame#TitleBar > QToolButton {
    background-color: transparent;
    border: none;
    color: #aaa;
    border-radius: 4px;
}
QFrame#TitleBar > QToolButton:hover { background-color: #333; color: white; }
QToolButton#BtnClose:hover { background-color: #e81123; }
QToolButton#BtnPin:checked { background-color: #383838; border: 1px solid #555; }

QToolButton#BtnBack, QToolButton#BtnFwd, QToolButton#BtnUp {
    background-color: transparent;
    border: none;
    color: #0078d7;
    font-size: 20px;
    font-weight: 900;
}
QToolButton#BtnBack:hover, QToolButton#BtnFwd:hover, QToolButton#BtnUp:hover {
    background-color: #333;
    color: #3399ff;
    border-radius: 4px;
}
QToolButton#BtnBack:disabled, QToolButton#BtnFwd:disabled { color: #004578; }

/* === 5. 面板 === */
QDockWidget { color: #eee; border: 1px solid #000; titlebar-close-icon: url(close.png); margin: 0; }
QDockWidget > QWidget { background-color: #252525; }
QFrame#DockTitleBar { background-color: #2d2d2d; border-bottom: 1px solid #000; }
QToolButton#PanelMenuBtn {
    background-color: transparent;
    border: none;
    color: #999;
    font-weight: bold;
}
QToolButton#PanelMenuBtn:hover { color: white; background-color: #444; }

/* === 6. 其他 === */
QLineEdit#AddressBar {
    background-color: #1f1f1f;
    border: 1px solid #000;
    border-radius: 4px;
    color: #eee;
    padding: 4px 8px;
}
QMenu { background-color: #2d2d2d; border: 1px solid #000; }
QMenu::item { color: #eee; }
QMenu::item:selected { background-color: #0078d7; }

/* 弹窗 */
QDialog { background-color: #1e1e1e; border: 1px solid #333; }
QDialog QLabel { color: #ddd; }
QDialog QLineEdit { background-color: #252525; border: 1px solid #444; color: #fff; padding: 6px; }
QDialog QPushButton { background-color: #333; border: 1px solid #444; color: #eee; padding: 6px 12px; }
QDialog QPushButton:hover { background-color: #444; }
"""

#===================|===================

# G:\PYthon\AssetManager\ui\panels.py

import os
import subprocess
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeView, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView, QMenu, QFileIconProvider
)
from PyQt6.QtCore import Qt, QFileInfo, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QAction

from ui.menus import FavoriteContextMenu

def format_time(timestamp):
    if not timestamp: return "-"
    return time.strftime("%Y/%m/%d %H:%M", time.localtime(timestamp))

# =========================================================
# 1. 收藏夹面板
# =========================================================
class FavoritesListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setStyleSheet("""
            QListWidget { border: none; background-color: #252525; }
            QListWidget::item { height: 32px; padding-left: 8px; color: #ddd; border-bottom: 1px solid #2a2a2a; } 
            QListWidget::item:hover { background-color: #333; } 
            QListWidget::item:selected { background-color: #444; border-left: 3px solid #0078d7; }
        """)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.icon_provider = QFileIconProvider()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path: self.add_favorite(os.path.normpath(path))
            event.acceptProposedAction()
        else: super().dropEvent(event)

    def add_favorite(self, path):
        for i in range(self.count()):
            if self.item(i).data(Qt.ItemDataRole.UserRole) == path: return
        file_info = QFileInfo(path)
        name = file_info.fileName() or path
        item = QListWidgetItem(f"★ {name}")
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setIcon(self.icon_provider.icon(file_info))
        self.addItem(item)

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item: return
        callbacks = {
            "remove": lambda: self.takeItem(self.row(item)),
            "reveal": lambda: self.reveal_in_explorer(item.data(Qt.ItemDataRole.UserRole))
        }
        menu = FavoriteContextMenu(self, callbacks)
        menu.exec(self.mapToGlobal(pos))

    def reveal_in_explorer(self, path):
        if path:
            try: subprocess.run(['explorer', '/select,', path])
            except: pass

class FavoritesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.list_view = FavoritesListWidget()
        layout.addWidget(self.list_view)

# =========================================================
# 2. 元数据面板 (修复斑马纹与选中)
# =========================================================
class MetadataPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        self.table = QTableWidget(9, 2)
        self.table.setHorizontalHeaderLabels(["属性", "值"])
        
        # 表头调整
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setVisible(True) # 确保表头显示
        
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        # 【核心修复】开启斑马纹
        self.table.setAlternatingRowColors(True)
        
        # 【核心修复】虽然开启选中(为了复制)，但我们会通过 CSS 隐藏颜色
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        
        layout.addWidget(self.table)

    def update_info(self, filename, info):
        def set_row(idx, key, val):
            self.table.setItem(idx, 0, QTableWidgetItem(key))
            self.table.setItem(idx, 1, QTableWidgetItem(str(val)))

        set_row(0, "文件名", filename)
        
        ftype = info.get("type")
        if ftype == "folder": ftype_str = "文件夹"
        else: ftype_str = info.get("ext", "未知").upper().replace(".", "") + " 文件"
        set_row(1, "类型", ftype_str)
        
        size = info.get("size", 0)
        if size < 1024: size_str = f"{size} B"
        elif size < 1024**2: size_str = f"{size/1024:.1f} KB"
        else: size_str = f"{size/1024**2:.1f} MB"
        set_row(2, "大小", size_str)
        
        set_row(3, "修改时间", format_time(info.get("mtime")))
        set_row(4, "创建时间", format_time(info.get("ctime")))
        set_row(5, "上次访问", format_time(info.get("atime")))
        
        view_count = info.get("view_count", 0)
        set_row(6, "打开次数", f"{view_count} 次")
        
        rating = info.get("rating", 0)
        set_row(7, "评级", "★" * rating if rating else "无")
        
        tags = info.get("tags", [])
        set_row(8, "标签", ", ".join(tags) if tags else "无")

# =========================================================
# 3. 其他面板
# =========================================================
class FolderPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)

class FilterPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(15)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        
        self.add_category("标签", ["红色", "绿色", "蓝色"])
        self.add_category("评级", ["5 星", "4 星", "未评级"])
        layout.addWidget(self.tree)

    def add_category(self, name, items):
        root = QTreeWidgetItem(self.tree)
        root.setText(0, name)
        root.setExpanded(True)
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        for item_text in items:
            child = QTreeWidgetItem(root)
            child.setText(0, item_text)
            child.setCheckState(0, Qt.CheckState.Unchecked)
