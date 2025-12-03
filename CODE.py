# J 监听剪贴板功能主界面.py
# -*- coding: utf-8 -*-
import sys
import os
import hashlib
from datetime import datetime

# === 1. 数据库部分 (保持不变) ===
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Table, Index, Float, func, LargeBinary
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, joinedload

try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QPushButton, QLabel, QLineEdit,
                                 QTableWidget, QTableWidgetItem, QHeaderView,
                                 QComboBox, QAbstractItemView, QShortcut, QInputDialog,
                                 QMessageBox, QTextEdit, QMenu, QFrame, QScrollArea,
                                 QDockWidget, QSizePolicy, QSplitter, QDialog, QGridLayout,
                                 QListWidget, QListWidgetItem, QCheckBox, QSpinBox, QStatusBar)
    from PyQt5.QtGui import QKeySequence, QColor, QFont, QIcon, QCursor, QImage, QPixmap
    from PyQt5.QtCore import Qt, pyqtSlot, QSize, QSettings, QBuffer, QUrl, QMimeData
except ImportError:
    print("请安装库: pip install PyQt5 SQLAlchemy")
    sys.exit(1)

from color_selector import ColorSelectorDialog

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
    binary_content = Column(LargeBinary, default=None) # 新增：用于存储文件/图片二进制数据
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

        # 使用一个连接处理所有迁移
        conn = None
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

            cursor.execute("PRAGMA table_info(clipboard_items)")
            columns = [row[1] for row in cursor.fetchall()]

            # 迁移逻辑
            migrations = {
                'group_color': "ALTER TABLE clipboard_items ADD COLUMN group_color VARCHAR(20)",
                'custom_color': "ALTER TABLE clipboard_items ADD COLUMN custom_color VARCHAR(20)",
                'is_file': "ALTER TABLE clipboard_items ADD COLUMN is_file BOOLEAN DEFAULT 0",
                'file_path': "ALTER TABLE clipboard_items ADD COLUMN file_path TEXT",
                'binary_content': "ALTER TABLE clipboard_items ADD COLUMN binary_content BLOB" # SQLite中BLOB对应LargeBinary
            }

            for col, statement in migrations.items():
                if col not in columns:
                    cursor.execute(statement)
                    print(f"✓ 数据库已更新: 添加 {col} 字段")

            conn.commit()

        except Exception as e:
            print(f"数据库迁移警告: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()


    def get_session(self): return self.Session()

    def add_item(self, content, content_type='text', binary_content=None, file_path=None):
        session = self.get_session()
        try:
            # 根据内容类型计算哈希值
            if content_type == 'text':
                data_to_hash = content.encode('utf-8')
                is_file_flag = False
            else: # image or file
                data_to_hash = binary_content
                is_file_flag = True

            content_hash = hashlib.sha256(data_to_hash).hexdigest()

            # 检查是否已存在
            existing = session.query(ClipboardItem).filter_by(content_hash=content_hash).first()
            if existing:
                existing.last_visited_at = datetime.now()
                existing.visit_count += 1
                session.commit()
                return existing, False

            # 计算排序索引
            min_sort = session.query(ClipboardItem).order_by(ClipboardItem.sort_index.asc()).first()
            new_sort = (min_sort.sort_index - 1.0) if min_sort else 0.0

            # 自动生成备注
            auto_note = ""
            if content_type == 'file' and file_path:
                auto_note = f"文件: {os.path.basename(file_path)}"
            elif content_type == 'image':
                auto_note = f"图片: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                first_line = content.split('\n')[0].strip()
                auto_note = first_line[:100] if first_line else ""

            # 创建新条目
            new_item = ClipboardItem(
                content=content,
                binary_content=binary_content,
                content_hash=content_hash,
                sort_index=new_sort,
                note=auto_note,
                is_file=is_file_flag,
                file_path=file_path
            )
            session.add(new_item)
            session.commit()
            session.refresh(new_item)
            return new_item, True
        except Exception as e:
            print(f"添加项目时出错: {e}")
            session.rollback()
            return None, False
        finally:
            session.close()

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
        """加载所有标签,适配不同视图和筛选"""
        self.tag_list.clear()

        # tags_data is a list of (name, count) tuples
        tags_data = self.db.get_tag_cloud()

        # --- 核心修改: 实现筛选和排序 ---
        # 暂时只实现“常用” (按引用计数排序), 其他为未来扩展保留
        if self.show_frequent:
            # get_tag_cloud 默认已按count降序排序
            display_tags = tags_data
        else:
            # 如果不显示常用，可以按字母顺序或添加时间排序（未来）
            display_tags = sorted(tags_data, key=lambda x: x[0]) # 按名称排序

        # 应用最大显示数量限制
        display_tags = display_tags[:self.max_display]

        for name, count in display_tags:
            if self.view_mode == "grid":
                item = QListWidgetItem(name)
                item.setToolTip(f"{name} ({count}次引用)")
                item.setTextAlignment(Qt.AlignCenter)
            else:  # list
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

        self.apply_style()

        # === 核心布局 ===
        self.central_container = QWidget()
        self.central_container.setObjectName("centralContainer")
        self.setCentralWidget(self.central_container)
        self.central_layout = QVBoxLayout(self.central_container)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.central_layout.setSpacing(0)

        # 初始化状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().setStyleSheet("background-color: #181825; color: #a6adc8;")

        self.init_title_bar()  # 初始化自定义标题栏
        self.init_top_bar()
        self.init_table()
        self.init_metadata_panel()
        self.init_tag_panel()
        self.load_data()

        # 恢复窗口状态
        self.restore_window_state()

        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self.on_clipboard_change)

        self.group_shortcut = QShortcut(QKeySequence("Ctrl+G"), self)
        self.group_shortcut.activated.connect(self.group_selected_items)

        # 已使用的颜色集合
        self.used_colors = set()

        # 编辑模式标志
        self.edit_mode = False  # False=读取模式, True=编辑模式

    def run_robust_self_test(self):
        """
        增强版内部集成测试：
        1. 依次模拟 文本、图片、文件 的剪贴板复制操作。
        2. 每一步操作后，自动加载数据并选中新条目，强制触发预览面板的刷新逻辑。
        3. 这将确保所有类型的预览代码都被执行，从而覆盖之前未测试到的代码路径。
        4. 测试过程不生成任何截图，如果完整流程无错误、不崩溃地执行完毕，即视为成功。
        """
        print("--- [Robust Self-Test] Starting enhanced test sequence... ---")
        from PyQt5.QtCore import QTimer

        def _select_top_row_and_process_events():
            """Helper to select top row and trigger UI updates."""
            self.load_data()
            if self.table.rowCount() > 0:
                print("[Robust Self-Test] Selecting top row to trigger preview update.")
                self.table.selectRow(0)
                QApplication.processEvents() # Crucial for processing signals
            else:
                print("[Robust Self-Test] Warning: Table is empty, cannot select row.")

        def step_1_copy_text():
            print("[Robust Self-Test] Step 1: Simulating text copy.")
            self.monitor_enabled = False
            self.clipboard.setText("A robust text test.")
            self.monitor_enabled = True
            self.on_clipboard_change()
            _select_top_row_and_process_events()
            QTimer.singleShot(500, step_2_copy_image)

        def step_2_copy_image():
            print("[Robust Self-Test] Step 2: Simulating image copy.")
            image = QImage(50, 50, QImage.Format_RGB32)
            image.fill(QColor("#f9e2af")) # Yellow
            self.monitor_enabled = False
            self.clipboard.setImage(image)
            self.monitor_enabled = True
            self.on_clipboard_change()
            _select_top_row_and_process_events() # This will trigger the QPixmap logic
            QTimer.singleShot(500, step_3_copy_file)

        def step_3_copy_file():
            print("[Robust Self-Test] Step 3: Simulating file copy.")
            self.test_file_path = os.path.abspath("robust_test_file.txt")
            with open(self.test_file_path, "w") as f:
                f.write("A robust file test.")
            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(self.test_file_path)])
            self.monitor_enabled = False
            self.clipboard.setMimeData(mime_data)
            self.monitor_enabled = True
            self.on_clipboard_change()
            _select_top_row_and_process_events()
            QTimer.singleShot(500, step_4_cleanup_and_exit)

        def step_4_cleanup_and_exit():
            print("[Robust Self-Test] Step 4: Cleaning up and exiting.")
            if hasattr(self, 'test_file_path') and os.path.exists(self.test_file_path):
                os.remove(self.test_file_path)
            print("--- [Robust Self-Test] Test sequence completed successfully. Exiting. ---")
            QApplication.instance().quit()

        QTimer.singleShot(1000, step_1_copy_text)

    def create_color_icon(self, color_hex, size=12):
        """根据HEX颜色值创建一个圆形的QIcon"""
        if not color_hex:
            return QIcon()

        from PyQt5.QtGui import QPixmap, QPainter
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color_hex))
        painter.drawEllipse(0, 0, size, size)
        painter.end()

        return QIcon(pixmap)

    def mousePressEvent(self, event):
        """处理鼠标按下事件,用于窗口拖动"""
        if event.button() == Qt.LeftButton and self.title_bar.underMouse():
            self.drag_start_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """处理鼠标移动事件,用于窗口拖动"""
        if event.buttons() == Qt.LeftButton and self.drag_start_position is not None:
            self.move(event.globalPos() - self.drag_start_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件"""
        self.drag_start_position = None
        event.accept()

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #11111b; } /* 极深色背景 */
            QWidget { color: #cdd6f4; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 13px; }

            /* Dock 标题栏极简化 */
            QDockWidget::title { background: #181825; padding-left: 5px; padding-top: 4px; border-bottom: 1px solid #313244; }

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
            QPushButton { background-color: #313244; border: 1px solid #45475a; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #45475a; border-color: #89b4fa; }
            QPushButton:pressed { background-color: #89b4fa; color: #1e1e2e; }

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
            QTableWidget { background-color: #11111b; border: none; gridline-color: #1e1e2e; selection-background-color: #313244; selection-color: #89b4fa; }
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
        self.title_bar.setFixedHeight(32)
        self.title_bar_layout = QHBoxLayout(self.title_bar)
        self.title_bar_layout.setContentsMargins(5, 0, 5, 0)
        self.title_bar_layout.setSpacing(10)

        # 应用图标
        self.icon_label = QLabel()
        # 注意: 这里需要一个有效的图标路径, 暂时使用占位符. 后面需要创建资源文件.
        # icon_pixmap = QPixmap(":/icons/app_icon.png").scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # self.icon_label.setPixmap(icon_pixmap)
        self.icon_label.setText("💾") # 临时图标
        self.title_bar_layout.addWidget(self.icon_label)

        # 标题
        self.title_label = QLabel("印象记忆_Dark")
        self.title_label.setObjectName("titleLabel")
        self.title_bar_layout.addWidget(self.title_label)

        # 添加伸缩, 将按钮推到右侧
        self.title_bar_layout.addStretch()

        # --- 功能按钮 ---
        # 刷新按钮
        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setObjectName("titleBarButton")
        self.btn_refresh.setFixedSize(30, 30)
        self.btn_refresh.setToolTip("刷新数据")
        self.btn_refresh.clicked.connect(lambda: self.load_data())
        self.title_bar_layout.addWidget(self.btn_refresh)

        # 自动删除按钮
        self.btn_auto_delete = QPushButton("🗑️")
        self.btn_auto_delete.setObjectName("titleBarButton")
        self.btn_auto_delete.setFixedSize(30, 30)
        self.btn_auto_delete.setToolTip("清理数据")
        self.btn_auto_delete.clicked.connect(self.auto_delete_old_items)
        self.title_bar_layout.addWidget(self.btn_auto_delete)

        # 模式切换按钮
        self.mode_btn = QPushButton("📖")
        self.mode_btn.setObjectName("titleBarButton")
        self.mode_btn.setFixedSize(30, 30)
        self.mode_btn.setCheckable(True)
        self.mode_btn.setToolTip("切换读/写模式")
        self.mode_btn.clicked.connect(self.toggle_edit_mode)
        self.title_bar_layout.addWidget(self.mode_btn)

        # 添加一个小的分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #45475a;")
        self.title_bar_layout.addWidget(separator)

        # 窗口控制按钮
        self.minimize_button = QPushButton("—")
        self.minimize_button.setObjectName("minimizeButton")
        self.minimize_button.setFixedSize(30, 30)
        self.minimize_button.setToolTip("最小化")
        self.minimize_button.clicked.connect(self.showMinimized)

        self.maximize_button = QPushButton("⃞")
        self.maximize_button.setObjectName("maximizeButton")
        self.maximize_button.setFixedSize(30, 30)
        self.maximize_button.setToolTip("最大化")
        self.maximize_button.clicked.connect(self.toggle_maximize)

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.setFixedSize(30, 30)
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(self.close)

        self.title_bar_layout.addWidget(self.minimize_button)
        self.title_bar_layout.addWidget(self.maximize_button)
        self.title_bar_layout.addWidget(self.close_button)

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
        w(0, 40); w(1, 50); w(2, 200); w(3, 60); w(4, 70); w(5, 40); w(6, 140); w(7, 140)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemSelectionChanged.connect(self.update_dock_panel)
        self.table.itemDoubleClicked.connect(self.on_table_double_click)  # 双击事件

        # 表头右键菜单
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_menu)

        self.central_layout.addWidget(self.table)

    def init_metadata_panel(self):
        """创建元数据面板"""
        self.metadata_dock = QDockWidget("📊 元数据", self)
        self.metadata_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)  # 禁止停靠到顶部
        self.metadata_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

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

    def init_tag_panel(self):
        """创建标签面板"""
        self.tag_dock = QDockWidget("🏷️ 标签", self)
        self.tag_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)  # 禁止停靠到顶部
        self.tag_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

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
        return self.format_size_bytes(b)

    def format_size_bytes(self, b):
        if b < 1024: return f"{b} B"
        elif b < 1024**2: return f"{b/1024:.1f} KB"
        return f"{b/1024**2:.1f} MB"

    def load_data(self, select_id=None):
        """加载数据,并可选择性地选中指定id的项目"""
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

    def insert_row(self, item, idx):
        r = self.table.rowCount(); self.table.insertRow(r)

        # 序号
        seq_item = QTableWidgetItem(str(idx))
        seq_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 0, seq_item)

        # 状态 (图标 + 文字)
        status_text = ""
        if item.is_pinned: status_text += "📌"
        if item.is_favorite: status_text += "❤️"
        if item.is_locked: status_text += "🔒"

        status_item = QTableWidgetItem()

        # 优先使用自定义颜色
        display_color = item.custom_color or item.group_color
        if display_color:
            status_item.setIcon(self.create_color_icon(display_color))

        status_item.setText(status_text)
        status_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 1, status_item)

        # 备注 (增加文件/图片类型图标)
        note_text = item.note
        if item.is_file:
            if item.binary_content and item.note.startswith("图片:"):
                note_text = f"🖼️ {note_text}"
            else:
                note_text = f"📄 {note_text}"

        note_item = QTableWidgetItem(note_text)
        self.table.setItem(r, 2, note_item)

        # 星级 - 使用金色★符号
        stars = "★" * item.star_level if item.star_level > 0 else ""
        star_item = QTableWidgetItem(stars)
        star_item.setTextAlignment(Qt.AlignCenter)
        star_item.setForeground(QColor("#FFD700"))  # 金色
        self.table.setItem(r, 3, star_item)

        # 大小
        # 如果是文件或图片，大小基于二进制数据
        if item.is_file and item.binary_content:
            size_str = self.format_size_bytes(len(item.binary_content))
        else:
            size_str = self.format_size(item.content)
        size_item = QTableWidgetItem(size_str)
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
        content_preview = item.content[:60].replace('\n', ' ')
        content_item = QTableWidgetItem(content_preview)
        self.table.setItem(r, 8, content_item)

        # ID(隐藏)
        id_item = QTableWidgetItem(str(item.id))
        self.table.setItem(r, 9, id_item)

    def show_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid(): return

        # 获取选中的所有行
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return

        item_ids = [int(self.table.item(row.row(), 9).text()) for row in selected_rows]
        is_batch = len(item_ids) > 1

        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #313244; color: white; border: 1px solid #45475a; }")

        # 星级设置 - 只显示星号
        star_menu = menu.addMenu("⭐ 设置星级")
        star_labels = ["无", "★", "★★", "★★★", "★★★★", "★★★★★"]
        for i in range(6):
            action = star_menu.addAction(star_labels[i])
            action.triggered.connect(lambda _, level=i, ids=item_ids: self.batch_set_star(ids, level))

        menu.addSeparator()
        menu.addAction(f"❤️ 收藏/取消 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_favorite'))
        menu.addAction(f"📌 置顶/取消 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_pinned'))
        menu.addAction(f"🔒 锁定/解锁 ({len(item_ids)}项)").triggered.connect(lambda: self.batch_toggle_field(item_ids, 'is_locked'))
        menu.addSeparator()
        menu.addAction(f"🎨 设置颜色 ({len(item_ids)}项)").triggered.connect(lambda: self.set_custom_color(item_ids))
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
                if db_item.is_file and db_item.file_path:
                    # 如果是文件,复制文件URL
                    mime_data = QMimeData()
                    mime_data.setUrls([QUrl.fromLocalFile(db_item.file_path)])
                    self.clipboard.setMimeData(mime_data)
                    self.statusBar().showMessage(f"✅ 文件路径已复制: {db_item.file_path}")
                elif db_item.is_file and db_item.binary_content:
                    # 如果是图片,复制图片本身
                    image = QImage()
                    image.loadFromData(db_item.binary_content)
                    self.clipboard.setImage(image)
                    self.statusBar().showMessage("✅ 图片已复制到剪贴板")
                else:
                    # 否则复制文本
                    self.clipboard.setText(db_item.content)
                    self.statusBar().showMessage("✅ 已发送到剪贴板")

                self.monitor_enabled = True
            session.close()

    # === 面板与标签逻辑 ===
    def update_dock_panel(self):
        sel = self.table.selectedItems()
        if not sel:
            self.clear_dock()
            return

        pid = int(self.table.item(sel[0].row(), 9).text())

        session = self.db.get_session()
        # 使用 joinedload 预加载 tags 关系, 提高效率
        item = session.query(ClipboardItem).options(joinedload(ClipboardItem.tags)).get(pid)

        if item:
            self.current_id = item.id

            # 核心修改：根据内容类型更新预览
            self.preview_text.clear() # 先清空
            if item.is_file and item.binary_content and item.note.startswith("🖼️"):
                from PyQt5.QtGui import QTextCursor, QTextImageFormat, QPixmap

                pixmap = QPixmap()
                pixmap.loadFromData(item.binary_content)

                # 获取预览框的宽度以缩放图片
                preview_width = self.preview_text.width() - 20 # 留出边距
                if pixmap.width() > preview_width:
                    pixmap = pixmap.scaledToWidth(preview_width, Qt.SmoothTransformation)

                cursor = self.preview_text.textCursor()
                cursor.insertImage(pixmap)
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
            session = self.db.get_session()
            item = session.query(ClipboardItem).get(self.current_id)
            if not item:
                session.close()
                return

            self.monitor_enabled = False
            # 根据内容类型决定如何复制
            if item.is_file and item.binary_content and item.note.startswith("🖼️"):
                image = QImage()
                image.loadFromData(item.binary_content)
                self.clipboard.setImage(image)
                self.statusBar().showMessage("✅ 图片已复制到剪贴板")
            else:
                self.clipboard.setText(self.preview_text.toPlainText())
                self.statusBar().showMessage("✅ 已发送到剪贴板")

            self.monitor_enabled = True

            item.visit_count += 1
            item.last_visited_at = datetime.now()
            session.commit()
            session.close()

            r = self.table.currentRow()
            if r >= 0: self.table.item(r, 5).setText(str(int(self.table.item(r, 5).text())+1))

    def update_db_order(self, ids):
        if self.sort_combo.currentIndex() != 0:
            QMessageBox.warning(self, "提示", "请切换到'手动拖拽'模式"); self.load_data(); return
        self.db.update_sort_order(ids)

    @pyqtSlot()
    def on_clipboard_change(self):
        if not self.monitor_enabled:
            return

        try:
            mime_data = self.clipboard.mimeData()

            # 1. 优先处理图片数据
            if mime_data.hasImage():
                image = self.clipboard.image()
                if not image.isNull():
                    buffer = QBuffer()
                    buffer.open(QBuffer.ReadWrite)
                    image.save(buffer, "PNG")
                    img_bytes = buffer.data().data()

                    item, is_new = self.db.add_item(
                        content="[截图内容]",
                        content_type='image',
                        binary_content=img_bytes
                    )

                    if is_new and self.sort_combo.currentIndex() == 0:
                        self.load_data()
                    return

            # 2. 处理文件URL
            elif mime_data.hasUrls():
                urls = mime_data.urls()
                added_count = 0
                for url in urls:
                    if url.isLocalFile():
                        file_path = url.toLocalFile()

                        try:
                            with open(file_path, 'rb') as f:
                                file_bytes = f.read()

                            item, is_new = self.db.add_item(
                                content=f"[文件内容]: {file_path}",
                                content_type='file',
                                binary_content=file_bytes,
                                file_path=file_path
                            )
                            if is_new:
                                added_count += 1

                        except Exception as e:
                            print(f"读取文件失败: {file_path}, 错误: {e}")

                if added_count > 0 and self.sort_combo.currentIndex() == 0:
                    self.load_data()
                return

            # 3. 处理纯文本
            elif mime_data.hasText():
                text = mime_data.text().strip()
                if not text or text == self.last_clipboard_text:
                    return

                self.last_clipboard_text = text

                item, is_new = self.db.add_item(content=text, content_type='text')

                if is_new and self.sort_combo.currentIndex() == 0:
                    self.load_data()

        except Exception as e:
            print(f"处理剪贴板变更时出错: {e}")

    # === 分组功能 ===
    def group_selected_items(self):
        """将选中的多个项目分组并分配颜色"""
        selected_rows = self.table.selectionModel().selectedRows()
        if len(selected_rows) < 2:
            QMessageBox.information(self, "提示", "请至少选择2个项目进行分组")
            return

        # 获取选中项目的ID
        item_ids = []
        for index in selected_rows:
            row = index.row()
            item_id = int(self.table.item(row, 9).text())
            item_ids.append(item_id)

        # 生成唯一的随机颜色
        group_color = self.generate_unique_color()

        # 更新数据库
        session = self.db.get_session()
        try:
            for item_id in item_ids:
                item = session.query(ClipboardItem).get(item_id)
                if item:
                    item.group_color = group_color
            session.commit()
            self.statusBar().showMessage(f"已将 {len(item_ids)} 个项目分组,颜色: {group_color}")
        finally:
            session.close()

        # 刷新显示
        self.load_data()

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

    # === 窗口状态管理 ===
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

        # 恢复列对齐
        for i in range(self.table.columnCount()):
            alignment = settings.value(f"column_{i}_alignment")
            if alignment is not None:
                self.set_column_alignment(i, Qt.Alignment(int(alignment)))

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

if __name__ == "__main__":
    # 检查是否处于测试模式
    is_test_mode = len(sys.argv) > 1 and sys.argv[1] == '--run-test'

    app = QApplication(sys.argv)
    window = ClipboardApp()

    # 仅在非测试模式下显示窗口, 测试模式下由虚拟桌面管理
    if not is_test_mode:
        window.show()

    # 如果是测试模式，则运行增强版的自测试
    if is_test_mode:
        window.run_robust_self_test()

    sys.exit(app.exec_())
