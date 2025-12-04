# J 监听剪贴板功能主界面.py
# -*- coding: utf-8 -*-
import sys
import os
import hashlib
from datetime import datetime
import ctypes
from ctypes.wintypes import MSG

# === 1. 数据库部分 (保持不变) ===
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Table, Index, Float, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, joinedload

try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                                 QTableWidget, QTableWidgetItem, QHeaderView, 
                                 QComboBox, QAbstractItemView, QShortcut, QInputDialog, 
                                 QMessageBox, QTextEdit, QMenu, QFrame, QScrollArea, 
                                 QDockWidget, QSizePolicy, QSplitter, QDialog, QGridLayout, 
                                 QListWidget, QListWidgetItem, QCheckBox, QSpinBox)
    from PyQt5.QtGui import QKeySequence, QColor, QFont, QIcon, QCursor, QPainter, QPixmap
    from PyQt5.QtCore import Qt, pyqtSlot, QSize, QSettings, QPoint
except ImportError:
    print("请安装库: pip install PyQt5 SQLAlchemy")
    sys.exit(1)

# from color_selector import ColorSelectorDialog # 内容已合并到本文件

Base = declarative_base()

# 关联表
item_tags = Table(
    'item_tags', Base.metadata,
    Column('item_id', Integer, ForeignKey('clipboard_items.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True),
    Index('idx_tag_item', 'tag_id', 'item_id')
)

class ClipboardItem(Base):
    __tablename__ = 'clipboard_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), index=True, unique=True)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    last_visited_at = Column(DateTime, default=datetime.now)
    visit_count = Column(Integer, default=0)
    sort_index = Column(Float, default=0.0)
    star_level = Column(Integer, default=0) 
    is_favorite = Column(Boolean, default=False)
    is_locked = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    group_color = Column(String(20), default=None)  # 分组颜色
    custom_color = Column(String(20), default=None)  # 自定义颜色标签
    is_file = Column(Boolean, default=False)  # 是否为文件
    file_path = Column(Text, default=None)  # 文件路径
    tags = relationship("Tag", secondary=item_tags, back_populates="items")

class Tag(Base):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    items = relationship("ClipboardItem", secondary=item_tags, back_populates="tags")

class DBManager:
    def __init__(self, db_path='sqlite:///clipboard_data.db'):
        if os.path.dirname(sys.argv[0]): os.chdir(os.path.dirname(sys.argv[0]))
        self.engine = create_engine(db_path + "?check_same_thread=False", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._migrate_database()  # 执行数据库迁移
    
    def _migrate_database(self):
        """数据库迁移:添加新字段"""
        import sqlite3
        db_file = 'clipboard_data.db'
        
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            # 检查group_color列是否存在
            cursor.execute("PRAGMA table_info(clipboard_items)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'group_color' not in columns:
                cursor.execute("ALTER TABLE clipboard_items ADD COLUMN group_color VARCHAR(20)")
                conn.commit()
                print("✓ 数据库已更新:添加group_color字段")
            
            conn.close()
        except Exception as e:
            print(f"数据库迁移警告: {e}")
        
        # 添加新字段
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA table_info(clipboard_items)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'custom_color' not in columns:
                cursor.execute("ALTER TABLE clipboard_items ADD COLUMN custom_color VARCHAR(20)")
                print("✓ 数据库已更新:添加custom_color字段")
            
            if 'is_file' not in columns:
                cursor.execute("ALTER TABLE clipboard_items ADD COLUMN is_file BOOLEAN DEFAULT 0")
                print("✓ 数据库已更新:添加is_file字段")
            
            if 'file_path' not in columns:
                cursor.execute("ALTER TABLE clipboard_items ADD COLUMN file_path TEXT")
                print("✓ 数据库已更新:添加file_path字段")
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"数据库迁移警告: {e}")

    def get_session(self): return self.Session()

    def add_item(self, text, is_file=False, file_path=None):
        session = self.get_session()
        try:
            text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
            existing = session.query(ClipboardItem).filter_by(content_hash=text_hash).first()
            if existing:
                existing.last_visited_at = datetime.now()
                existing.visit_count += 1
                session.commit()
                return existing, False
            
            min_sort = session.query(ClipboardItem).order_by(ClipboardItem.sort_index.asc()).first()
            new_sort = (min_sort.sort_index - 1.0) if min_sort else 0.0
            
            # 自动提取首行到备注
            auto_note = ""
            if is_file and file_path:
                auto_note = os.path.basename(file_path)
            else:
                first_line = text.split('\n')[0].strip()
                auto_note = first_line[:100] if first_line else ""
            
            new_item = ClipboardItem(
                content=text, 
                content_hash=text_hash, 
                sort_index=new_sort,
                note=auto_note,
                is_file=is_file,
                file_path=file_path
            )
            session.add(new_item)
            session.commit()
            session.refresh(new_item)
            return new_item, True
        except: session.rollback(); return None, False
        finally: session.close()

    def get_all_items(self, filter_type=None, search_key="", sort_by="manual"):
        session = self.get_session()
        try:
            query = session.query(ClipboardItem).options(joinedload(ClipboardItem.tags))
            if filter_type == "favorite": query = query.filter(ClipboardItem.is_favorite == True)
            elif filter_type == "locked": query = query.filter(ClipboardItem.is_locked == True)
            if search_key:
                query = query.filter(ClipboardItem.content.like(f"%{search_key}%") | ClipboardItem.note.like(f"%{search_key}%"))
            
            # 排序逻辑
            if sort_by == "manual": query = query.order_by(ClipboardItem.is_pinned.desc(), ClipboardItem.sort_index.asc())
            elif sort_by == "time_desc": query = query.order_by(ClipboardItem.is_pinned.desc(), ClipboardItem.created_at.desc())
            elif sort_by == "visit_desc": query = query.order_by(ClipboardItem.is_pinned.desc(), ClipboardItem.visit_count.desc())
            elif sort_by == "stars_desc": query = query.order_by(ClipboardItem.is_pinned.desc(), ClipboardItem.star_level.desc())
            elif sort_by == "size_desc": 
                from sqlalchemy import func
                query = query.order_by(ClipboardItem.is_pinned.desc(), func.length(ClipboardItem.content).desc())
            return query.limit(200).all()
        finally: session.close()

    def get_tag_cloud(self):
        """核心新增：获取标签云数据 (标签名, 引用计数)"""
        session = self.get_session()
        try:
            # SQL: SELECT name, count(item_id) FROM tags JOIN item_tags GROUP BY tags.id ORDER BY count DESC
            results = session.query(Tag.name, func.count(item_tags.c.item_id).label('count'))\
                .join(item_tags)\
                .group_by(Tag.id)\
                .order_by(func.count(item_tags.c.item_id).desc())\
                .all()
            return results # List of (name, count)
        finally:
            session.close()

    def update_sort_order(self, ids):
        session = self.get_session()
        try:
            for idx, item_id in enumerate(ids):
                item = session.query(ClipboardItem).get(item_id)
                if item: item.sort_index = float(idx)
            session.commit()
        finally: session.close()

    def update_field(self, item_id, field, value):
        session = self.get_session()
        try:
            item = session.query(ClipboardItem).get(item_id)
            if item: setattr(item, field, value); session.commit(); return True
            return False
        finally: session.close()

    def delete_item(self, item_id):
        session = self.get_session()
        try:
            item = session.query(ClipboardItem).get(item_id)
            if item:
                if item.is_locked: return False, "数据被【禁删】保护，请先解锁。"
                session.delete(item); session.commit(); return True, "已删除"
            return False, "数据不存在"
        finally: session.close()

    def remove_tag_from_item(self, item_id, tag_name):
        session = self.get_session()
        try:
            item = session.query(ClipboardItem).get(item_id)
            tag = session.query(Tag).filter_by(name=tag_name).first()
            if item and tag and tag in item.tags: item.tags.remove(tag); session.commit()
        finally: session.close()
            
    def add_tags_to_items(self, item_ids, tag_name):
        session = self.get_session()
        try:
            tag = session.query(Tag).filter_by(name=tag_name).first()
            if not tag: tag = Tag(name=tag_name); session.add(tag)
            items = session.query(ClipboardItem).filter(ClipboardItem.id.in_(item_ids)).all()
            for item in items:
                if tag not in item.tags: item.tags.append(tag)
            session.commit()
        except: session.rollback()
        finally: session.close()
    
    def auto_delete_old_data(self, days=21):
        """自动删除21天前的数据(保留锁定的)"""
        from datetime import timedelta
        session = self.get_session()
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            old_items = session.query(ClipboardItem).filter(
                ClipboardItem.created_at < cutoff_date,
                ClipboardItem.is_locked == False
            ).all()
            count = len(old_items)
            for item in old_items:
                session.delete(item)
            session.commit()
            return count
        except:
            session.rollback()
            return 0
        finally:
            session.close()

# === 2. 可拖拽表格 (已修复闪退和排序问题) ===
class DraggableTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)  # 支持多选
        # 显示插入位置指示器
        self.setDropIndicatorShown(True)

    def dropEvent(self, event):
        # 如果不是来自本表格的拖拽，调用父类默认处理
        if event.source() != self:
            super().dropEvent(event)
            return

        # 1. 获取源行和目标位置
        source_row = self.currentRow()
        target_index = self.indexAt(event.pos())
        target_row = target_index.row()

        # 如果拖到了空白处，默认放到最后一行
        if target_row == -1:
            target_row = self.rowCount() - 1

        if source_row == target_row:
            return

        # 2. 手动执行移动操作 (避免使用默认dropEvent导致的崩溃)
        # 取出源行数据
        row_items = []
        for col in range(self.columnCount()):
            row_items.append(self.takeItem(source_row, col))

        # 移除源行
        self.removeRow(source_row)

        # 如果源行在目标行上方，移除源行后，目标行索引会前移，需要修正
        if source_row < target_row:
            target_row -= 1
        
        # 插入新行
        self.insertRow(target_row)
        
        # 填回数据
        for col, item in enumerate(row_items):
            self.setItem(target_row, col, item)

        # 选中新位置
        self.selectRow(target_row)

        # 3. 更新界面序号并收集新的ID顺序
        new_order_ids = []
        for row in range(self.rowCount()):
            # 更新显示的序号列 (第0列)
            item_idx = self.item(row, 0)
            if item_idx:
                item_idx.setText(str(row + 1))
            
            # 收集隐藏的ID列 (第9列)
            id_item = self.item(row, 9) 
            if id_item: 
                new_order_ids.append(int(id_item.text()))
        
        # 4. 通知主窗口更新数据库
        mw = self.window()
        if hasattr(mw, 'update_db_order'): 
            mw.update_db_order(new_order_ids)
        
        # 5. 立即刷新数据并选中移动后的行
        if hasattr(mw, 'load_data'):
            # 获取移动后的项目id
            moved_id = new_order_ids[target_row] if target_row < len(new_order_ids) else None
            mw.load_data(select_id=moved_id)

        event.accept()

# === 3. 现代化标签选择对话框 ===
class TagSelectorDialog(QDialog):
    def __init__(self, db_manager, current_item_id, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.current_item_id = current_item_id
        self.view_mode = "list"  # list 或 grid
        self.show_frequent = True
        self.show_recent = True
        self.show_recommended = True
        self.max_display = 50
        
        self.setWindowTitle("标签管理")
        self.setMinimumSize(450, 550)
        self.setModal(False)  # 非模态对话框
        
        # 应用深色主题
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QLineEdit {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 8px 12px;
                color: #cdd6f4;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #89b4fa;
            }
            QListWidget {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 5px;
                outline: none;
            }
            QListWidget::item {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 8px 12px;
                margin: 3px;
                color: #cdd6f4;
            }
            QListWidget::item:hover {
                background-color: #313244;
                border-color: #89b4fa;
            }
            QListWidget::item:selected {
                background-color: #89b4fa;
                color: #11111b;
                border-color: #89b4fa;
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
            QPushButton:pressed {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
            QPushButton#iconBtn {
                background-color: transparent;
                border: none;
                padding: 4px;
            }
            QPushButton#iconBtn:hover {
                background-color: #313244;
            }
            QLabel {
                color: #a6adc8;
                font-size: 12px;
            }
            QLabel#titleLabel {
                color: #cdd6f4;
                font-size: 14px;
                font-weight: bold;
            }
            QCheckBox {
                color: #cdd6f4;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #313244;
                background-color: #11111b;
            }
            QCheckBox::indicator:checked {
                background-color: #89b4fa;
                border-color: #89b4fa;
            }
            QCheckBox::indicator:hover {
                border-color: #89b4fa;
            }
        """)
        
        self.init_ui()
        self.load_tags()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)
        
        # 顶部工具栏
        toolbar = QHBoxLayout()
        
        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索...")
        self.search_input.textChanged.connect(self.filter_tags)
        self.search_input.returnPressed.connect(self.add_tag_from_search)  # 回车添加
        toolbar.addWidget(self.search_input)
        
        # 视图切换按钮
        btn_list_view = QPushButton("☰")
        btn_list_view.setObjectName("iconBtn")
        btn_list_view.setToolTip("列表视图")
        btn_list_view.clicked.connect(lambda: self.switch_view("list"))
        toolbar.addWidget(btn_list_view)
        
        btn_grid_view = QPushButton("⊞")
        btn_grid_view.setObjectName("iconBtn")
        btn_grid_view.setToolTip("网格视图")
        btn_grid_view.clicked.connect(lambda: self.switch_view("grid"))
        toolbar.addWidget(btn_grid_view)
        
        # 设置按钮
        btn_settings = QPushButton("⚙")
        btn_settings.setObjectName("iconBtn")
        btn_settings.setToolTip("设置")
        btn_settings.clicked.connect(self.show_settings)
        toolbar.addWidget(btn_settings)
        
        layout.addLayout(toolbar)
        
        # 标签列表
        self.tag_list = QListWidget()
        self.tag_list.itemDoubleClicked.connect(self.add_tag_from_list)
        layout.addWidget(self.tag_list)
        
        # 底部提示
        hint_label = QLabel("💡 提示: 双击标签添加 | 回车键快速添加 | ESC关闭")
        hint_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(hint_label)
    
    def load_tags(self):
        """加载所有标签,适配不同视图"""
        self.tag_list.clear()
        tags_data = self.db.get_tag_cloud()
        
        # 根据设置过滤和排序
        filtered_tags = []
        for name, count in tags_data:
            if len(filtered_tags) >= self.max_display:
                break
            filtered_tags.append((name, count))
        
        for name, count in filtered_tags:
            if self.view_mode == "grid":
                item = QListWidgetItem(name)
                item.setToolTip(f"{name} ({count}次引用)")
                item.setTextAlignment(Qt.AlignCenter)
            else: # list
                item = QListWidgetItem(f"🏷️ {name}  ({count})")
            
            item.setData(Qt.UserRole, name)
            self.tag_list.addItem(item)
            
        # 重新应用搜索过滤器
        self.filter_tags(self.search_input.text())
    
    def filter_tags(self, text):
        """根据搜索文本过滤标签"""
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            tag_name = item.data(Qt.UserRole)
            item.setHidden(text.lower() not in tag_name.lower())
    
    def add_tag_from_search(self):
        """从搜索框添加标签(回车键)"""
        tag_name = self.search_input.text().strip()
        if not tag_name:
            return
        
        # 添加标签到当前项目
        self.db.add_tags_to_items([self.current_item_id], tag_name)
        
        # 清空搜索框
        self.search_input.clear()
        
        # 刷新列表
        self.load_tags()
        
        # 通知父窗口更新
        if self.parent():
            self.parent().update_dock_panel()
            self.parent().refresh_tag_cloud()
    
    def add_tag_from_list(self, item):
        """从列表添加标签(双击)"""
        tag_name = item.data(Qt.UserRole)
        self.db.add_tags_to_items([self.current_item_id], tag_name)
        
        # 通知父窗口更新
        if self.parent():
            self.parent().update_dock_panel()
            self.parent().refresh_tag_cloud()
    
    def switch_view(self, mode):
        """切换视图模式"""
        if self.view_mode == mode: return
        self.view_mode = mode
        
        if mode == "grid":
            self.tag_list.setViewMode(QListWidget.IconMode)
            self.tag_list.setFlow(QListWidget.LeftToRight)
            self.tag_list.setWrapping(True)
            self.tag_list.setResizeMode(QListWidget.Adjust)
            self.tag_list.setGridSize(QSize(100, 40))
            self.tag_list.setMovement(QListWidget.Static)
            self.tag_list.setSpacing(5)
        else: # "list"
            self.tag_list.setViewMode(QListWidget.ListMode)
            # 恢复默认设置
            self.tag_list.setGridSize(QSize(-1, -1))
            self.tag_list.setWrapping(False)
        
        self.load_tags()
    
    def show_settings(self):
        """显示设置面板"""
        settings_dialog = QDialog(self)
        settings_dialog.setWindowTitle("标签设置")
        settings_dialog.setMinimumSize(300, 250)
        settings_dialog.setStyleSheet(self.styleSheet())
        
        layout = QVBoxLayout(settings_dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题
        title = QLabel("列表")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        
        # 选项
        cb_frequent = QCheckBox("常用标签")
        cb_frequent.setChecked(self.show_frequent)
        cb_frequent.stateChanged.connect(lambda s: setattr(self, 'show_frequent', s == 2))
        layout.addWidget(cb_frequent)
        
        cb_recent = QCheckBox("最近使用")
        cb_recent.setChecked(self.show_recent)
        cb_recent.stateChanged.connect(lambda s: setattr(self, 'show_recent', s == 2))
        layout.addWidget(cb_recent)
        
        cb_recommended = QCheckBox("推荐")
        cb_recommended.setChecked(self.show_recommended)
        cb_recommended.stateChanged.connect(lambda s: setattr(self, 'show_recommended', s == 2))
        layout.addWidget(cb_recommended)
        
        # 显示数量
        layout.addWidget(QLabel("显示数量"))
        spin_max = QSpinBox()
        spin_max.setRange(10, 200)
        spin_max.setValue(self.max_display)
        spin_max.valueChanged.connect(lambda v: setattr(self, 'max_display', v))
        layout.addWidget(spin_max)
        
        layout.addStretch()
        
        # 确定按钮
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(settings_dialog.accept)
        layout.addWidget(btn_ok)
        
        if settings_dialog.exec_() == QDialog.Accepted:
            self.load_tags()
    
    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

# === 4. 主界面 ===
class ClipboardApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DBManager()
        self.last_clipboard_text = ""
        self.monitor_enabled = True
        self.drag_start_position = None

        self.setWindowTitle("印象记忆_Dark (标签云增强版)")
        self.resize(1300, 850)
        
        # 设置无边框窗口
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 启用鼠标追踪以支持边缘调整大小
        self.setMouseTracking(True)
        self.resize_margin = 5  # 边缘调整区域大小
        self.resize_direction = None  # 当前调整方向
        self.drag_start_position = None

        self.apply_style()

        # === 核心布局 ===
        self.central_container = QWidget()
        self.central_container.setObjectName("centralContainer")
        self.setCentralWidget(self.central_container)
        self.central_layout = QVBoxLayout(self.central_container)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.central_layout.setSpacing(0)

        # 已使用的颜色集合
        self.used_colors = set()
        
        # 编辑模式标志（必须在restore_window_state之前定义）
        self.edit_mode = False  # False=读取模式, True=编辑模式
        
        self.init_title_bar()  # 初始化自定义标题栏
        self.init_top_bar()
        self.init_table()
        self.init_metadata_panel()
        self.init_tag_panel()
        
        # 添加右下角调整大小手柄
        from PyQt5.QtWidgets import QSizeGrip
        self.size_grip = QSizeGrip(self.central_container)
        self.size_grip.setFixedSize(16, 16)
        # 将手柄放置在右下角
        self.size_grip.setStyleSheet("""
            QSizeGrip {
                background-color: transparent;
                image: url(none);
            }
        """)
        # 使用布局将手柄固定在右下角
        self.size_grip.raise_()
        
        # 恢复窗口状态（必须在edit_mode定义之后，但在load_data之前）
        self.restore_window_state()
        
        self.load_data()

        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self.on_clipboard_change)
        
        self.group_shortcut = QShortcut(QKeySequence("Ctrl+G"), self)
        self.group_shortcut.activated.connect(self.group_selected_items)
        
        # 添加保存定时器，避免频繁保存
        from PyQt5.QtCore import QTimer
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_window_state)
        self.save_timer.timeout.connect(self.save_window_state)
        self.save_timer.setInterval(500)  # 500ms后保存

        # === 焦点追踪 (用于双击粘贴) ===
        self.last_external_hwnd = None
        self.focus_timer = QTimer()
        self.focus_timer.timeout.connect(self.track_active_window)
        self.focus_timer.start(200) # 每200ms记录一次当前活动窗口

    def track_active_window(self):
        """追踪并记录最后一个非本程序的活动窗口"""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            # 如果当前活动窗口不是本程序，则记录下来
            if hwnd and hwnd != int(self.winId()):
                self.last_external_hwnd = hwnd
        except Exception:
            pass

    def nativeEvent(self, eventType, message):
        """使用Windows原生消息处理窗口大小调整和移动"""
        if eventType == "windows_generic_MSG":
            msg = MSG.from_address(message.__int__())
            if msg.message == 0x0084: # WM_NCHITTEST
                x = msg.lParam & 0xFFFF
                y = msg.lParam >> 16
                pos = self.mapFromGlobal(QPoint(x, y))
                x = pos.x()
                y = pos.y()
                w = self.width()
                h = self.height()
                m = self.resize_margin
                
                # 边缘检测
                is_left = x < m
                is_right = x > w - m
                is_top = y < m
                is_bottom = y > h - m
                
                if is_top and is_left: return True, 13 # HTTOPLEFT
                if is_top and is_right: return True, 14 # HTTOPRIGHT
                if is_bottom and is_left: return True, 16 # HTBOTTOMLEFT
                if is_bottom and is_right: return True, 17 # HTBOTTOMRIGHT
                if is_left: return True, 10 # HTLEFT
                if is_right: return True, 11 # HTRIGHT
                if is_top: return True, 12 # HTTOP
                if is_bottom: return True, 15 # HTBOTTOM
                
                # 标题栏拖动检测
                # 如果鼠标在标题栏范围内，且没有悬停在按钮上，则允许拖动
                if self.title_bar.geometry().contains(pos):
                    child = self.childAt(pos)
                    # 如果直接点在标题栏上，或者点在Label上，允许拖动
                    # 如果点在按钮上(QPushButton)，则不处理，交给Qt
                    if child == self.title_bar or isinstance(child, QLabel):
                        return True, 2 # HTCAPTION
                        
        return super().nativeEvent(eventType, message)

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #11111b; } /* 极深色背景 */
            QWidget { color: #cdd6f4; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 13px; }
            
            /* Dock 面板无边框 */
            QDockWidget {
                border: none;
                titlebar-close-icon: none;
                titlebar-normal-icon: none;
            }
            QDockWidget::title { 
                background: #181825; 
                padding-left: 5px; 
                padding-top: 4px; 
                border: none;
            }
            
            /* 输入框彻底去除白色 */
            QLineEdit, QScrollArea { 
                background-color: #1e1e2e; /* 深灰背景 */
                border: 1px solid #313244; 
                border-radius: 4px; 
                color: #cdd6f4; 
            }
            QTextEdit { 
                background-color: #262637; /* 预览框更深的背景 */
                border: 1px solid #313244; 
                border-radius: 4px; 
                color: #cdd6f4; 
            }
            QLineEdit:focus, QTextEdit:focus { border: 1px solid #89b4fa; }

            /* 按钮样式 */
            QPushButton { background-color: #313244; border: 1px solid #45475a; border-radius: 4px; padding: 4px; }
            QPushButton:hover { background-color: #45475a; border-color: #89b4fa; }
            QPushButton:pressed { background-color: #89b4fa; color: #1e1e2e; }
            
            /* 标题栏按钮专用样式 - 扁平化设计 */
            #titleBarButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 2px;
                font-size: 20px; /* 更大的图标 */
            }
            #titleBarButton:hover {
                background-color: rgba(255, 255, 255, 0.1); /* 只有悬停时显示背景 */
            }
            #titleBarButton:checked {
                background-color: rgba(137, 180, 250, 0.2); /* 选中状态 */
                color: #89b4fa;
            }
            #titleBarButton:pressed {
                background-color: rgba(255, 255, 255, 0.15);
            }

            /* 标签按钮 */
            QPushButton#TagCloudBtn { 
                background-color: #181825; 
                border: 1px solid #585b70; 
                border-radius: 12px; 
                padding: 4px 10px; 
                font-size: 12px;
                text-align: left;
            }
            QPushButton#TagCloudBtn:hover { border-color: #89b4fa; color: #fff; background-color: #313244; }

            /* 表格 */
            QTableWidget { background-color: #11111b; alternate-background-color: #181825; border: none; gridline-color: #1e1e2e; selection-background-color: #313244; selection-color: #89b4fa; }
            QHeaderView::section { background-color: #181825; color: #a6adc8; border: none; padding: 6px; font-weight: bold; }
            
            /* 自定义标题栏 */
            #titleBar {
                background-color: #181825;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            #centralContainer {
                background-color: #11111b;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            #titleLabel {
                font-weight: bold;
                padding-left: 5px;
            }
            
            /* 标题栏按钮 */
            #titleBarButton, #minimizeButton, #maximizeButton, #closeButton {
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: #cdd6f4;
            }
            #titleBarButton:hover, #minimizeButton:hover, #maximizeButton:hover {
                background-color: #313244;
            }
            #closeButton:hover {
                background-color: #f38ba8; /* 红色 */
                color: #11111b;
            }
        """)

    def init_title_bar(self):
        """初始化自定义标题栏"""
        self.title_bar = QWidget()
        self.title_bar.setObjectName("titleBar")
        self.title_bar.setFixedHeight(36) # 调整高度为36
        self.title_bar_layout = QHBoxLayout(self.title_bar)
        self.title_bar_layout.setContentsMargins(5, 0, 5, 0)
        self.title_bar_layout.setSpacing(10)

        # 应用图标
        self.icon_label = QLabel()
        # 注意: 这里需要一个有效的图标路径, 暂时使用占位符. 后面需要创建资源文件.
        # icon_pixmap = QPixmap(":/icons/app_icon.png").scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # self.icon_label.setPixmap(icon_pixmap)
        self.icon_label.setText("💾") # 临时图标
        self.title_bar_layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        # 标题
        self.title_label = QLabel("印象记忆_Dark")
        self.title_label.setObjectName("titleLabel")
        self.title_bar_layout.addWidget(self.title_label, 0, Qt.AlignVCenter)
        
        # 添加伸缩, 将按钮推到右侧
        self.title_bar_layout.addStretch()
        
        # --- 功能按钮 ---
        # 刷新按钮
        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setObjectName("titleBarButton")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setToolTip("刷新数据")
        self.btn_refresh.clicked.connect(lambda: self.load_data())
        self.title_bar_layout.addWidget(self.btn_refresh, 0, Qt.AlignVCenter)

        # 自动删除按钮
        self.btn_auto_delete = QPushButton("🗑️")
        self.btn_auto_delete.setObjectName("titleBarButton")
        self.btn_auto_delete.setFixedSize(32, 32)
        self.btn_auto_delete.setToolTip("清理数据")
        self.btn_auto_delete.clicked.connect(self.auto_delete_old_items)
        self.title_bar_layout.addWidget(self.btn_auto_delete, 0, Qt.AlignVCenter)

        # 置顶按钮
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setObjectName("titleBarButton")
        self.btn_pin.setFixedSize(32, 32)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("置顶窗口")
        self.btn_pin.clicked.connect(self.toggle_always_on_top)
        self.title_bar_layout.addWidget(self.btn_pin, 0, Qt.AlignVCenter)

        # 设置颜色按钮
        self.btn_set_color = QPushButton("🎨")
        self.btn_set_color.setObjectName("titleBarButton")
        self.btn_set_color.setFixedSize(32, 32)
        self.btn_set_color.setToolTip("设置颜色")
        self.btn_set_color.clicked.connect(self.toolbar_set_color)
        self.title_bar_layout.addWidget(self.btn_set_color, 0, Qt.AlignVCenter)

        # 模式切换按钮
        self.mode_btn = QPushButton("📖")
        self.mode_btn.setObjectName("titleBarButton")
        self.mode_btn.setFixedSize(32, 32)
        self.mode_btn.setCheckable(True)
        self.mode_btn.setToolTip("切换读/写模式")
        self.mode_btn.clicked.connect(self.toggle_edit_mode)
        self.title_bar_layout.addWidget(self.mode_btn, 0, Qt.AlignVCenter)

        # 添加一个小的分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(20) # 设置固定高度
        separator.setStyleSheet("color: #45475a;")
        self.title_bar_layout.addWidget(separator, 0, Qt.AlignVCenter)

        # 窗口控制按钮
        self.minimize_button = QPushButton("—")
        self.minimize_button.setObjectName("minimizeButton")
        self.minimize_button.setFixedSize(32, 32)
        self.minimize_button.setToolTip("最小化")
        self.minimize_button.clicked.connect(self.showMinimized)

        self.maximize_button = QPushButton("⃞")
        self.maximize_button.setObjectName("maximizeButton")
        self.maximize_button.setFixedSize(32, 32)
        self.maximize_button.setToolTip("最大化")
        self.maximize_button.clicked.connect(self.toggle_maximize)

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.setFixedSize(32, 32)
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(self.close)

        self.title_bar_layout.addWidget(self.minimize_button, 0, Qt.AlignVCenter)
        self.title_bar_layout.addWidget(self.maximize_button, 0, Qt.AlignVCenter)
        self.title_bar_layout.addWidget(self.close_button, 0, Qt.AlignVCenter)

        self.central_layout.addWidget(self.title_bar)

    def init_top_bar(self):
        top_frame = QFrame()
        top_frame.setFixedHeight(40) # 减小高度
        top_frame.setStyleSheet("background-color: #181825; border-bottom: 1px solid #313244;")
        layout = QHBoxLayout(top_frame)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索...")
        self.search_input.setFixedWidth(250)
        self.search_input.returnPressed.connect(lambda: self.load_data())
        layout.addWidget(self.search_input)

        layout.addWidget(QLabel(" | 筛选: "))
        self.btn_all = QPushButton("全部"); self.btn_all.setCheckable(True); self.btn_all.setChecked(True)
        self.btn_fav = QPushButton("仅收藏"); self.btn_fav.setCheckable(True)
        self.btn_lock = QPushButton("仅禁删"); self.btn_lock.setCheckable(True)
        
        for btn in [self.btn_all, self.btn_fav, self.btn_lock]:
            btn.clicked.connect(lambda _, b=btn: self.switch_filter(b))
            layout.addWidget(btn)
        
        layout.addStretch()
        layout.addWidget(QLabel("排序:"))
        self.sort_combo = QComboBox()
        self.sort_combo.setStyleSheet("background-color: #313244; color: white;")
        self.sort_combo.addItems(["✋ 手动拖拽", "🕒 创建时间", "💾 大小", "🔥 热度", "⭐ 星级"])
        self.sort_map = {0: "manual", 1: "time_desc", 2: "size_desc", 3: "visit_desc", 4: "stars_desc"}
        self.sort_combo.currentIndexChanged.connect(lambda: self.load_data())
        layout.addWidget(self.sort_combo)

        self.central_layout.addWidget(top_frame)
        self.current_filter = None

    def init_table(self):
        self.table = DraggableTableWidget()
        cols = ["序", "状态", "备注", "星级", "大小", "访问", "创建时间", "访问时间", "内容", "ID"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setColumnHidden(9, True)
        
        w = self.table.setColumnWidth
        w(0, 40); w(1, 50); w(2, 120); w(3, 60); w(4, 70); w(5, 40); w(6, 140); w(7, 140)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemSelectionChanged.connect(self.update_dock_panel)
        self.table.itemDoubleClicked.connect(self.on_table_double_click)  # 双击事件
        self.table.itemChanged.connect(self.on_item_changed) # 编辑持久化
        self.table.setAlternatingRowColors(True)
        
        # 表头右键菜单
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_menu)
        
        # 监听列宽变化以自动保存
        self.table.horizontalHeader().sectionResized.connect(self.on_column_resized)
        
        # 双击粘贴功能
        self.table.doubleClicked.connect(self.paste_to_previous_window)
        
        self.central_layout.addWidget(self.table)

    def init_metadata_panel(self):
        """创建元数据面板"""
        self.metadata_dock = QDockWidget("📊 元数据", self)
        self.metadata_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)  # 禁止停靠到顶部
        self.metadata_dock.setFeatures(QDockWidget.DockWidgetMovable)  # 只允许移动，不允许浮动
        
        metadata_content = QWidget()
        metadata_content.setStyleSheet("background-color: #11111b;")
        layout = QVBoxLayout(metadata_content)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 使用QSplitter使预览框可调整大小
        splitter = QSplitter(Qt.Vertical)
        
        # 内容预览
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(100)
        splitter.addWidget(self.preview_text)
        
        # 下半部分容器
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        # 提取内容按钮
        btn_copy = QPushButton("提取内容")
        btn_copy.clicked.connect(self.extract_content)
        bottom_layout.addWidget(btn_copy)
        
        bottom_layout.addSpacing(15)
        
        # 备注
        bottom_layout.addWidget(QLabel("📝 备注"))
        self.note_input = QLineEdit()
        self.note_input.returnPressed.connect(self.save_note)
        bottom_layout.addWidget(self.note_input)
        
        bottom_layout.addStretch()
        
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 3)  # 预览框占3份
        splitter.setStretchFactor(1, 2)  # 下半部分占2份
        
        layout.addWidget(splitter)
        
        self.metadata_dock.setWidget(metadata_content)
        self.addDockWidget(Qt.RightDockWidgetArea, self.metadata_dock)
        self.metadata_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        
        # 监听Dock面板位置变化
        self.metadata_dock.dockLocationChanged.connect(self.schedule_save_window_state)
    
    def init_tag_panel(self):
        """创建标签面板"""
        self.tag_dock = QDockWidget("🏷️ 标签", self)
        self.tag_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)  # 禁止停靠到顶部
        self.tag_dock.setFeatures(QDockWidget.DockWidgetMovable)  # 只允许移动，不允许浮动
        
        tag_content = QWidget()
        tag_content.setStyleSheet("background-color: #11111b;")
        layout = QVBoxLayout(tag_content)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 当前标签区域
        layout.addWidget(QLabel("当前标签:"))
        self.current_tag_area = QWidget()
        self.current_tag_layout = QHBoxLayout(self.current_tag_area)
        self.current_tag_layout.setContentsMargins(0, 0, 0, 0)
        self.current_tag_layout.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.current_tag_area)
        
        layout.addSpacing(15)
        
        # 标签云/历史标签
        layout.addWidget(QLabel("📚 标签库 (点击添加):"))
        self.tag_cloud_area = QScrollArea()
        self.tag_cloud_area.setWidgetResizable(True)
        self.tag_cloud_container = QWidget()
        self.tag_cloud_layout = QVBoxLayout(self.tag_cloud_container)
        self.tag_cloud_layout.setAlignment(Qt.AlignTop)
        self.tag_cloud_area.setWidget(self.tag_cloud_container)
        layout.addWidget(self.tag_cloud_area)
        
        # 添加新标签按钮
        btn_new_tag = QPushButton("+ 新建标签")
        btn_new_tag.clicked.connect(self.add_tag_action)
        layout.addWidget(btn_new_tag)
        
        self.tag_dock.setWidget(tag_content)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tag_dock)
        self.tag_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        
        # 监听Dock面板位置变化
        self.tag_dock.dockLocationChanged.connect(self.schedule_save_window_state)

    # === 逻辑部分 ===
    def switch_filter(self, btn):
        self.btn_all.setChecked(False); self.btn_fav.setChecked(False); self.btn_lock.setChecked(False)
        btn.setChecked(True)
        if btn == self.btn_fav: self.current_filter = "favorite"
        elif btn == self.btn_lock: self.current_filter = "locked"
        else: self.current_filter = None
        self.load_data()

    def format_size(self, text):
        b = len(text.encode('utf-8'))
        if b < 1024: return f"{b} B"
        elif b < 1024**2: return f"{b/1024:.1f} KB"
        return f"{b/1024**2:.1f} MB"

    def load_data(self, select_id=None):
        """加载数据,并可选择性地选中指定id的项目"""
        self.table.blockSignals(True) # 加载数据前阻塞信号
        search = self.search_input.text().strip()
        sort = self.sort_map.get(self.sort_combo.currentIndex(), "manual")
        items = self.db.get_all_items(self.current_filter, search, sort)
        self.table.setRowCount(0)
        
        select_row = -1
        for i, item in enumerate(items):
            self.insert_row(item, i+1)
            if select_id and item.id == select_id:
                select_row = i
        
        self.refresh_tag_cloud()
        
        # 选中指定行
        if select_row >= 0:
            self.table.selectRow(select_row)
            self.table.scrollToItem(self.table.item(select_row, 0))
        
        self.table.blockSignals(False) # 完成后恢复信号

    def insert_row(self, item, idx):
        r = self.table.rowCount(); self.table.insertRow(r)
        
        # 序号
        seq_item = QTableWidgetItem(str(idx))
        seq_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 0, seq_item)
        
        # 状态
        status = ""
        if item.is_pinned: status += "📌"
        if item.is_favorite: status += "❤️"
        if item.is_locked: status += "🔒"
        status_item = QTableWidgetItem(status)

        # 优先使用自定义颜色,否则使用分组颜色
        display_color = item.custom_color or item.group_color
        if display_color:
            status_item.setIcon(self.create_color_icon(display_color))
        
        status_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 1, status_item)
        
        # 备注
        display_note = f"📄 {item.note}" if item.is_file else item.note
        note_item = QTableWidgetItem(display_note)
        self.table.setItem(r, 2, note_item)
        
        # 星级 - 使用金色★符号
        stars = "★" * item.star_level if item.star_level > 0 else ""
        star_item = QTableWidgetItem(stars)
        star_item.setTextAlignment(Qt.AlignCenter)
        star_item.setForeground(QColor("#FFD700"))  # 金色
        self.table.setItem(r, 3, star_item)
        
        # 大小
        size_item = QTableWidgetItem(self.format_size(item.content))
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(r, 4, size_item)
        
        # 访问次数
        visit_item = QTableWidgetItem(str(item.visit_count))
        visit_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 5, visit_item)
        
        # 创建时间 - 精确到秒
        created_item = QTableWidgetItem(item.created_at.strftime("%Y-%m-%d %H:%M:%S"))
        self.table.setItem(r, 6, created_item)
        
        # 访问时间 - 精确到秒
        visited_item = QTableWidgetItem(item.last_visited_at.strftime("%Y-%m-%d %H:%M:%S") if item.last_visited_at else "")
        self.table.setItem(r, 7, visited_item)
        
        # 内容
        display_content = f"[文件] {item.content}" if item.is_file else item.content
        content_item = QTableWidgetItem(display_content[:60].replace('\n', ' '))
        self.table.setItem(r, 8, content_item)
        
        # ID(隐藏)
        id_item = QTableWidgetItem(str(item.id))
        self.table.setItem(r, 9, id_item)

    def show_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid(): return

        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return

        item_ids = [int(self.table.item(row.row(), 9).text()) for row in selected_rows]
        is_batch = len(item_ids) > 1

        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #313244; color: white; border: 1px solid #45475a; }")

        # --- 星级设置 ---
        star_menu = menu.addMenu("⭐ 设置星级")
        star_labels = ["无", "★", "★★", "★★★", "★★★★", "★★★★★"]
        for i in range(6):
            action = star_menu.addAction(star_labels[i])
            action.triggered.connect(lambda _, level=i, ids=item_ids: self.batch_set_star(ids, level))

        menu.addSeparator()

        # --- 动态菜单项 ---
        if is_batch:
            # 批量操作,保持原有文本
            menu.addAction(f"❤️ 收藏/取消 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_favorite'))
            menu.addAction(f"📌 置顶/取消 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_pinned'))
            menu.addAction(f"🔒 锁定/解锁 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_locked'))
        else:
            # 单项操作,动态显示文本
            session = self.db.get_session()
            item = session.query(ClipboardItem).get(item_ids[0])
            if item:
                fav_text = "❤️ 取消收藏" if item.is_favorite else "❤️ 收藏"
                pin_text = "📌 取消置顶" if item.is_pinned else "📌 置顶"
                lock_text = "🔒 解锁" if item.is_locked else "🔒 锁定"
                
                menu.addAction(fav_text).triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_favorite'))
                menu.addAction(pin_text).triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_pinned'))
                menu.addAction(lock_text).triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_locked'))
            session.close()

        menu.addSeparator()

        # --- 新的颜色标签菜单结构 ---
        color_tag_menu = menu.addMenu("🎨 颜色标签")

        # 常用颜色
        common_colors_menu = color_tag_menu.addMenu("常用颜色标签")
        common_colors = [
            ("🔴 紧急", "#f38ba8"), ("🟡 重要", "#f9e2af"), ("🟢 通过", "#a6e3a1"),
            ("🔵 参考", "#89b4fa"), ("🟣 个人", "#cba6f7"), ("⚫️ 存档", "#585b70")
        ]
        for name, color in common_colors:
            action = common_colors_menu.addAction(name)
            action.setIcon(self.create_color_icon(color))
            action.triggered.connect(lambda _, c=color, ids=item_ids: self.batch_set_color(ids, c))

        # 收藏颜色 (新功能)
        fav_colors_menu = color_tag_menu.addMenu("收藏颜色标签")
        settings = QSettings("ClipboardApp", "ColorFavorites")
        fav_colors = settings.value("favorite_colors", [], type=list) # 明确类型
        if fav_colors:
            for color in fav_colors:
                action = fav_colors_menu.addAction(color)
                action.setIcon(self.create_color_icon(color))
                action.triggered.connect(lambda _, c=color, ids=item_ids: self.batch_set_color(ids, c))
        else:
            fav_colors_menu.setEnabled(False)

        # 历史颜色
        history_colors_menu = color_tag_menu.addMenu("历史颜色标签")
        settings = QSettings("ClipboardApp", "ColorHistory")
        history = settings.value("colors", [])
        if history:
            for color in history[:10]:
                action = history_colors_menu.addAction(color)
                action.setIcon(self.create_color_icon(color))
                action.triggered.connect(lambda _, c=color, ids=item_ids: self.batch_set_color(ids, c))
        else:
            history_colors_menu.setEnabled(False)

        menu.addSeparator()

        # --- 独立的功能项 ---
        menu.addAction("移除颜色标签").triggered.connect(lambda: self.batch_set_color(item_ids, None))
        
        menu.addSeparator()
        menu.addAction(f"❌ 删除 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_delete(item_ids))
        
        menu.exec_(self.table.mapToGlobal(pos))
    
    def show_header_menu(self, pos):
        """显示表头右键菜单 - 设置对齐方式"""
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        if col < 0 or col >= self.table.columnCount():
            return
        
        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #313244; color: white; border: 1px solid #45475a; }")
        
        menu.addAction("← 靠左对齐").triggered.connect(lambda: self.set_column_alignment(col, Qt.AlignLeft | Qt.AlignVCenter))
        menu.addAction("↔ 居中对齐").triggered.connect(lambda: self.set_column_alignment(col, Qt.AlignCenter))
        menu.addAction("→ 靠右对齐").triggered.connect(lambda: self.set_column_alignment(col, Qt.AlignRight | Qt.AlignVCenter))
        
        menu.exec_(self.table.horizontalHeader().mapToGlobal(pos))
    
    def set_column_alignment(self, col, alignment):
        """设置整列的对齐方式"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, col)
            if item:
                item.setTextAlignment(alignment)
        
        # 保存对齐设置
        settings = QSettings("ClipboardApp", "WindowState")
        settings.setValue(f"column_{col}_alignment", int(alignment))

    def batch_set_star(self, item_ids, level):
        """批量设置星级"""
        session = self.db.get_session()
        try:
            for item_id in item_ids:
                item = session.query(ClipboardItem).get(item_id)
                if item: item.star_level = level
            session.commit()
        finally:
            session.close()
        self.load_data(select_id=item_ids[0] if item_ids else None)
    
    def batch_toggle_field(self, item_ids, field):
        """批量切换布尔字段"""
        session = self.db.get_session()
        try:
            for item_id in item_ids:
                item = session.query(ClipboardItem).get(item_id)
                if item: setattr(item, field, not getattr(item, field))
            session.commit()
        finally:
            session.close()
        self.load_data(select_id=item_ids[0] if item_ids else None)

    def batch_set_color(self, item_ids, color_hex):
        """批量设置自定义颜色"""
        session = self.db.get_session()
        try:
            # color_hex 为 None 或 "" 时,数据库中存为 NULL,表示清除颜色
            db_color_value = color_hex if color_hex else None
            
            items_to_update = session.query(ClipboardItem).filter(ClipboardItem.id.in_(item_ids)).all()
            for item in items_to_update:
                item.custom_color = db_color_value
            
            session.commit()
        finally:
            session.close()
        
        # 刷新界面并选中第一个被修改的行
        self.load_data(select_id=item_ids[0] if item_ids else None)
    
    def batch_delete(self, item_ids):
        """批量删除"""
        reply = QMessageBox.question(self, "确认删除", 
                                     f"确定要删除 {len(item_ids)} 个项目吗?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        session = self.db.get_session()
        try:
            for item_id in item_ids:
                item = session.query(ClipboardItem).get(item_id)
                if item and not item.is_locked:
                    session.delete(item)
            session.commit()
        finally:
            session.close()
        self.load_data()
    
    def toggle_bool(self, pid, field):
        session = self.db.get_session()
        item = session.query(ClipboardItem).get(pid)
        if item: setattr(item, field, not getattr(item, field)); session.commit()
        session.close()
        self.load_data(select_id=pid)

    def toggle_edit_mode(self):
        """切换编辑/读取模式"""
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            self.mode_btn.setText("✏️")
            self.mode_btn.setToolTip("编辑模式 (已开启)")
            self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
            self.table.setDragEnabled(True)  # 编辑模式允许拖拽
        else:
            self.mode_btn.setText("📖")
            self.mode_btn.setToolTip("读取模式 (已开启)")
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setDragEnabled(False)  # 读取模式禁止拖拽
        self.mode_btn.setChecked(self.edit_mode)
    
    def on_table_double_click(self, item):
        """处理表格双击事件"""
        if not self.edit_mode:
            # 读取模式:发送到剪贴板
            row = item.row()
            item_id = int(self.table.item(row, 9).text())
            session = self.db.get_session()
            db_item = session.query(ClipboardItem).get(item_id)
            if db_item:
                self.monitor_enabled = False
                self.clipboard.setText(db_item.content)
                self.monitor_enabled = True
                self.statusBar().showMessage("✅ 已发送到剪贴板")
            session.close()

    # === 面板与标签逻辑 ===
    def update_dock_panel(self):
        sel = self.table.selectedItems()
        if not sel: self.clear_dock(); return
        pid = int(self.table.item(sel[0].row(), 9).text())
        
        session = self.db.get_session()
        item = session.query(ClipboardItem).get(pid)
        if item:
            self.current_id = item.id
            
            # 优化文件条目的预览
            if item.is_file:
                preview_content = f"[文件]\n\n路径: {item.file_path}"
                self.preview_text.setText(preview_content)
            else:
                self.preview_text.setText(item.content)
            
            self.note_input.setText(item.note)
            self.render_current_tags(item.tags)
        session.close()

    def render_current_tags(self, tags):
        """渲染当前Item已有的标签"""
        # 清空
        for i in reversed(range(self.current_tag_layout.count())): 
            w = self.current_tag_layout.itemAt(i).widget()
            if w: w.setParent(None)
            
        for tag in tags:
            btn = QPushButton(f"{tag.name} ✖")
            btn.setStyleSheet("background-color: #313244; color: #89b4fa; border: 1px solid #89b4fa; border-radius: 10px;")
            btn.setCursor(Qt.PointingHandCursor)
            # 点击删除标签
            btn.clicked.connect(lambda _, t=tag.name: self.del_tag(t))
            self.current_tag_layout.addWidget(btn)

    def refresh_tag_cloud(self):
        """渲染历史标签库 (标签云)"""
        # 清空
        for i in reversed(range(self.tag_cloud_layout.count())): 
            w = self.tag_cloud_layout.itemAt(i).widget()
            if w: w.setParent(None)

        # 获取数据: [(name, count), ...]
        tags_data = self.db.get_tag_cloud()
        
        for name, count in tags_data:
            # 创建带统计数字的按钮
            btn = QPushButton(f"🏷️ {name}  ({count})")
            btn.setObjectName("TagCloudBtn")
            btn.setCursor(Qt.PointingHandCursor)
            # 点击将该标签添加到当前选中的Item
            btn.clicked.connect(lambda _, t=name: self.apply_tag_from_cloud(t))
            self.tag_cloud_layout.addWidget(btn)

    def apply_tag_from_cloud(self, tag_name):
        if hasattr(self, 'current_id'):
            self.db.add_tags_to_items([self.current_id], tag_name)
            self.update_dock_panel() # 刷新当前Item标签
            self.refresh_tag_cloud() # 刷新计数

    def del_tag(self, name):
        if hasattr(self, 'current_id'):
            self.db.remove_tag_from_item(self.current_id, name)
            self.update_dock_panel()
            self.refresh_tag_cloud()

    def add_tag_action(self):
        if hasattr(self, 'current_id'):
            dialog = TagSelectorDialog(self.db, self.current_id, self)
            dialog.show()  # 非模态显示

    def clear_dock(self):
        self.preview_text.clear(); self.note_input.clear()
        for i in reversed(range(self.current_tag_layout.count())): 
            w = self.current_tag_layout.itemAt(i).widget(); 
            if w: w.setParent(None)

    def save_note(self):
        if hasattr(self, 'current_id'):
            self.db.update_field(self.current_id, 'note', self.note_input.text())
            r = self.table.currentRow()
            if r >= 0: self.table.item(r, 2).setText(self.note_input.text())

    def extract_content(self):
        if hasattr(self, 'current_id'):
            self.monitor_enabled = False
            self.clipboard.setText(self.preview_text.toPlainText())
            self.monitor_enabled = True
            session = self.db.get_session()
            item = session.query(ClipboardItem).get(self.current_id)
            if item: item.visit_count += 1; item.last_visited_at = datetime.now(); session.commit()
            session.close()
            r = self.table.currentRow()
            if r >= 0: self.table.item(r, 5).setText(str(int(self.table.item(r, 5).text())+1))

    def update_db_order(self, ids):
        if self.sort_combo.currentIndex() != 0:
            QMessageBox.warning(self, "提示", "请切换到'手动拖拽'模式"); self.load_data(); return
        self.db.update_sort_order(ids)

    @pyqtSlot()
    def on_clipboard_change(self):
        if not self.monitor_enabled: return
        try:
            m = self.clipboard.mimeData()
            
            # 优先处理文件
            if m.hasUrls():
                file_paths = []
                for url in m.urls():
                    if url.isLocalFile():
                        file_paths.append(url.toLocalFile())
                
                if not file_paths: return
                
                # 将路径列表合并为一个字符串,用换行符分隔,作为剪贴板文本的唯一标识
                clipboard_content = "\n".join(file_paths)
                if clipboard_content == self.last_clipboard_text: return
                self.last_clipboard_text = clipboard_content
                
                # 为每个文件创建一个条目
                for path in file_paths:
                    # 使用路径本身作为'content'进行哈希检查
                    self.db.add_item(text=path, is_file=True, file_path=path)
                
                if self.sort_combo.currentIndex() == 0: self.load_data()
            
            # 处理文本
            elif m.hasText():
                t = m.text().strip()
                if not t or t == self.last_clipboard_text: return
                self.last_clipboard_text = t
                item, is_new = self.db.add_item(t)
                if self.sort_combo.currentIndex() == 0: self.load_data()
                
        except Exception as e:
            print(f"剪贴板监控错误: {e}")
    
    # === 分组功能 ===
    def group_selected_items(self):
        """智能颜色标签切换：根据选中项的颜色状态，智能添加或取消颜色标签"""
        selected_rows = self.table.selectionModel().selectedRows()
        if len(selected_rows) < 1:
            QMessageBox.information(self, "提示", "请至少选择1个项目")
            return
        
        # 获取选中项目的ID和颜色状态
        item_ids = []
        session = self.db.get_session()
        try:
            items_with_colors = []  # 有颜色的项目
            items_without_colors = []  # 无颜色的项目
            color_counts = {}  # 统计每种颜色的数量
            
            for index in selected_rows:
                row = index.row()
                item_id = int(self.table.item(row, 9).text())
                item_ids.append(item_id)
                
                item = session.query(ClipboardItem).get(item_id)
                if item:
                    # 优先使用custom_color，否则使用group_color
                    color = item.custom_color or item.group_color
                    if color:
                        items_with_colors.append((item_id, color))
                        color_counts[color] = color_counts.get(color, 0) + 1
                    else:
                        items_without_colors.append(item_id)
            
            # 逻辑判断
            total_count = len(item_ids)
            colored_count = len(items_with_colors)
            
            if colored_count == total_count:
                # 情况1: 所有选中项都有颜色 -> 取消所有颜色标签
                for item_id in item_ids:
                    item = session.query(ClipboardItem).get(item_id)
                    if item:
                        item.custom_color = None
                        item.group_color = None
                session.commit()
                self.statusBar().showMessage(f"已取消 {total_count} 个项目的颜色标签")
            
            elif colored_count == 0:
                # 情况2: 所有选中项都没有颜色 -> 分配新颜色
                group_color = self.generate_unique_color()
                for item_id in item_ids:
                    item = session.query(ClipboardItem).get(item_id)
                    if item:
                        item.group_color = group_color
                session.commit()
                self.statusBar().showMessage(f"已为 {total_count} 个项目添加颜色标签: {group_color}")
            
            else:
                # 情况3: 混合状态 -> 少数服从多数
                # 找出最多的颜色
                majority_color = max(color_counts.items(), key=lambda x: x[1])[0] if color_counts else None
                
                if majority_color:
                    # 将所有无颜色的项目设置为多数颜色
                    for item_id in items_without_colors:
                        item = session.query(ClipboardItem).get(item_id)
                        if item:
                            item.group_color = majority_color
                    session.commit()
                    self.statusBar().showMessage(f"已将 {len(items_without_colors)} 个项目统一为多数颜色: {majority_color}")
        
        finally:
            session.close()
        
        # 刷新显示并保持选中状态
        self.load_data()
        
        # 重新选中之前选中的项目
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            row_id = int(self.table.item(row, 9).text())
            if row_id in item_ids:
                self.table.selectRow(row)
    
    def generate_unique_color(self):
        """生成唯一的随机颜色(柔和的深色系)"""
        import random
        
        # 预定义的柔和深色调色板
        color_palette = [
            "#2d3748",  # 深灰蓝
            "#2c5282",  # 深蓝
            "#2f855a",  # 深绿
            "#744210",  # 深棕
            "#5a2e5e",  # 深紫
            "#2c5f5f",  # 深青
            "#4a5568",  # 深灰
            "#5a3825",  # 深褐
            "#2d4a3e",  # 深墨绿
            "#3d3846",  # 深紫灰
            "#2e4057",  # 深蓝灰
            "#4a3f35",  # 深卡其
        ]
        
        # 找出未使用的颜色
        available_colors = [c for c in color_palette if c not in self.used_colors]
        
        # 如果所有颜色都用完了,清空已使用颜色集合
        if not available_colors:
            self.used_colors.clear()
            available_colors = color_palette
        
        # 随机选择一个颜色
        color = random.choice(available_colors)
        self.used_colors.add(color)
        
        return color

    def toolbar_set_color(self):
        """工具栏颜色按钮点击处理"""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要设置颜色的项目")
            return
        
        # 获取选中项目的ID
        item_ids = [int(self.table.item(row.row(), 9).text()) for row in selected_rows]
        self.set_custom_color(item_ids)

    def set_custom_color(self, item_ids):
        """设置自定义颜色"""
        dialog = ColorSelectorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            color_hex = dialog.selected_color
            
            # 如果color_hex是空字符串,表示清除颜色,数据库中存为NULL
            db_color_value = color_hex if color_hex else None
            
            session = self.db.get_session()
            try:
                for item_id in item_ids:
                    item = session.query(ClipboardItem).get(item_id)
                    if item:
                        item.custom_color = db_color_value
                session.commit()
            finally:
                session.close()
            self.load_data(select_id=item_ids[0] if item_ids else None)
    
    def auto_delete_old_items(self):
        """清理21天前的旧数据"""
        reply = QMessageBox.question(
            self, 
            "确认清理", 
            "确定要删除21天前的数据吗?\n(已锁定的数据不会被删除)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            count = self.db.auto_delete_old_data(21)
            QMessageBox.information(self, "清理完成", f"已删除 {count} 条旧数据")
            self.load_data()
    
    def create_color_icon(self, color_hex):
        """根据HEX颜色值创建一个圆形图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 16, 16)
        painter.end()
        return QIcon(pixmap)

    def on_item_changed(self, item):
        """处理表格内编辑并持久化"""
        if not self.edit_mode:
            return

        col = item.column()
        row = item.row()
        
        # 获取ID
        id_item = self.table.item(row, 9)
        if not id_item: return
        item_id = int(id_item.text())
        
        new_text = item.text().strip()
        
        # 根据列更新不同字段
        if col == 2: # 备注
            self.db.update_field(item_id, 'note', new_text)
            # 更新侧边栏(如果当前选中)
            if self.table.currentRow() == row:
                self.note_input.setText(new_text)
        elif col == 8: # 内容
            self.db.update_field(item_id, 'content', new_text)
            # 更新大小列
            size_item = self.table.item(row, 4)
            if size_item:
                size_item.setText(self.format_size(new_text))
            # 更新侧边栏预览
            if self.table.currentRow() == row:
                self.preview_text.setText(new_text)

    # === 功能方法 ===
    def toggle_always_on_top(self):
        """切换窗口置顶状态"""
        is_top = self.btn_pin.isChecked()
        if is_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.btn_pin.setStyleSheet("background-color: #45475a; border: 1px solid #89b4fa;")
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.btn_pin.setStyleSheet("")
        self.show() # 需要重新show才能生效
    
    def paste_to_previous_window(self):
        """双击粘贴到上一个窗口"""
        # 1. 获取选中内容
        row = self.table.currentRow()
        if row < 0: return
        
        content = self.table.item(row, 8).text() # 内容列
        if not content: return
        
        # 2. 写入剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        
        # 3. 激活上一个窗口
        if self.last_external_hwnd:
            try:
                # 尝试将窗口置于前台
                # 注意: Windows限制了SetForegroundWindow的使用，但在用户交互(双击)后通常允许
                ctypes.windll.user32.SetForegroundWindow(self.last_external_hwnd)
                
                # 如果窗口被最小化了，恢复它
                if ctypes.windll.user32.IsIconic(self.last_external_hwnd):
                    ctypes.windll.user32.ShowWindow(self.last_external_hwnd, 9) # SW_RESTORE
            except Exception as e:
                print(f"激活窗口失败: {e}")
        
        # 隐藏自己 (可选，根据用户习惯，Ditto通常会隐藏)
        self.showMinimized()
        
        # 4. 延时后模拟粘贴
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(150, self._perform_paste)

    def keyPressEvent(self, event):
        """处理快捷键设置星级"""
        modifiers = QApplication.keyboardModifiers()
        key = event.key()

        # 检查是否按下了Ctrl键
        if modifiers == Qt.ControlModifier:
            star_level = -1
            if Qt.Key_0 <= key <= Qt.Key_5:
                star_level = key - Qt.Key_0

            if star_level != -1:
                selected_rows = self.table.selectionModel().selectedRows()
                if not selected_rows:
                    return # 没有选中行，不执行任何操作

                item_ids = [int(self.table.item(index.row(), 9).text()) for index in selected_rows]
                self.batch_set_star(item_ids, star_level)
                event.accept()
                return

        # 如果不是我们的快捷键，调用父类的方法
        super().keyPressEvent(event)
        
    def _perform_paste(self):
        """执行粘贴操作"""
        # 使用ctypes模拟Ctrl+V
        # keybd_event: 0x11=VK_CONTROL, 0x56=V
        user32 = ctypes.windll.user32
        
        # 按下 Ctrl
        user32.keybd_event(0x11, 0, 0, 0)
        # 按下 V
        user32.keybd_event(0x56, 0, 0, 0)
        # 释放 V
        user32.keybd_event(0x56, 0, 2, 0)
        # 释放 Ctrl
        user32.keybd_event(0x11, 0, 2, 0)

    # === 窗口状态管理 ===
    def on_column_resized(self, logicalIndex, oldSize, newSize):
        """列宽变化时延迟保存"""
        self.schedule_save_window_state()
    
    def schedule_save_window_state(self):
        """延迟保存窗口状态，避免频繁保存"""
        if hasattr(self, 'save_timer'):
            self.save_timer.stop()
            self.save_timer.start()
    
    def save_window_state(self):
        """保存窗口状态"""
        settings = QSettings("ClipboardApp", "WindowState")
        
        # 保存主窗口状态
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        
        # 保存UI状态
        settings.setValue("currentFilter", self.btn_fav.isChecked() and "favorite" or (self.btn_lock.isChecked() and "locked" or "all"))
        settings.setValue("sortIndex", self.sort_combo.currentIndex())
        
        # 保存列宽
        column_widths = []
        for i in range(self.table.columnCount()):
            column_widths.append(self.table.columnWidth(i))
        settings.setValue("columnWidths", column_widths)
        
        # 保存编辑模式状态
        settings.setValue("editMode", self.edit_mode)
    
    def restore_window_state(self):
        """恢复窗口状态"""
        settings = QSettings("ClipboardApp", "WindowState")
        
        # 恢复主窗口状态
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        window_state = settings.value("windowState")
        if window_state:
            self.restoreState(window_state)
        
        # 恢复UI状态
        filter_type = settings.value("currentFilter", "all")
        if filter_type == "favorite":
            self.btn_fav.setChecked(True)
            self.btn_all.setChecked(False)
            self.current_filter = "favorite"
        elif filter_type == "locked":
            self.btn_lock.setChecked(True)
            self.btn_all.setChecked(False)
            self.current_filter = "locked"
        
        sort_index = settings.value("sortIndex", 0)
        if sort_index:
            self.sort_combo.setCurrentIndex(int(sort_index))
        
        # 恢复列宽
        column_widths = settings.value("columnWidths")
        if column_widths:
            for i, width in enumerate(column_widths):
                if i < self.table.columnCount():
                    self.table.setColumnWidth(i, int(width))
        
        # 恢复编辑模式状态
        edit_mode = settings.value("editMode", False, type=bool)
        if edit_mode:
            self.edit_mode = True
            self.mode_btn.setChecked(True)
            self.mode_btn.setText("✏️")
            # 设置表格可编辑
            self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
    
    def closeEvent(self, event):
        """窗口关闭时保存状态"""
        self.save_window_state()
        event.accept()
        
    def toggle_maximize(self):
        """切换最大化/正常状态"""
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("⃞")
            self.maximize_button.setToolTip("最大化")
        else:
            self.showMaximized()
            self.maximize_button.setText("❐")
            self.maximize_button.setToolTip("向下还原")

# ===================|===================

# color_selector.py

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
            QPushButton { border: none; border-radius: 4px; padding: 4px; }
            QPushButton:hover { border: 1px solid #89b4fa; }
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
        
        # 1. 推荐颜色
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
        
        # 2. 最近使用
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
        
        # 新增: 收藏按钮
        btn_fav = QPushButton("⭐")
        btn_fav.setFixedSize(36, 36)
        btn_fav.setToolTip("收藏此颜色")
        btn_fav.setStyleSheet("background-color: #313244; color: white; font-size: 16px;")
        btn_fav.clicked.connect(self.save_favorite_color)
        custom_layout.addWidget(btn_fav)
        
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
        settings = QSettings("ClipboardApp", "ColorHistory")
        history = settings.value("colors", [])
        if not history: history = ["#ffffff", "#000000", "#808080"]
        
        for i in reversed(range(self.grid_history.count())): 
            self.grid_history.itemAt(i).widget().setParent(None)
            
        for i, color in enumerate(history[:16]):
            btn = self.create_color_btn(color)
            self.grid_history.addWidget(btn, i // 8, i % 8)
            
    def save_history(self, color):
        settings = QSettings("ClipboardApp", "ColorHistory")
        history = settings.value("colors", [])
        if color in history: history.remove(color)
        history.insert(0, color)
        settings.setValue("colors", history[:16])
        
    def save_favorite_color(self):
        color_text = self.hex_input.text().strip()
        if QColor(color_text).isValid():
            settings = QSettings("ClipboardApp", "ColorFavorites")
            fav_colors = settings.value("favorite_colors", [])
            if color_text not in fav_colors:
                fav_colors.insert(0, color_text)
                settings.setValue("favorite_colors", fav_colors)
                QMessageBox.information(self, "成功", f"颜色 {color_text} 已收藏!")
            else:
                QMessageBox.information(self, "提示", f"颜色 {color_text} 已在收藏夹中。")

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ClipboardApp()
    window.show()
    sys.exit(app.exec_())

# ===================|===================

# color_selector.py

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
            QPushButton:hover { border: 1px solid #89b4fa; }
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
