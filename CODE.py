import sys
import os
import time
import logging
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QSplitter, QTreeView, QListView, QAbstractItemView,
    QLabel, QLineEdit, QPushButton, QMenu, QToolBar, QStatusBar,
    QMessageBox, QInputDialog, QFileDialog, QComboBox, QTabWidget,
    QDockWidget, QStackedWidget
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QDir, QSettings
from PyQt6.QtGui import QIcon, QPixmap, QAction, QKeySequence, QPalette, QColor, QFileSystemModel

from db_manager import DatabaseManager
from data_source_manager import DataSourceManager
from cache_manager import ThumbnailCache, MetadataCache, ThumbnailLoader
from enhanced_file_list import EnhancedFileListWidget, FileItemWidget
from table_view import FileTableView
from folder_browser import FolderBrowserWidget
from search_bar import SearchBar
from properties_panel import MetadataPanel, KeywordsPanel, FilterPanel
from favorites_manager import FavoritesManager
from draggable_favorites import DraggableFavoritesPanel
from logger import setup_logging, get_logger
from metadata_service import MetadataService

# 初始化日志
setup_logging()
logger = get_logger(__name__)

def apply_dark_theme(app):
    """应用深色主题"""
    logger.debug("应用深色主题")
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    
    app.setPalette(palette)
    
    app.setStyleSheet("""
        QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }
        QSplitter::handle { background-color: #2a2a2a; }
        QToolBar { border: none; background-color: #353535; spacing: 5px; }
        QLineEdit { background-color: #252525; color: white; border: 1px solid #555; padding: 4px; border-radius: 3px; }
        QListWidget { background-color: #252525; border: none; }
        QTreeView { background-color: #252525; border: none; }
        QTabWidget::pane { border: 1px solid #444; }
        QTabBar::tab { background: #353535; color: #aaa; padding: 5px 10px; border: 1px solid #444; border-bottom: none; }
        QTabBar::tab:selected { background: #454545; color: white; }
        QMainWindow { background-color: #353535; }
    """)

class FileLoaderThread(QThread):
    """后台加载文件列表线程 (极简双模式)"""
    batch_ready = pyqtSignal(list, list) # files, folders
    finished = pyqtSignal()

    def __init__(self, folder_path, sort_mode='name_asc', recursive=False, show_hidden=False, use_db_source=False, json_source=None):
        super().__init__()
        self.folder_path = folder_path
        self.sort_mode = sort_mode
        self.recursive = recursive
        self.show_hidden = show_hidden
        self.use_db = use_db_source
        self.json_source = json_source
        self.is_running = True

    def run(self):
        start_time = time.time()
        db = DatabaseManager()
        
        try:
            if self.use_db:
                self._load_from_db(db)
            else:
                self._load_from_json()
                
            logger.info(f"加载完成: {self.folder_path}, 耗时: {time.time() - start_time:.4f}s")
            
        except Exception as e:
            logger.error(f"加载出错: {e}", exc_info=True)
        finally:
            db.close()
            self.finished.emit()

    def _load_from_db(self, db):
        """从数据库加载 (全局模式)"""
        # 数据库模式通常用于递归视图
        all_files = db.get_files_recursive(self.folder_path)
        all_folders = db.get_folders_recursive(self.folder_path)

        if not self.show_hidden:
            all_files = [f for f in all_files if not os.path.basename(f['path']).startswith('.')]
            all_folders = [f for f in all_folders if not os.path.basename(f['path']).startswith('.')]
            
        self._sort_batch(all_files, all_folders)
        
        # 分批发送
        if all_folders:
            self.batch_ready.emit([], all_folders)
            QThread.msleep(20)
            
        chunk_size = 100
        for i in range(0, len(all_files), chunk_size):
            if not self.is_running: break
            chunk = all_files[i : i + chunk_size]
            self.batch_ready.emit(chunk, [])
            QThread.msleep(30)

    def _load_from_json(self):
        """从 JSON 加载 (局部模式)"""
        if not self.json_source:
            return

        all_items = self.json_source.get_all_items()
        all_files = []
        all_folders = []
        
        for item in all_items:
            if not self.show_hidden and os.path.basename(item.get('path', '')).startswith('.'):
                continue
            
            # 确保有 ID (使用哈希作为临时 ID)
            if 'id' not in item:
                item['id'] = abs(hash(item.get('path'))) % (10 ** 10)
                
            if item.get('is_folder'):
                if 'name' not in item:
                    item['name'] = os.path.basename(item.get('path'))
                all_folders.append(item)
            else:
                if 'filename' not in item:
                    item['filename'] = os.path.basename(item.get('path'))
                all_files.append(item)
        
        self._sort_batch(all_files, all_folders)
        
        if all_folders:
            self.batch_ready.emit([], all_folders)
            QThread.msleep(10)
            
        chunk_size = 100
        for i in range(0, len(all_files), chunk_size):
            if not self.is_running: break
            chunk = all_files[i : i + chunk_size]
            self.batch_ready.emit(chunk, [])
            QThread.msleep(20)

    def _sort_batch(self, files, folders):
        """排序列表"""
        if self.sort_mode == 'name_asc':
            folders.sort(key=lambda x: x.get('name', '').lower())
            files.sort(key=lambda x: x.get('filename', '').lower())
        elif self.sort_mode == 'name_desc':
            folders.sort(key=lambda x: x.get('name', '').lower(), reverse=True)
            files.sort(key=lambda x: x.get('filename', '').lower(), reverse=True)
        elif self.sort_mode == 'date_asc':
            folders.sort(key=lambda x: x.get('modified_time', 0))
            files.sort(key=lambda x: x.get('mtime', 0))
        elif self.sort_mode == 'date_desc':
            folders.sort(key=lambda x: x.get('modified_time', 0), reverse=True)
            files.sort(key=lambda x: x.get('mtime', 0), reverse=True)
        elif self.sort_mode == 'size_asc':
            files.sort(key=lambda x: x.get('size', 0))
        elif self.sort_mode == 'size_desc':
            files.sort(key=lambda x: x.get('size', 0), reverse=True)

    def stop(self):
        logger.info("停止文件加载线程")
        self.is_running = False
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("初始化主窗口")
        self.setWindowTitle("Python Bridge - 资源管理")
        self.resize(1600, 900)

        # 数据与状态
        self.db = DatabaseManager()
        self.db.init_db() # 初始化数据库并自动迁移架构
        
        # 数据源管理器（统一管理 SQLite 和 JSON）
        self.data_source = DataSourceManager(self.db)
        
        # 收藏夹管理器
        config_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        self.favorites_manager = FavoritesManager(config_dir)
        
        self.thumb_cache = ThumbnailCache()
        self.meta_cache = MetadataCache(self.db)
        
        # 元数据服务
        self.metadata_service = MetadataService(self.data_source)
        
        # 连接元数据变更信号到筛选器刷新 (新增)
        self.metadata_service.metadata_changed.connect(self._refresh_filter_stats)
        self.metadata_service.tags_changed.connect(self._refresh_filter_stats)
        
        self.current_tag_id = -1
        self.current_folder_path = None
        self.current_view_mode = 'grid'
        self.current_sort_mode = 'name_asc'
        
        # 视图选项
        self.show_hidden_files = False
        self.show_folders = True
        self.show_subfolders_content = False  # 递归显示子文件夹内容
        
        # 导航历史
        self.history = []
        self.history_index = -1
        self.is_navigating_history = False
        
        # 加载线程
        self.loader_thread = None

        # 中央布局
        self._setup_central_widget()
        
        # 初始化缩略图加载器 (必须在 UI 初始化之后)
        self.thumb_loader = ThumbnailLoader(self.thumb_cache)
        self.thumb_loader.thumbnail_ready.connect(self.file_table.update_thumbnail)

        # 菜单、工具栏与快捷键
        self.setup_menu_bar()
        self.setup_toolbar()
        self.setup_shortcuts()

        # 初始加载
        self.restore_settings()
        self._check_and_fix_db_schema()
        
        # 自动加载第一个收藏夹
        QThread.currentThread().setObjectName("MainThread")
        self.load_initial_path()
        
        self.statusBar().showMessage("准备就绪")
        logger.info("主窗口初始化完成")

    def restore_settings(self):
        """恢复界面设置"""
        settings = QSettings("PythonBridge", "FileManager")
        
        # 恢复窗口大小和位置
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            
        # 恢复分割器状态
        splitter_state = settings.value("splitterState")
        if splitter_state:
            # 找到 splitter
            splitter = self.findChild(QSplitter)
            if splitter:
                splitter.restoreState(splitter_state)
                
        # 恢复表格列宽
        header_state = settings.value("tableHeaderState")
        if header_state:
            self.file_table.horizontalHeader().restoreState(header_state)
    
    def closeEvent(self, event):
        """关闭窗口时保存设置"""
        settings = QSettings("PythonBridge", "FileManager")
        
        settings.setValue("geometry", self.saveGeometry())
        
        splitter = self.findChild(QSplitter)
        if splitter:
            settings.setValue("splitterState", splitter.saveState())
            
        # 保存表格列宽
        settings.setValue("tableHeaderState", self.file_table.horizontalHeader().saveState())
            
        super().closeEvent(event)

    def load_initial_path(self):
        """加载初始路径（第一个收藏夹）"""
        favorites = self.favorites_manager.get_favorites()
        if favorites:
            first_fav = favorites[0]
            path = first_fav['path']
            if os.path.exists(path):
                logger.info(f"启动自动加载收藏夹: {path}")
                self.load_path(path)
            else:
                logger.warning(f"初始收藏夹路径不存在: {path}")
        else:
            logger.info("没有收藏夹，不自动加载路径")

    def _check_and_fix_db_schema(self):
        """检查并修复数据库结构"""
        try:
            self.db.connect()
            cursor = self.db.conn.cursor()
            
            # 检查 files 表是否有 extension 列
            cursor.execute("PRAGMA table_info(files)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'extension' not in columns:
                logger.warning("files 表缺少 extension 列，尝试添加...")
                try:
                    cursor.execute("ALTER TABLE files ADD COLUMN extension TEXT")
                    self.db.conn.commit()
                    logger.info("成功添加 extension 列")
                except Exception as e:
                    logger.error(f"添加 extension 列失败: {e}")
            
        except Exception as e:
            logger.error(f"检查数据库结构失败: {e}")
        finally:
            self.db.close()

    def _setup_central_widget(self):
        """构建主界面布局"""
        logger.debug("设置中央组件")
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        main_layout.addWidget(splitter)

        # === 左侧面板 (文件夹/收藏) ===
        left_panel = QTabWidget()
        left_panel.setTabPosition(QTabWidget.TabPosition.North)
        
        # 文件夹标签页
        folder_tab = QWidget()
        folder_layout = QVBoxLayout(folder_tab)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加"添加当前文件夹"按钮
        add_fav_btn = QPushButton("添加当前文件夹")
        add_fav_btn.clicked.connect(self.add_current_to_favorites)
        folder_layout.addWidget(add_fav_btn)
        
        self.folder_browser = FolderBrowserWidget()
        self.folder_browser.folder_selected.connect(self.on_folder_selected)
        folder_layout.addWidget(self.folder_browser)
        left_panel.addTab(folder_tab, "文件夹")
        
        # 收藏夹标签页
        fav_tab = QWidget()
        fav_layout = QVBoxLayout(fav_tab)
        fav_layout.setContentsMargins(0, 0, 0, 0)
        
        self.favorites_panel = DraggableFavoritesPanel(self.favorites_manager)
        self.favorites_panel.favorite_clicked.connect(self.load_path)
        
        fav_layout.addWidget(self.favorites_panel)
        left_panel.addTab(fav_tab, "收藏夹")

        splitter.addWidget(left_panel)

        # === 中间面板 (文件列表) ===
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用 QStackedWidget 管理多视图
        self.view_stack = QStackedWidget()
        
        # 1. 网格视图 (EnhancedFileListWidget)
        self.file_list = EnhancedFileListWidget(self.thumb_cache, self.metadata_service)
        self.file_list.item_clicked.connect(self.on_file_clicked)
        self.file_list.selection_changed.connect(self.on_selection_changed_list)
        self.file_list.go_up_requested.connect(self._handle_go_up)
        self.file_list.rename_file_requested.connect(self._handle_inline_rename)
        self.view_stack.addWidget(self.file_list)
        
        # 2. 表格视图 (FileTableView)
        self.file_table = FileTableView()
        self.file_table.item_clicked.connect(self.on_file_clicked)
        self.file_table.selection_changed.connect(self.on_selection_changed_list)
        self.file_table.item_double_clicked.connect(self.on_file_double_clicked) # 需要实现这个方法
        self.view_stack.addWidget(self.file_table)
        
        center_layout.addWidget(self.view_stack)
        splitter.addWidget(center_panel)

        # 设置初始比例 (左侧 : 中间)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1000])

        self.setCentralWidget(central)
        
        # === 右侧面板 (拆分为三个独立 Dock) ===
        
        # 1. 元数据面板
        self.metadata_dock = QDockWidget("元数据", self)
        self.metadata_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.metadata_panel = MetadataPanel(self.metadata_service)
        self.metadata_panel.tag_submitted.connect(self.on_quick_tag_requested)
        self.metadata_dock.setWidget(self.metadata_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.metadata_dock)
        
        # 2. 筛选器面板
        self.filter_dock = QDockWidget("筛选器", self)
        self.filter_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.filter_panel = FilterPanel(self.db)
        self.filter_panel.filter_changed.connect(self.on_filter_changed)
        self.filter_dock.setWidget(self.filter_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.filter_dock)
        
        # 设置 Dock 嵌套
        self.setDockNestingEnabled(True)
        # 默认垂直排列（只有元数据和筛选器）
        self.splitDockWidget(self.metadata_dock, self.filter_dock, Qt.Orientation.Vertical)

    def setup_toolbar(self):
        """设置工具栏"""
        logger.debug("设置工具栏")
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 导航按钮
        self.back_action = QAction("←", self)
        self.back_action.setToolTip("后退")
        self.back_action.triggered.connect(self.go_back)
        self.back_action.setEnabled(False)
        toolbar.addAction(self.back_action)
        
        self.forward_action = QAction("→", self)
        self.forward_action.setToolTip("前进")
        self.forward_action.triggered.connect(self.go_forward)
        self.forward_action.setEnabled(False)
        toolbar.addAction(self.forward_action)
        
        self.up_action = QAction("↑", self)
        self.up_action.setToolTip("上级目录")
        self.up_action.triggered.connect(self.go_up)
        toolbar.addAction(self.up_action)
        
        toolbar.addSeparator()
        
        # 地址栏
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("输入路径...")
        self.path_edit.returnPressed.connect(lambda: self.load_path(self.path_edit.text()))
        toolbar.addWidget(self.path_edit)
        
        toolbar.addSeparator()
        
        # 搜索栏
        self.search_bar = SearchBar()
        self.search_bar.setMaximumWidth(250)
        self.search_bar.search_triggered.connect(self.search_files)
        toolbar.addWidget(self.search_bar)
        
        toolbar.addSeparator()

        # 排序选项
        sort_label = QLabel("排序:")
        toolbar.addWidget(sort_label)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "名称↑", "名称↓", 
            "修改时间↑", "修改时间↓",
            "大小↑", "大小↓"
        ])
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        toolbar.addWidget(self.sort_combo)
        
        toolbar.addSeparator()

        # 视图切换
        grid_view_action = QAction("📅", self)
        grid_view_action.setToolTip("网格视图")
        grid_view_action.triggered.connect(lambda: self.switch_view_mode('grid'))
        toolbar.addAction(grid_view_action)
        
        list_view_action = QAction("☰", self)
        list_view_action.setToolTip("列表视图")
        list_view_action.triggered.connect(lambda: self.switch_view_mode('list'))
        toolbar.addAction(list_view_action)
        
        refresh_action = QAction("↻", self)
        refresh_action.setToolTip("刷新")
        refresh_action.triggered.connect(self.refresh_current_view)
        toolbar.addAction(refresh_action)

    def setup_menu_bar(self):
        """初始化菜单栏"""
        logger.debug("设置菜单栏")
        menubar = self.menuBar()

        # 视图菜单
        view_menu = menubar.addMenu("视图")
        
        # 显示隐藏文件
        self.show_hidden_action = QAction("显示隐藏文件", self, checkable=True)
        self.show_hidden_action.setChecked(self.show_hidden_files)
        self.show_hidden_action.triggered.connect(self.toggle_show_hidden_files)
        view_menu.addAction(self.show_hidden_action)
        
        # 显示文件夹
        self.show_folders_action = QAction("显示文件夹", self, checkable=True)
        self.show_folders_action.setChecked(self.show_folders)
        self.show_folders_action.triggered.connect(self.toggle_show_folders)
        view_menu.addAction(self.show_folders_action)

        # 显示子文件夹内容
        self.show_subfolders_action = QAction("显示子文件夹中的项目", self, checkable=True)
        self.show_subfolders_action.setChecked(self.show_subfolders_content)
        self.show_subfolders_action.triggered.connect(self.toggle_show_subfolders_content)
        view_menu.addAction(self.show_subfolders_action)
        
        view_menu.addSeparator()

        # 评级快捷键 (Ctrl+0-5)
        for i in range(6):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{i}"))
            action.triggered.connect(lambda checked, r=i: self.set_selected_rating(r))
            self.addAction(action)
        
        # 颜色 (Ctrl+6-9)
        color_map = {6: 'red', 7: 'yellow', 8: 'green', 9: 'blue'}
        for key, color in color_map.items():
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{key}"))
            action.triggered.connect(lambda checked, c=color: self.set_selected_color(c))
            self.addAction(action)
        
        # 置顶 (Ctrl+P)
        pin_action = QAction(self)
        pin_action.setShortcut(QKeySequence("Ctrl+P"))
        pin_action.triggered.connect(self.toggle_selected_pin)
        self.addAction(pin_action)
        
        # 搜索 (Ctrl+F)
        search_action = QAction(self)
        search_action.setShortcut(QKeySequence("Ctrl+F"))
        search_action.triggered.connect(lambda: self.search_bar.setFocus())
        self.addAction(search_action)

    def toggle_show_hidden_files(self, checked):
        """切换显示隐藏文件"""
        self.show_hidden_files = checked
        logger.info(f"显示隐藏文件: {checked}")
        self.refresh_current_view()

    def toggle_show_folders(self, checked):
        """切换显示文件夹"""
        self.show_folders = checked
        logger.info(f"显示文件夹: {checked}")
        self.refresh_current_view()

    def toggle_show_subfolders_content(self, checked):
        """切换显示子文件夹内容（递归）"""
        self.show_subfolders_content = checked
        logger.info(f"显示子文件夹内容: {checked}")
        self.refresh_current_view()

    # ================= 导航逻辑 =================
    
    def load_path(self, path):
        """加载指定路径"""
        # 处理搜索伪协议
        if path.startswith("search://"):
            self._perform_search(path[9:])
            self._update_history(path)
            return

        path = os.path.normpath(path)
        if not os.path.exists(path) or not os.path.isdir(path):
            self.statusBar().showMessage(f"路径不存在: {path}")
            return

        self._update_history(path)
        self.current_folder_path = path
        self.current_tag_id = -1
        self.path_edit.setText(path)
        self.setWindowTitle(f"Python Bridge - {os.path.basename(path)}")
        self.folder_browser.expand_path(path)
        
        # 极简双模式判断
        if self.show_subfolders_content:
            # 全局模式 (数据库)
            self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
            self._start_loading(path, use_db=True)
        else:
            # 局部模式 (JSON)
            self.data_source.set_scope(DataSourceManager.SCOPE_LOCAL, path)
            self._start_loading(path, use_db=False)

    def _update_history(self, path):
        """更新导航历史"""
        if not self.is_navigating_history:
            if self.history_index < len(self.history) - 1:
                self.history = self.history[:self.history_index+1]
            self.history.append(path)
            self.history_index += 1
            self.update_nav_buttons()

    def _perform_search(self, keyword):
        """执行实际的搜索逻辑"""
        logger.info(f"执行搜索: {keyword}")
        self.current_folder_path = None # 搜索结果不是物理文件夹
        self.path_edit.setText(f"search://{keyword}")
        self.setWindowTitle(f"Python Bridge - 搜索: {keyword}")
        
        # 设置数据源为全局范围
        self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
        
        # 1. 搜索文件
        files = self.db.search_files_by_name(keyword)
        tag_files = self.db.search_files_by_tag_name(keyword)
        
        # 2. 搜索文件夹
        folders = self.db.search_folders_by_name(keyword)
        tag_folders = self.db.search_folders_by_tag_name(keyword)
        
        # 合并文件结果并去重
        seen_ids = {f['id'] for f in files}
        for f in tag_files:
            if f['id'] not in seen_ids:
                files.append(f)
                seen_ids.add(f['id'])
        
        # 合并文件夹结果并去重
        seen_folder_ids = {f['id'] for f in folders}
        for f in tag_folders:
            if f['id'] not in seen_folder_ids:
                folders.append(f)
                seen_folder_ids.add(f['id'])
        
        # 直接更新UI (不使用 loader thread)
        self.file_list.clear()
        self.file_list.append_files(files, folders)
        
        self.file_table.setRowCount(0)
        self.file_table.setSortingEnabled(False)
        for folder in folders:
            self.file_table.add_item(folder, is_folder=True)
        for file in files:
            self.file_table.add_item(file, is_folder=False)
        self.file_table.setSortingEnabled(True)
        
        all_items = files + folders
        self.filter_panel.update_facets(all_items)
        self._apply_active_filters()
        self.statusBar().showMessage(f"搜索完成: {len(all_items)} 个结果")

    def _start_loading(self, path, use_db):
        """启动加载 (极简双模式)"""
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.stop()
        
        self.file_list.clear()
        self.file_table.setRowCount(0)
        self.statusBar().showMessage(f"正在加载: {path}...")
        
        # 获取 JSON 源 (仅在非 DB 模式下)
        json_source = None if use_db else getattr(self.data_source, 'json_source', None)
        
        self.loader_thread = FileLoaderThread(
            path, 
            self.current_sort_mode, 
            recursive=self.show_subfolders_content,
            show_hidden=self.show_hidden_files,
            use_db_source=use_db,
            json_source=json_source
        )
        self.loader_thread.batch_ready.connect(self.on_files_batch_ready)
        self.loader_thread.finished.connect(lambda: self.statusBar().showMessage(f"加载完成: {path}"))
        self.loader_thread.start()

    def on_files_batch_ready(self, files, folders):
        """接收后台线程加载的一批文件"""
        t0 = time.time()
        # logger.debug(f"收到文件批次: {len(files)} 文件, {len(folders)} 文件夹")
        
        # === 关键修复：合并 JSON 元数据 ===
        # 从 DataSourceManager 读取元数据（优先 JSON），更新 file_data
        for file_data in files:
            path = file_data.get('path')
            if path:
                metadata = self.data_source.get_item_metadata(path)
                # 更新元数据字段
                file_data['is_pinned'] = metadata.get('is_pinned', file_data.get('is_pinned', 0))
                file_data['rating'] = metadata.get('rating', file_data.get('rating', 0))
                file_data['label_color'] = metadata.get('label_color', file_data.get('label_color'))
        
        for folder_data in folders:
            path = folder_data.get('path')
            if path:
                metadata = self.data_source.get_item_metadata(path)
                folder_data['is_pinned'] = metadata.get('is_pinned', folder_data.get('is_pinned', 0))
                folder_data['rating'] = metadata.get('rating', folder_data.get('rating', 0))
                folder_data['label_color'] = metadata.get('label_color', folder_data.get('label_color'))
        
        # 如果不显示文件夹，清空文件夹列表
        if not self.show_folders:
            folders = []
            
        # 1. 更新网格视图
        self.file_list.append_files(files, folders)
        
        # 2. 更新表格视图（使用 append_files 而不是 load_files，避免清空已有数据）
        self.file_table.append_files(files, folders)
        
        # 刷新统计 (从当前视图获取)
        self._refresh_filter_stats()
        
        self._apply_active_filters()
        
        # 启动缩略图加载 (仅针对文件)
        if files:
            self.thumb_loader.add_paths([f['path'] for f in files])
            if not self.thumb_loader.isRunning():
                self.thumb_loader.start()

    def setup_shortcuts(self):
        """设置快捷键"""
        # 刷新 F5
        refresh_shortcut = QAction(self)
        refresh_shortcut.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_shortcut.triggered.connect(self.refresh_current_view)
        self.addAction(refresh_shortcut)

    def on_file_double_clicked(self, file_data):
        """文件双击处理"""
        path = file_data.get('path')
        if not path: return
        
        if os.path.isdir(path):
            self.load_path(path)
        else:
            # 打开文件
            try:
                os.startfile(path)
            except Exception as e:
                logger.error(f"无法打开文件: {e}")
                QMessageBox.warning(self, "错误", f"无法打开文件:\n{e}")

    
    def add_current_to_favorites(self):
        """将当前文件夹添加到收藏夹"""
        if self.current_folder_path and os.path.exists(self.current_folder_path):
            self.favorites_manager.add_favorite(self.current_folder_path)
        else:
            QMessageBox.warning(self, "提示", "当前没有打开的文件夹")

    def go_back(self):
        """后退"""
        logger.info("后退导航")
        if self.history_index > 0:
            self.is_navigating_history = True
            self.history_index -= 1
            self.load_path(self.history[self.history_index])
            self.is_navigating_history = False
            self.update_nav_buttons()

    def go_forward(self):
        """前进"""
        logger.info("前进导航")
        if self.history_index < len(self.history) - 1:
            self.is_navigating_history = True
            self.history_index += 1
            self.load_path(self.history[self.history_index])
            self.is_navigating_history = False
            self.update_nav_buttons()

    def go_up(self):
        """上级目录"""
        logger.info("上级目录")
        if self.current_folder_path:
            parent = os.path.dirname(self.current_folder_path)
            if parent and os.path.exists(parent):
                self.load_path(parent)

    def update_nav_buttons(self):
        """更新导航按钮状态"""
        self.back_action.setEnabled(self.history_index > 0)
        self.forward_action.setEnabled(self.history_index < len(self.history) - 1)

    def on_folder_selected(self, folder_path):
        """左侧树选中文件夹"""
        logger.info(f"文件夹树选择: {folder_path}")
        self.load_path(folder_path)

    def on_sort_changed(self, index):
        """排序方式改变"""
        sort_modes = ['name_asc', 'name_desc', 'date_asc', 'date_desc', 'size_asc', 'size_desc']
        self.current_sort_mode = sort_modes[index]
        logger.info(f"排序方式改变: {self.current_sort_mode}")
        self.refresh_current_view()

    # ================= 业务逻辑 =================

    def on_file_clicked(self, path):
        """文件被点击"""
        logger.info(f"文件被点击: {path}")
        if os.path.isdir(path):
            # 点击文件夹,导航进入
            self.load_path(path)
        else:
            # 点击文件,更新属性面板
            file_id = self.db.upsert_file(path)
            if file_id:
                file_data = self.db.get_file_by_id(file_id)
                if file_data:
                    thumb_path = self.thumb_cache.get_thumbnail(path)
                    self.metadata_panel.update_info(file_data, thumb_path)
                    self.keywords_panel.set_file(file_data)
                    self.metadata_panel.set_tag_input_enabled(True)


    def on_selection_changed_list(self, paths):
        """选择改变(来自文件列表)"""
        logger.debug(f"选择改变: {len(paths)} 个项目")
        if not paths:
            self.metadata_panel.clear()
            self.keywords_panel.clear()
            return
        
        # 统计文件和文件夹数量
        file_count = sum(1 for p in paths if os.path.isfile(p))
        total_count = len(paths)
        
        if total_count == 1 and file_count == 1:
            # 单个文件被选中
            path = paths[0]
            file_id = self.db.upsert_file(path)
            if file_id:
                file_data = self.db.get_file_by_id(file_id)
                if file_data:
                    thumb_path = self.thumb_cache.get_thumbnail(path)
                    self.metadata_panel.update_info(file_data, thumb_path)
                    self.keywords_panel.set_file(file_data)
                    self.metadata_panel.set_tag_input_enabled(True)
        else:
            # 多个项目被选中
            self.metadata_panel.clear()
            self.keywords_panel.clear()
            self.metadata_panel.show_selection_summary(total_count, file_count)

    def on_selection_changed(self):
        """选择改变时更新属性面板"""
        logger.debug("选择改变")
        selected_items = self.file_list.selectedItems()
        total = len(selected_items)
        if total == 0:
            self.properties_panel.clear()
            return

        file_items = [item for item in selected_items if not item.data(Qt.ItemDataRole.UserRole + 1)]

        if total == 1 and file_items:
            item = file_items[0]
            file_data = item.data(Qt.ItemDataRole.UserRole)
            thumb_path = self.thumb_cache.get_thumbnail(file_data['path'])
            self.metadata_panel.update_info(file_data, thumb_path)
            self.keywords_panel.set_file(file_data)
            self.metadata_panel.set_tag_input_enabled(True)
        else:
            self.metadata_panel.clear()
            self.keywords_panel.clear()
            self.metadata_panel.show_selection_summary(total, len(file_items))

    def load_files_by_tag(self, tag_id):
        """加载标签文件"""
        logger.info(f"加载标签文件: tag_id={tag_id}")
        self.current_tag_id = tag_id
        self.current_folder_path = None
        self.path_edit.clear()
        
        # 设置数据源为全局范围
        self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
        logger.info("数据源切换到全局范围（标签筛选）")
        
        if tag_id == -1:
            files = self.db.get_all_files()
            self.setWindowTitle("Python Bridge - 所有文件")
        else:
            files = self.db.get_files_by_tag(tag_id)
            self.setWindowTitle(f"Python Bridge - 标签筛选")
        
        self.file_list.load_files(files)
        self._apply_active_filters()

    def search_files(self, keyword):
        """搜索文件和文件夹"""
        logger.info(f"搜索: {keyword}")
        if not keyword:
            return
        self.load_path(f"search://{keyword}")

    def batch_add_tags(self):
        """批量添加标签"""
        logger.info("批量添加标签")
        selected_items = self.file_list.selectedItems()
        if not selected_items: 
            return
        
        tags = self.db.get_all_tags()
        if not tags:
            QMessageBox.warning(self, "提示", "请先创建标签")
            return
            
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "批量添加标签", "选择标签:", tag_names, 0, False)
        
        if ok and tag_name:
            count = 0
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if 'path' in file_data:
                    self.metadata_service.add_tag(file_data['path'], tag_name)
                    count += 1
            self.statusBar().showMessage(f"已添加标签 '{tag_name}' 到 {count} 个项目")

    def batch_remove_tags(self):
        """批量移除标签"""
        logger.info("批量移除标签")
        selected_items = self.file_list.selectedItems()
        if not selected_items: 
            return
        
        tags = self.db.get_all_tags()
        if not tags:
            QMessageBox.warning(self, "提示", "没有可用的标签")
            return
            
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "批量移除标签", "选择标签:", tag_names, 0, False)
        
        if ok and tag_name:
            count = 0
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if 'path' in file_data:
                    self.metadata_service.remove_tag(file_data['path'], tag_name)
                    count += 1
            self.statusBar().showMessage(f"已从 {count} 个项目移除标签 '{tag_name}'")

    def batch_delete_files(self):
        """批量删除文件记录"""
        logger.info("批量删除文件记录")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return
        
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 {len(selected_items)} 个文件记录吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.delete_file(file_data['id'])
            self.refresh_current_view()

    def _handle_go_up(self):
        """处理退格键返回上一级"""
        if self.current_folder_path:
            parent = os.path.dirname(self.current_folder_path)
            if parent and os.path.exists(parent):
                self.load_path(parent)
    
    def _handle_inline_rename(self, old_path, new_name):
        """处理内嵌重命名"""
        try:
            directory = os.path.dirname(old_path)
            new_path = os.path.join(directory, new_name)
            
            if os.path.exists(new_path):
                QMessageBox.warning(self, "错误", "文件名已存在")
                self.refresh_current_view()
                return
                
            # 重命名文件
            os.rename(old_path, new_path)
            
            # 更新数据库
            self.db.rename_file(old_path, new_path, new_name)
            
            # 刷新列表
            self.refresh_current_view()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"重命名失败: {e}")
            self.refresh_current_view()

    def on_quick_tag_requested(self, tag_name):
        """快速标签请求"""
        logger.info(f"快速标签请求: {tag_name}")
        tag_name = tag_name.strip()
        if not tag_name: return

        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先选择至少一个文件")
            return

        if len(selected_items) > 10:
            reply = QMessageBox.question(self, "提示", "批量添加标签, 是否继续", 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        updated = 0
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            if 'path' in file_data:
                self.metadata_service.add_tag(file_data['path'], tag_name)
                updated += 1

        QMessageBox.information(self, "完成", f"已为 {updated} 个文件添加标签 '{tag_name}'")

    def on_tag_added_from_panel(self, tag_name):
        """关键字面板：添加标签"""
        path = self.keywords_panel.current_file_path
        if path:
            self.metadata_service.add_tag(path, tag_name)

    def on_tag_removed_from_panel(self, tag_name):
        """关键字面板：移除标签"""
        path = self.keywords_panel.current_file_path
        if path:
            self.metadata_service.remove_tag(path, tag_name)

    def on_tag_created_from_panel(self, tag_name):
        """关键字面板：创建并添加标签"""
        path = self.keywords_panel.current_file_path
        if path:
            self.metadata_service.add_tag(path, tag_name)

    def on_filter_changed(self, filters):
        """筛选器改变"""
        logger.debug(f"筛选器改变: {filters}")
        self.file_list.apply_filters(filters)
        self.file_table.apply_filters(filters)

    def set_selected_color(self, color):
        """设置选中文件/文件夹颜色"""
        logger.info(f"========== 设置选中项颜色: {color} ==========")
        selected_items = self.file_list.selectedItems()
        if selected_items:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if file_data and 'path' in file_data:
                    self.metadata_service.set_color_label(file_data['path'], color)
            self.refresh_current_view()

    def set_selected_rating(self, rating):
        """设置选中文件/文件夹评级"""
        logger.info(f"========== 设置选中项评级: {rating} ==========")
        selected_items = self.file_list.selectedItems()
        if selected_items:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if file_data and 'path' in file_data:
                    self.metadata_service.set_rating(file_data['path'], rating)
            self.refresh_current_view()

    def toggle_selected_pin(self):
        """切换选中文件/文件夹置顶状态"""
        logger.info("========== 切换选中项置顶状态 ==========")
        selected_items = self.file_list.selectedItems()
        if selected_items:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if file_data and 'path' in file_data:
                    self.metadata_service.toggle_pin(file_data['path'])
            self.refresh_current_view()
        else:
            logger.warning("没有选中任何项目！")

    def _refresh_filter_stats(self, *args):
        """刷新筛选器统计 (元数据变更后调用)"""
        all_items = []
        
        # 根据当前视图获取所有项目
        if self.current_view_mode == 'list':
            # 表格视图
            for row in range(self.file_table.rowCount()):
                if not self.file_table.isRowHidden(row):
                    item = self.file_table.item(row, 0)
                    data = item.data(Qt.ItemDataRole.UserRole)
                    all_items.append(data)
        else:
            # 网格视图
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                if not item.isHidden():
                    data = item.data(Qt.ItemDataRole.UserRole)
                    all_items.append(data)
        
        if all_items:
            self.filter_panel.update_facets(all_items)

    def _apply_active_filters(self):
        """应用当前激活的筛选器"""
        filters = self.filter_panel.get_filters()
        self.file_list.apply_filters(filters)
        self.file_table.apply_filters(filters)

    def switch_view_mode(self, mode):
        """切换视图模式"""
        logger.info(f"切换视图模式: {mode}")
        self.current_view_mode = mode
        
        if mode == 'list':
            self.view_stack.setCurrentWidget(self.file_table)
        else:
            self.view_stack.setCurrentWidget(self.file_list)
            # 网格视图内部也有 view_mode (icon/list)，这里统一设为 icon
            self.file_list.set_view_mode('icon') # 强制为图标模式
            
        # 切换后刷新统计
        self._refresh_filter_stats()

    def refresh_current_view(self):
        """刷新当前视图"""
        logger.info("刷新当前视图")
        if self.current_folder_path:
            self.load_path(self.current_folder_path)
        elif self.current_tag_id != -1:
            self.load_files_by_tag(self.current_tag_id)
        else:
            self.load_files_by_tag(-1)

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("启动 Python Bridge 应用程序")
    logger.info("=" * 60)
    
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    
    logger.info("主窗口已显示")
    sys.exit(app.exec())
