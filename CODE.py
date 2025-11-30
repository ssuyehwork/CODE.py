# =================== 1 ===================

# main.py
import sys
import os
import time
import logging
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QSplitter, QLabel, QFileDialog, QInputDialog,
                             QToolBar, QMessageBox, QTabWidget, QStyleFactory, QListWidget,
                             QLineEdit, QPushButton, QMenu, QListWidgetItem, QComboBox)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QDir, QSettings
from PyQt6.QtGui import QIcon, QPixmap, QAction, QKeySequence, QPalette, QColor

from db_manager import DatabaseManager
from data_source_manager import DataSourceManager
from cache_manager import ThumbnailCache, MetadataCache
from enhanced_file_list import EnhancedFileListWidget, FileItemWidget
from folder_browser import FolderBrowserWidget
from search_bar import SearchBar
from properties_panel import PropertiesPanel
from draggable_favorites import DraggableFavoritesPanel
from logger import setup_logging, get_logger

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
    """后台加载文件列表线程"""
    batch_ready = pyqtSignal(list, list) # files, folders
    finished = pyqtSignal()

    def __init__(self, folder_path, sort_mode='name_asc', recursive=False, show_hidden=False, use_db_source=False):
        super().__init__()
        self.folder_path = folder_path
        self.sort_mode = sort_mode
        self.recursive = recursive
        self.show_hidden = show_hidden
        self.use_db_source = use_db_source
        self.is_running = True
        logger.info(f"FileLoaderThread 初始化: path={folder_path}, sort={sort_mode}, recursive={recursive}, hidden={show_hidden}, db_source={use_db_source}")

    def run(self):
        start_time = time.time()
        db = DatabaseManager()
        files_batch = []
        folders_batch = []
        
        try:
            logger.info(f"开始加载: {self.folder_path}")
            
            if self.use_db_source:
                # === 数据库模式 ===
                logger.info("使用数据库模式加载")
                all_files = db.get_files_recursive(self.folder_path)
                all_folders = db.get_folders_recursive(self.folder_path)
                
                if not self.show_hidden:
                    all_files = [f for f in all_files if not os.path.basename(f['path']).startswith('.')]
                    all_folders = [f for f in all_folders if not os.path.basename(f['path']).startswith('.')]
                
                logger.info(f"数据获取耗时: {time.time() - start_time:.4f}s")
                
                # 排序
                self._sort_batch(all_files, all_folders)
                
                logger.info(f"处理完成: {len(all_files)} 文件, {len(all_folders)} 文件夹")
                
                # 分批发射数据，避免界面卡顿
                # 先发送所有文件夹
                if all_folders:
                    self.batch_ready.emit([], all_folders)
                    QThread.msleep(20)
                
                # 分批发送文件
                chunk_size = 100 # 每次发送100个文件
                total_files = len(all_files)
                for i in range(0, total_files, chunk_size):
                    if not self.is_running: break
                    chunk = all_files[i : i + chunk_size]
                    self.batch_ready.emit(chunk, [])
                    # 给主线程一点时间处理UI
                    QThread.msleep(30)
                    
            else:
                # === 磁盘扫描模式 ===
                logger.info("使用磁盘扫描模式加载")
                if not os.path.exists(self.folder_path):
                    logger.warning(f"路径不存在: {self.folder_path}")
                    return

                def iterate_items():
                    if self.recursive:
                        for root, dirs, files in os.walk(self.folder_path):
                            for d in dirs:
                                yield os.path.join(root, d), True
                            for f in files:
                                yield os.path.join(root, f), False
                    else:
                        for item_name in os.listdir(self.folder_path):
                            yield os.path.join(self.folder_path, item_name), os.path.isdir(os.path.join(self.folder_path, item_name))

                count = 0
                for item_path, is_dir in iterate_items():
                    if not self.is_running: 
                        logger.info("加载被中断")
                        break
                    
                    item_name = os.path.basename(item_path)
                    
                    if not self.show_hidden and item_name.startswith('.'):
                        continue
                    
                    try:
                        if is_dir:
                            folder_id = db.upsert_folder(item_path, recursive=False)
                            if folder_id:
                                folder_data = db.get_folder_by_path(item_path)
                                if folder_data:
                                    folders_batch.append(folder_data)
                        else:
                            file_id = db.upsert_file(item_path)
                            if file_id:
                                file_data = db.get_file_by_id(file_id)
                                if file_data:
                                    files_batch.append(file_data)
                        
                        count += 1
                        # 磁盘模式下，每500个发送一次，或者每隔一段时间发送一次
                        # 这里复用之前的逻辑：收集到 batch 后发送
                        # 但之前的逻辑是全部收集完才发送？不，之前的逻辑是最后才发送。
                        # 应该改为每收集一定数量就发送。
                        
                        if len(files_batch) + len(folders_batch) >= 100:
                            self._sort_batch(files_batch, folders_batch)
                            self.batch_ready.emit(files_batch, folders_batch)
                            files_batch = []
                            folders_batch = []
                            QThread.msleep(20)
                                    
                    except Exception as e:
                        logger.error(f"处理项目失败 {item_name}: {e}")
                
                # 发送剩余的
                if files_batch or folders_batch:
                    self._sort_batch(files_batch, folders_batch)
                    self.batch_ready.emit(files_batch, folders_batch)
            
            logger.info(f"文件夹加载完成: {self.folder_path}")
                
        except Exception as e:
            logger.error(f"加载出错: {e}", exc_info=True)
        finally:
            db.close()
            self.finished.emit()

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
        
        self.thumb_cache = ThumbnailCache()
        self.meta_cache = MetadataCache(self.db)
        
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
    
    def closeEvent(self, event):
        """关闭窗口时保存设置"""
        settings = QSettings("PythonBridge", "FileManager")
        
        settings.setValue("geometry", self.saveGeometry())
        
        splitter = self.findChild(QSplitter)
        if splitter:
            settings.setValue("splitterState", splitter.saveState())
            
        super().closeEvent(event)

    def load_initial_path(self):
        """加载初始路径（第一个收藏夹）"""
        favorites = self.db.get_all_favorites()
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
        
        self.favorites_panel = DraggableFavoritesPanel(self.db)
        self.favorites_panel.favorite_clicked.connect(self.load_path)
        
        fav_layout.addWidget(self.favorites_panel)
        left_panel.addTab(fav_tab, "收藏夹")

        splitter.addWidget(left_panel)

        # === 中间面板 (文件列表) ===
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        self.file_list = EnhancedFileListWidget(self.thumb_cache)
        self.file_list.item_clicked.connect(self.on_file_clicked)
        self.file_list.selection_changed.connect(self.on_selection_changed_list)
        self.file_list.go_up_requested.connect(self._handle_go_up)
        self.file_list.rename_file_requested.connect(self._handle_inline_rename)
        
        center_layout.addWidget(self.file_list)
        splitter.addWidget(center_panel)

        # === 右侧面板 (属性/元数据) ===
        self.properties_panel = PropertiesPanel(self.db)
        self.properties_panel.rating_changed.connect(self.on_rating_changed)
        self.properties_panel.tag_added.connect(self.on_tag_added)
        self.properties_panel.tag_removed.connect(self.on_tag_removed)
        self.properties_panel.tag_created.connect(self.on_tag_created)
        self.properties_panel.filter_changed.connect(self.on_filter_changed)
        self.properties_panel.quick_tag_requested.connect(self.on_quick_tag_requested)
        splitter.addWidget(self.properties_panel)

        # 设置初始比例
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 1000, 300])

        self.setCentralWidget(central)

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
        
        # 显示子文件夹中的项目（递归）
        self.show_sub_content_action = QAction("显示子文件夹中的项目(全局范围)", self, checkable=True)
        self.show_sub_content_action.setChecked(self.show_subfolders_content)
        self.show_sub_content_action.triggered.connect(self.toggle_show_subfolders_content)
        view_menu.addAction(self.show_sub_content_action)

    def setup_shortcuts(self):
        """设置键盘快捷键"""
        logger.debug("设置快捷键")
        # 评级 (Ctrl+0-5)
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
        logger.info(f"加载路径: {path}")
        path = os.path.normpath(path)
        if not os.path.exists(path) or not os.path.isdir(path):
            logger.warning(f"路径不存在或不是目录: {path}")
            self.statusBar().showMessage(f"路径不存在: {path}")
            return

        # 更新历史记录
        if not self.is_navigating_history:
            if self.history_index < len(self.history) - 1:
                self.history = self.history[:self.history_index+1]
            self.history.append(path)
            self.history_index += 1
            self.update_nav_buttons()
        
        self.current_folder_path = path
        self.current_tag_id = -1
        self.path_edit.setText(path)
        self.setWindowTitle(f"Python Bridge - {os.path.basename(path)}")
        
        # 根据视图模式设置数据源范围
        use_db_source = False
        if self.show_subfolders_content:
            # 递归显示子文件夹内容时，使用全局范围（SQLite）
            # 并且使用数据库作为数据源，而不是扫描磁盘
            self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
            use_db_source = True
            logger.info(f"数据源切换到全局范围（递归视图 - 数据库模式）: {path}")
        else:
            # 普通文件夹视图，使用局部范围（JSON + DB）
            self.data_source.set_scope(DataSourceManager.SCOPE_LOCAL, path)
            logger.info(f"数据源切换到局部范围: {path}")
        
        # 同步左侧树
        self.folder_browser.expand_path(path)
        
        # 开始异步加载
        self.start_async_loading(path, use_db_source=use_db_source)

    def start_async_loading(self, path, use_db_source=False):
        """启动异步加载线程"""
        logger.info(f"启动异步加载: {path}, recursive={self.show_subfolders_content}, hidden={self.show_hidden_files}, db_source={use_db_source}")
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.stop()
        
        self.file_list.clear()
        self.statusBar().showMessage(f"正在加载: {path}...")
        
        self.loader_thread = FileLoaderThread(
            path, 
            self.current_sort_mode, 
            recursive=self.show_subfolders_content,
            show_hidden=self.show_hidden_files,
            use_db_source=use_db_source
        )
        self.loader_thread.batch_ready.connect(self.on_files_batch_ready)
        self.loader_thread.finished.connect(lambda: self.statusBar().showMessage(f"加载完成: {path}"))
        self.loader_thread.start()

    def on_files_batch_ready(self, files, folders):
        """接收后台线程加载的一批文件"""
        t0 = time.time()
        logger.debug(f"收到文件批次: {len(files)} 文件, {len(folders)} 文件夹")
        
        # 如果不显示文件夹，清空文件夹列表
        if not self.show_folders:
            folders = []
            
        # 使用 EnhancedFileListWidget 的 append_files 方法
        self.file_list.append_files(files, folders)
        logger.info(f"UI渲染耗时: {time.time() - t0:.4f}s")
        
        all_files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not item.data(Qt.ItemDataRole.UserRole + 1): # Not folder
                all_files.append(data)
        
        self.properties_panel.update_filter_stats(all_files)
        
        self._apply_active_filters()
    
    def _on_item_rating_changed(self, file_data, rating):
        """文件项的评分改变"""
        logger.info(f"评分改变: {file_data.get('path')} -> {rating}")
        item_id = file_data.get('id')
        if item_id:
            if file_data.get('is_folder'):
                self.db.set_folder_rating(item_id, rating)
            else:
                self.db.set_file_rating(item_id, rating)

    def add_current_to_favorites(self):
        """将当前文件夹添加到收藏夹"""
        if self.current_folder_path and os.path.exists(self.current_folder_path):
            self.favorites_panel.add_favorite(self.current_folder_path)
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
                    self.properties_panel.set_file(file_data, thumb_path)
                    self.properties_panel.set_tag_input_enabled(True)

    def on_selection_changed_list(self, paths):
        """选择改变(来自文件列表)"""
        logger.debug(f"选择改变: {len(paths)} 个项目")
        if not paths:
            self.properties_panel.clear()
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
                    self.properties_panel.set_file(file_data, thumb_path)
                    self.properties_panel.set_tag_input_enabled(True)
        else:
            # 多个项目被选中
            self.properties_panel.clear(keep_tag_input=True)
            self.properties_panel.show_selection_summary(total_count, file_count)

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
            self.properties_panel.set_file(file_data, thumb_path)
            self.properties_panel.set_tag_input_enabled(True)
        else:
            self.properties_panel.clear(keep_tag_input=True)
            self.properties_panel.show_selection_summary(total, len(file_items))

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
        """搜索文件"""
        logger.info(f"搜索文件: {keyword}")
        if not keyword:
            return

        # 设置数据源为全局范围
        self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
        logger.info("数据源切换到全局范围（搜索）")
        
        # 注意：不更新地址栏，保持独立性
        self.statusBar().showMessage(f"正在搜索: {keyword}...")
        self.setWindowTitle(f"Python Bridge - 搜索: {keyword}")
        
        # 1. 按文件名搜索
        files = self.db.search_files_by_name(keyword)
        
        # 2. 按标签名搜索 (合并结果)
        tag_files = self.db.search_files_by_tag_name(keyword)
        
        # 合并去重
        seen_ids = {f['id'] for f in files}
        for f in tag_files:
            if f['id'] not in seen_ids:
                files.append(f)
                seen_ids.add(f['id'])
        
        self.file_list.load_files(files)
        self.setWindowTitle(f"搜索: {keyword} ({len(files)} 个结果)")
        
        # 更新筛选统计
        self.properties_panel.update_filter_stats(files)
        self._apply_active_filters()

    def assign_tag_to_selection(self):
        """为选中文件添加标签"""
        logger.info("为选中文件添加标签")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return

        tags = self.db.get_all_tags()
        if not tags:
            QMessageBox.warning(self, "提示", "请先创建标签")
            return
        
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "选择标签", "将选中文件添加到:", tag_names, 0, False)
        
        if ok and tag_name:
            tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.link_file_tag(file_data['id'], tag_id)
                self.db.link_file_tag(file_data['id'], tag_id)
            self.statusBar().showMessage(f"已添加标签 '{tag_name}' 到 {len(selected_items)} 个文件")

    def batch_add_tags(self):
        """批量添加标签"""
        logger.info("批量添加标签")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return
        
        tags = self.db.get_all_tags()
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "批量添加标签", "选择标签:", tag_names, 0, False)
        
        if ok and tag_name:
            tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.link_file_tag(file_data['id'], tag_id)
            self.refresh_current_view()

    def batch_remove_tags(self):
        """批量移除标签"""
        logger.info("批量移除标签")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return
        
        tags = self.db.get_all_tags()
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "批量移除标签", "选择标签:", tag_names, 0, False)
        
        if ok and tag_name:
            tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.remove_file_tag(file_data['id'], tag_id)
            self.refresh_current_view()

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

    def on_rating_changed(self, file_id, rating):
        """评级改变"""
        logger.info(f"评级改变: file_id={file_id}, rating={rating}")
        if file_id == -1:
            self.set_selected_rating(rating)
        else:
            self.db.set_file_rating(file_id, rating)
            self.refresh_current_view()

    def on_color_changed(self, file_id, color):
        """颜色改变"""
        logger.info(f"颜色改变: file_id={file_id}, color={color}")
        self.db.set_file_label_color(file_id, color)
        self.refresh_current_view()

    def on_pin_toggled(self, file_id, is_pinned):
        """置顶切换"""
        logger.info(f"置顶切换: file_id={file_id}, is_pinned={is_pinned}")
        if is_pinned:
            self.db.pin_file(file_id)
        else:
            self.db.unpin_file(file_id)
        self.refresh_current_view()

    def on_tag_added(self, file_id, tag_id):
        """标签添加"""
        logger.info(f"标签添加: file_id={file_id}, tag_id={tag_id}")
        self.db.link_file_tag(file_id, tag_id)
        self.refresh_current_view()

    def on_tag_removed(self, file_id, tag_id):
        """标签移除"""
        logger.info(f"标签移除: file_id={file_id}, tag_id={tag_id}")
        self.db.remove_file_tag(file_id, tag_id)
        self.refresh_current_view()
    
    def on_tag_created(self, tag_name):
        """标签创建"""
        logger.info(f"标签创建: {tag_name}")
        tag_id = self.db.create_tag(tag_name)
        if tag_id:
            self.properties_panel.refresh_tag_filters(self.current_tag_id)
            self.properties_panel.refresh_tag_suggestions()
            selected_items = self.file_list.selectedItems()
            if selected_items:
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    self.db.link_file_tag(file_data['id'], tag_id)
                self.refresh_current_view()
                self.on_selection_changed()

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

        file_items = [item for item in selected_items if not item.data(Qt.ItemDataRole.UserRole + 1)]
        tag_id = self.db.create_tag(tag_name)
        
        updated = 0
        for item in file_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            self.db.link_file_tag(file_data['id'], tag_id)
            updated += 1

        QMessageBox.information(self, "完成", f"已为 {updated} 个文件添加标签 '{tag_name}'")
        self.properties_panel.refresh_tag_suggestions()
        self.properties_panel.refresh_tag_filters(self.current_tag_id)
        self.on_selection_changed()

    def on_filter_changed(self, filters):
        """筛选器改变"""
        logger.debug(f"筛选器改变: {filters}")
        self.file_list.apply_filters(filters)

    def set_selected_color(self, color):
        """设置选中文件颜色"""
        logger.info(f"设置选中文件颜色: {color}")
        selected_items = self.file_list.selectedItems()
        if selected_items:
            for item in selected_items:
                if item.data(Qt.ItemDataRole.UserRole + 1): continue
                file_data = item.data(Qt.ItemDataRole.UserRole)
                # 使用数据源管理器
                self.data_source.set_color(file_data['path'], color)
            self.refresh_current_view()

    def set_selected_rating(self, rating):
        """设置选中文件评级"""
        logger.info(f"设置选中文件评级: {rating}")
        selected_items = self.file_list.selectedItems()
        if selected_items:
            for item in selected_items:
                if item.data(Qt.ItemDataRole.UserRole + 1): continue
                file_data = item.data(Qt.ItemDataRole.UserRole)
                # 使用数据源管理器
                self.data_source.set_rating(file_data['path'], rating)
            self.refresh_current_view()

    def toggle_selected_pin(self):
        """切换选中文件置顶状态"""
        logger.info("切换选中文件置顶状态")
        selected_items = self.file_list.selectedItems()
        if selected_items:
            for item in selected_items:
                if item.data(Qt.ItemDataRole.UserRole + 1): continue
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_pinned = file_data.get('is_pinned', 0)
                # 使用数据源管理器
                self.data_source.set_pin(file_data['path'], not is_pinned)
            self.refresh_current_view()

    def _apply_active_filters(self):
        """应用当前激活的筛选器"""
        filters = self.properties_panel.get_filters()
        self.file_list.apply_filters(filters)

    def switch_view_mode(self, mode):
        """切换视图模式"""
        logger.info(f"切换视图模式: {mode}")
        self.current_view_mode = mode
        self.file_list.set_view_mode(mode)

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

# =================== 2 ===================

# data_source_manager.py

"""
数据源管理器模块

提供统一接口管理文件元数据，支持双写模式（同时写入 JSON 和 SQLite）
"""

import os
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from logger import get_logger

logger = get_logger("DataSourceManager")


class BaseDataSource(ABC):
    """数据源基类，定义统一接口"""
    
    @abstractmethod
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """获取文件/文件夹的元数据"""
        pass
    
    @abstractmethod
    def set_pin(self, path: str, pinned: bool) -> bool:
        """设置置顶状态"""
        pass
    
    @abstractmethod
    def set_rating(self, path: str, rating: int) -> bool:
        """设置评级 (0-5)"""
        pass
    
    @abstractmethod
    def set_label(self, path: str, label: str) -> bool:
        """设置文本标签"""
        pass
    
    @abstractmethod
    def set_color(self, path: str, color: str) -> bool:
        """设置颜色标签"""
        pass
    
    @abstractmethod
    def get_all_items(self) -> List[Dict[str, Any]]:
        """获取当前范围内所有项目及其元数据"""
        pass


class JSONDataSource(BaseDataSource):
    """JSON 文件数据源（用于局部/单文件夹范围）"""
    
    METADATA_FILENAME = ".bridge_metadata.json"
    
    def __init__(self, folder_path: str):
        """
        初始化 JSON 数据源
        
        Args:
            folder_path: 文件夹路径
        """
        self.folder_path = folder_path
        self.metadata_file = os.path.join(folder_path, self.METADATA_FILENAME)
        self._cache = None
        logger.info(f"初始化 JSON 数据源: {folder_path}")
    
    def _load_metadata(self) -> Dict[str, Any]:
        """加载 JSON 元数据文件"""
        if self._cache is not None:
            return self._cache
        
        if not os.path.exists(self.metadata_file):
            # 创建默认结构
            self._cache = {
                "bridgedata": {
                    "version": "1",
                    "labels": {"version": "1", "items": []},
                    "ratings": {"version": "1", "items": []},
                    "pins": {"version": "1", "items": []},
                    "colors": {"version": "1", "items": []}
                }
            }
            return self._cache
        
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                self._cache = json.load(f)
                logger.debug(f"成功加载元数据: {self.metadata_file}")
                return self._cache
        except Exception as e:
            logger.error(f"加载元数据文件失败: {e}")
            # 返回默认结构
            self._cache = {
                "bridgedata": {
                    "version": "1",
                    "labels": {"version": "1", "items": []},
                    "ratings": {"version": "1", "items": []},
                    "pins": {"version": "1", "items": []},
                    "colors": {"version": "1", "items": []}
                }
            }
            return self._cache
    
    def _save_metadata(self, data: Dict[str, Any]) -> bool:
        """保存元数据到 JSON 文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.metadata_file), exist_ok=True)
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self._cache = data
            logger.debug(f"成功保存元数据: {self.metadata_file}")
            return True
        except Exception as e:
            logger.error(f"保存元数据文件失败: {e}")
            return False
    
    def _get_filename(self, path: str) -> str:
        """获取文件名（相对于当前文件夹）"""
        return os.path.basename(path)
    
    def _find_item(self, items: List[Dict], key: str) -> Optional[Dict]:
        """在列表中查找指定 key 的项"""
        for item in items:
            if item.get("key") == key:
                return item
        return None
    
    def _update_or_add_item(self, items: List[Dict], key: str, **kwargs) -> List[Dict]:
        """更新或添加项"""
        item = self._find_item(items, key)
        if item:
            item.update(kwargs)
        else:
            items.append({"key": key, **kwargs})
        return items
    
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """获取文件/文件夹的元数据"""
        data = self._load_metadata()
        bridge = data.get("bridgedata", {})
        filename = self._get_filename(path)
        
        metadata = {
            "path": path,
            "is_pinned": False,
            "rating": 0,
            "label": None,
            "label_color": None
        }
        
        # 读取置顶状态
        pins = bridge.get("pins", {}).get("items", [])
        pin_item = self._find_item(pins, filename)
        if pin_item:
            metadata["is_pinned"] = pin_item.get("pinned", False)
        
        # 读取评级
        ratings = bridge.get("ratings", {}).get("items", [])
        rating_item = self._find_item(ratings, filename)
        if rating_item:
            metadata["rating"] = int(rating_item.get("rating", 0))
        
        # 读取标签
        labels = bridge.get("labels", {}).get("items", [])
        label_item = self._find_item(labels, filename)
        if label_item:
            metadata["label"] = label_item.get("label")
        
        # 读取颜色
        colors = bridge.get("colors", {}).get("items", [])
        color_item = self._find_item(colors, filename)
        if color_item:
            metadata["label_color"] = color_item.get("color")
        
        return metadata
    
    def set_pin(self, path: str, pinned: bool) -> bool:
        """设置置顶状态"""
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        pins = bridge["pins"]["items"]
        self._update_or_add_item(pins, filename, pinned=pinned)
        bridge["pins"]["items"] = pins
        
        logger.info(f"设置置顶: {filename} = {pinned}")
        return self._save_metadata(data)
    
    def set_rating(self, path: str, rating: int) -> bool:
        """设置评级 (0-5)"""
        if not 0 <= rating <= 5:
            logger.warning(f"无效的评级: {rating}")
            return False
        
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        ratings = bridge["ratings"]["items"]
        self._update_or_add_item(ratings, filename, rating=str(rating))
        bridge["ratings"]["items"] = ratings
        
        logger.info(f"设置评级: {filename} = {rating}")
        return self._save_metadata(data)
    
    def set_label(self, path: str, label: str) -> bool:
        """设置文本标签"""
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        labels = bridge["labels"]["items"]
        if label:
            self._update_or_add_item(labels, filename, label=label)
        else:
            # 删除标签
            labels = [item for item in labels if item.get("key") != filename]
        bridge["labels"]["items"] = labels
        
        logger.info(f"设置标签: {filename} = {label}")
        return self._save_metadata(data)
    
    def set_color(self, path: str, color: str) -> bool:
        """设置颜色标签"""
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        colors = bridge["colors"]["items"]
        if color:
            self._update_or_add_item(colors, filename, color=color)
        else:
            # 删除颜色
            colors = [item for item in colors if item.get("key") != filename]
        bridge["colors"]["items"] = colors
        
        logger.info(f"设置颜色: {filename} = {color}")
        return self._save_metadata(data)
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """获取当前文件夹内所有项目及其元数据"""
        items = []
        if not os.path.exists(self.folder_path):
            return items
        
        try:
            for item_name in os.listdir(self.folder_path):
                # 跳过元数据文件本身
                if item_name == self.METADATA_FILENAME:
                    continue
                
                item_path = os.path.join(self.folder_path, item_name)
                metadata = self.get_item_metadata(item_path)
                items.append(metadata)
            
            return items
        except Exception as e:
            logger.error(f"获取文件夹项目失败: {e}")
            return []


class SQLiteDataSource(BaseDataSource):
    """SQLite 数据源（用于全局范围）"""
    
    def __init__(self, db_manager):
        """
        初始化 SQLite 数据源
        
        Args:
            db_manager: DatabaseManager 实例
        """
        self.db = db_manager
        logger.info("初始化 SQLite 数据源")
    
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """获取文件/文件夹的元数据"""
        metadata = {
            "path": path,
            "is_pinned": False,
            "rating": 0,
            "label": None,
            "label_color": None
        }
        
        is_dir = os.path.isdir(path)
        
        try:
            if is_dir:
                # 文件夹
                folder_data = self.db.get_folder_by_path(path)
                if folder_data:
                    metadata["is_pinned"] = folder_data.get("is_pinned", False)
                    metadata["rating"] = folder_data.get("rating", 0)
                    metadata["label_color"] = folder_data.get("label_color")
                    # 获取标签
                    tags = self.db.get_folder_tags(folder_data["id"])
                    if tags:
                        metadata["label"] = tags[0].get("name")
            else:
                # 文件
                file_id = self.db._get_file_id_by_path(path)
                if file_id:
                    file_data = self.db.get_file_by_id(file_id)
                    if file_data:
                        metadata["is_pinned"] = file_data.get("is_pinned", False)
                        metadata["rating"] = file_data.get("rating", 0)
                        metadata["label_color"] = file_data.get("label_color")
                        # 获取标签
                        tags = self.db.get_file_tags(file_id)
                        if tags:
                            metadata["label"] = tags[0].get("name")
        except Exception as e:
            logger.error(f"获取元数据失败: {e}")
        
        return metadata
    
    def set_pin(self, path: str, pinned: bool) -> bool:
        """设置置顶状态"""
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    if pinned:
                        self.db.pin_folder(folder_id)
                    else:
                        self.db.unpin_folder(folder_id)
                    logger.info(f"设置文件夹置顶: {path} = {pinned}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    if pinned:
                        self.db.pin_file(file_id)
                    else:
                        self.db.unpin_file(file_id)
                    logger.info(f"设置文件置顶: {path} = {pinned}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"设置置顶失败: {e}")
            return False
    
    def set_rating(self, path: str, rating: int) -> bool:
        """设置评级 (0-5)"""
        if not 0 <= rating <= 5:
            logger.warning(f"无效的评级: {rating}")
            return False
        
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    self.db.set_folder_rating(folder_id, rating)
                    logger.info(f"设置文件夹评级: {path} = {rating}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    self.db.set_file_rating(file_id, rating)
                    logger.info(f"设置文件评级: {path} = {rating}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"设置评级失败: {e}")
            return False
    
    def set_label(self, path: str, label: str) -> bool:
        """设置文本标签"""
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    if label:
                        # 先获取或创建标签
                        tag_id = self.db.create_tag(label)
                        if tag_id:
                            self.db.link_folder_tag(folder_id, tag_id)
                            logger.info(f"设置文件夹标签: {path} = {label}")
                            return True
                    else:
                        # 删除所有标签
                        tags = self.db.get_folder_tags(folder_id)
                        for tag in tags:
                            self.db.remove_folder_tag(folder_id, tag['id'])
                        logger.info(f"删除文件夹标签: {path}")
                        return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    if label:
                        # 先获取或创建标签
                        tag_id = self.db.create_tag(label)
                        if tag_id:
                            self.db.link_file_tag(file_id, tag_id)
                            logger.info(f"设置文件标签: {path} = {label}")
                            return True
                    else:
                        # 删除所有标签
                        tags = self.db.get_file_tags(file_id)
                        for tag in tags:
                            self.db.remove_file_tag(file_id, tag['id'])
                        logger.info(f"删除文件标签: {path}")
                        return True
            
            return False
        except Exception as e:
            logger.error(f"设置标签失败: {e}")
            return False
    
    def set_color(self, path: str, color: str) -> bool:
        """设置颜色标签"""
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    self.db.set_folder_label_color(folder_id, color)
                    logger.info(f"设置文件夹颜色: {path} = {color}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    self.db.set_file_label_color(file_id, color)
                    logger.info(f"设置文件颜色: {path} = {color}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"设置颜色失败: {e}")
            return False
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """获取所有文件及其元数据（全局范围）"""
        items = []
        try:
            files = self.db.get_all_files()
            for file_data in files:
                metadata = self.get_item_metadata(file_data["path"])
                items.append(metadata)
            return items
        except Exception as e:
            logger.error(f"获取所有文件失败: {e}")
            return []


class DataSourceManager:
    """
    数据源管理器
    
    实现双写策略：所有元数据操作同时写入 JSON 和 SQLite
    """
    
    SCOPE_GLOBAL = "global"
    SCOPE_LOCAL = "local"
    
    def __init__(self, db_manager):
        """
        初始化数据源管理器
        
        Args:
            db_manager: DatabaseManager 实例（用于全局范围）
        """
        self.db_manager = db_manager
        self.sqlite_source = SQLiteDataSource(db_manager)
        self.json_source = None
        self.current_scope = self.SCOPE_GLOBAL
        self.current_folder = None
        logger.info("数据源管理器初始化完成 - 双写模式已启用")
    
    def set_scope(self, scope: str, folder_path: str = None):
        """
        设置当前操作范围
        
        Args:
            scope: 范围类型 ('global' 或 'local')
            folder_path: 文件夹路径（local 范围时必需）
        """
        self.current_scope = scope
        
        if scope == self.SCOPE_LOCAL and folder_path:
            self.current_folder = folder_path
            self.json_source = JSONDataSource(folder_path)
            logger.info(f"切换到局部范围: {folder_path}")
        else:
            self.current_folder = None
            self.json_source = None
            logger.info("切换到全局范围")
    
    def _get_current_source(self) -> BaseDataSource:
        """获取当前活动的数据源"""
        if self.current_scope == self.SCOPE_LOCAL and self.json_source:
            return self.json_source
        return self.sqlite_source
    
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """获取文件/文件夹的元数据（优先从 JSON 读取）"""
        # 如果在局部范围，优先从 JSON 读取
        if self.current_scope == self.SCOPE_LOCAL and self.json_source:
            metadata = self.json_source.get_item_metadata(path)
            # 如果 JSON 中没有数据，尝试从数据库读取
            if metadata['rating'] == 0 and not metadata['is_pinned'] and not metadata['label'] and not metadata['label_color']:
                db_metadata = self.sqlite_source.get_item_metadata(path)
                if db_metadata['rating'] != 0 or db_metadata['is_pinned'] or db_metadata['label'] or db_metadata['label_color']:
                    return db_metadata
            return metadata
        else:
            return self.sqlite_source.get_item_metadata(path)
    
    def _update_json_metadata(self, path: str, callback) -> bool:
        """
        辅助方法：更新指定文件的 JSON 元数据（双写策略的核心）
        
        Args:
            path: 文件绝对路径
            callback: 接受 JSONDataSource 的回调函数
            
        Returns:
            bool: 是否成功写入 JSON
        """
        try:
            # 验证路径
            if not path or not isinstance(path, str):
                logger.warning(f"无效的路径参数: {path}")
                return False
                
            if not os.path.exists(path):
                logger.warning(f"文件不存在，跳过 JSON 写入: {path}")
                return False
            
            # 获取文件所在文件夹
            if os.path.isdir(path):
                folder_path = path
            else:
                folder_path = os.path.dirname(path)
            
            if not os.path.exists(folder_path):
                logger.warning(f"文件夹不存在，跳过 JSON 写入: {folder_path}")
                return False
            
            # 实例化临时的 JSONDataSource
            json_source = JSONDataSource(folder_path)
            result = callback(json_source)
            
            if result:
                logger.debug(f"✓ JSON 写入成功: {os.path.basename(path)}")
            else:
                logger.warning(f"✗ JSON 写入失败: {os.path.basename(path)}")
            
            return result
            
        except Exception as e:
            logger.error(f"更新 JSON 元数据异常: {e}", exc_info=True)
            return False

    def set_pin(self, path: str, pinned: bool) -> bool:
        """
        设置置顶状态（双写：同时写入 JSON 和数据库）
        
        Args:
            path: 文件/文件夹路径
            pinned: 是否置顶
            
        Returns:
            bool: 是否至少有一个数据源写入成功
        """
        logger.info(f"[双写] 设置置顶: {os.path.basename(path)} = {pinned}")
        
        # 1. 写入数据库 (总是执行)
        success_db = self.sqlite_source.set_pin(path, pinned)
        if success_db:
            logger.debug(f"  ✓ 数据库写入成功")
        else:
            logger.warning(f"  ✗ 数据库写入失败")
        
        # 2. 写入 JSON (总是尝试执行，根据文件路径动态定位)
        success_json = self._update_json_metadata(path, lambda js: js.set_pin(path, pinned))
        
        result = success_db or success_json
        logger.info(f"[双写结果] 置顶 - DB: {success_db}, JSON: {success_json}, 总体: {result}")
        return result
    
    def set_rating(self, path: str, rating: int) -> bool:
        """
        设置评级 (0-5)（双写：同时写入 JSON 和数据库）
        
        Args:
            path: 文件/文件夹路径
            rating: 评级 (0-5)
            
        Returns:
            bool: 是否至少有一个数据源写入成功
        """
        logger.info(f"[双写] 设置评级: {os.path.basename(path)} = {rating}")
        
        # 1. 写入数据库
        success_db = self.sqlite_source.set_rating(path, rating)
        if success_db:
            logger.debug(f"  ✓ 数据库写入成功")
        else:
            logger.warning(f"  ✗ 数据库写入失败")
        
        # 2. 写入 JSON
        success_json = self._update_json_metadata(path, lambda js: js.set_rating(path, rating))
        
        result = success_db or success_json
        logger.info(f"[双写结果] 评级 - DB: {success_db}, JSON: {success_json}, 总体: {result}")
        return result
    
    def set_label(self, path: str, label: str) -> bool:
        """
        设置文本标签（双写：同时写入 JSON 和数据库）
        
        Args:
            path: 文件/文件夹路径
            label: 标签文本（空字符串表示删除）
            
        Returns:
            bool: 是否至少有一个数据源写入成功
        """
        logger.info(f"[双写] 设置标签: {os.path.basename(path)} = '{label}'")
        
        # 1. 写入数据库
        success_db = self.sqlite_source.set_label(path, label)
        if success_db:
            logger.debug(f"  ✓ 数据库写入成功")
        else:
            logger.warning(f"  ✗ 数据库写入失败")
        
        # 2. 写入 JSON
        success_json = self._update_json_metadata(path, lambda js: js.set_label(path, label))
        
        result = success_db or success_json
        logger.info(f"[双写结果] 标签 - DB: {success_db}, JSON: {success_json}, 总体: {result}")
        return result
    
    def set_color(self, path: str, color: str) -> bool:
        """
        设置颜色标签（双写：同时写入 JSON 和数据库）
        
        Args:
            path: 文件/文件夹路径
            color: 颜色值（如 'red', 'blue' 等，空字符串或 None 表示删除）
            
        Returns:
            bool: 是否至少有一个数据源写入成功
        """
        logger.info(f"[双写] 设置颜色: {os.path.basename(path)} = '{color}'")
        
        # 1. 写入数据库
        success_db = self.sqlite_source.set_color(path, color)
        if success_db:
            logger.debug(f"  ✓ 数据库写入成功")
        else:
            logger.warning(f"  ✗ 数据库写入失败")
        
        # 2. 写入 JSON
        success_json = self._update_json_metadata(path, lambda js: js.set_color(path, color))
        
        result = success_db or success_json
        logger.info(f"[双写结果] 颜色 - DB: {success_db}, JSON: {success_json}, 总体: {result}")
        return result
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """获取当前范围内所有项目及其元数据"""
        return self._get_current_source().get_all_items()
    
    def get_current_scope(self) -> str:
        """获取当前范围"""
        return self.current_scope
    
    def is_local_scope(self) -> bool:
        """判断是否为局部范围"""
        return self.current_scope == self.SCOPE_LOCAL
        
        
# =================== 3 ===================

# enhanced_file_list.py

from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QWidget, QVBoxLayout, 
                             QLabel, QMenu, QApplication, QAbstractItemView, QFrame, QLineEdit,
                             QStyledItemDelegate)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QUrl, QMimeData
from PyQt6.QtGui import QIcon, QPixmap, QDrag, QAction, QColor, QPainter, QBrush, QPen
import os
import sys
import time
from datetime import datetime
from cache_manager import ThumbnailLoader
from rating_widget import RatingWidget

# 自定义Delegate,完全不绘制item背景
class NoFocusDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # 完全不绘制item,只显示widget
        pass

class FileItemWidget(QWidget):
    rating_changed = pyqtSignal(int)  # 评分改变信号
    rename_requested = pyqtSignal(str, str) # old_path, new_name
    
    def __init__(self, file_data, cache_manager, parent=None):
        super().__init__(parent)
        self.file_data = file_data
        self.cache = cache_manager
        self.is_selected = False
        self.is_folder = file_data.get('is_folder', False)
        
        self.setup_ui()
        
    def mousePressEvent(self, event):
        """忽略鼠标按下事件，让QListWidget处理选择"""
        # print(f"FileItemWidget mousePress: {self.file_data.get('filename')}")
        event.ignore()
        
    def mouseDoubleClickEvent(self, event):
        """忽略双击事件，让QListWidget处理打开"""
        # print(f"FileItemWidget mouseDoubleClick: {self.file_data.get('filename')}")
        event.ignore()
        
    def setup_ui(self):
        self.setFixedSize(160, 210)  # 固定大小，防止布局抖动和对齐问题
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 强制居中对齐
        
        # 缩略图容器
        self.thumb_container = QLabel()
        self.thumb_container.setObjectName("thumb_container") # 设置对象名以防止样式继承
        self.thumb_container.setFixedSize(140, 140)
        self.thumb_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_container.setStyleSheet("#thumb_container { background-color: transparent; border-radius: 5px; }")
        
        # 缩略图
        self.thumb_label = QLabel(self.thumb_container)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 默认图标
        if self.is_folder:
            self.thumb_label.setText("📁")
            self.thumb_label.setStyleSheet("font-size: 48px; color: #888;")
        else:
            self.thumb_label.setText("📄")
            self.thumb_label.setStyleSheet("font-size: 48px; color: #888;")
            
        layout.addWidget(self.thumb_container, 0, Qt.AlignmentFlag.AlignCenter)
        
        # === 悬浮/状态图标层 (Overlay) ===
        # 置顶图标
        self.pin_label = QLabel("📌", self.thumb_container)
        self.pin_label.setStyleSheet("font-size: 16px; background: transparent;")
        # Move to top-right corner (container is 140x140)
        self.pin_label.move(115, 0) 
        self.pin_label.hide()
        
        # 文件夹子项计数
        self.count_label = QLabel("", self.thumb_container)
        self.count_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 150);
            color: white;
            font-size: 10px;
            padding: 2px 5px;
            border-radius: 8px;
        """)
        self.count_label.hide()
        
        # 类型标识 (文件夹显示"FOLDER",文件显示扩展名)
        if self.is_folder:
            type_badge = QLabel("FOLDER", self.thumb_container)
            type_badge.setStyleSheet("""
                background-color: rgba(0, 0, 0, 150);
                color: white;
                font-size: 10px;
                padding: 2px 4px;
                border-bottom-right-radius: 4px;
            """)
            type_badge.move(0, 0)
            type_badge.show()
        else:
            # 显示文件扩展名
            extension = self.file_data.get('extension', '')
            if extension:
                ext_badge = QLabel(extension.upper().lstrip('.'), self.thumb_container)
                ext_badge.setStyleSheet("""
                    background-color: rgba(42, 130, 218, 180);
                    color: white;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 2px 4px;
                    border-bottom-right-radius: 4px;
                """)
                ext_badge.adjustSize()
                ext_badge.move(0, 0)
                ext_badge.show()
        
        # 星级评分 (始终显示,可点击)
        self.rating_widget = RatingWidget(self.file_data.get('rating', 0))
        self.rating_widget.rating_changed.connect(self._on_rating_clicked)
        layout.addWidget(self.rating_widget, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 文件名
        filename = self.file_data.get('filename', '')
        if not filename and 'path' in self.file_data:
            filename = os.path.basename(self.file_data['path'])
            
        self.name_label = QLabel(filename)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("color: #ccc; font-size: 12px;")
        self.name_label.setFixedWidth(150) # 固定宽度，略小于 widget 宽度
        self.name_label.setFixedHeight(35)
        layout.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 更新颜色和状态
        self.update_color_display()
        self.update_status_icons()

    def set_size(self, size):
        """动态调整大小"""
        self.setFixedSize(size, size + 50)
        thumb_size = size - 20
        self.thumb_container.setFixedSize(thumb_size, thumb_size)
        
        # Update pin position (Top-Right)
        self.pin_label.move(thumb_size - 25, 0)
        
        # Update badges
        # Count label (Bottom-Right)
        self.count_label.move(thumb_size - self.count_label.width() - 5, 
                              thumb_size - self.count_label.height() - 5)
                              
        # Name label width
        self.name_label.setFixedWidth(size - 10)

    def start_rename(self):
        """开始重命名"""
        self.name_label.hide()
        self.rename_edit = QLineEdit(self.name_label.text(), self)
        self.rename_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rename_edit.setStyleSheet("background-color: #333; color: white; border: 1px solid #0078d7;")
        self.rename_edit.setFixedWidth(self.width() - 10)
        self.rename_edit.move(5, self.height() - 40)
        self.rename_edit.show()
        self.rename_edit.setFocus()
        self.rename_edit.selectAll()
        self.rename_edit.returnPressed.connect(self.finish_rename)
        self.rename_edit.focusOutEvent = self._on_rename_focus_out

    def _on_rename_focus_out(self, event):
        """失去焦点时取消或提交 (这里选择提交)"""
        self.finish_rename()
        QLineEdit.focusOutEvent(self.rename_edit, event)

    def finish_rename(self):
        """完成重命名"""
        if hasattr(self, 'rename_edit') and self.rename_edit:
            new_name = self.rename_edit.text().strip()
            if new_name and new_name != self.name_label.text():
                self.rename_requested.emit(self.file_data['path'], new_name)
                self.name_label.setText(new_name)
            
            self.rename_edit.deleteLater()
            self.rename_edit = None
            self.name_label.show()

    def update_status_icons(self):
        """更新置顶、计数等状态图标"""
        # 置顶
        if self.file_data.get('is_pinned'):
            self.pin_label.show()
        else:
            self.pin_label.hide()
            
        # 文件夹计数
        if self.is_folder:
            file_count = self.file_data.get('children_file_count', 0)
            folder_count = self.file_data.get('children_folder_count', 0)
            total = file_count + folder_count
            if total > 0:
                self.count_label.setText(f"{total}")
                self.count_label.adjustSize()
                # 右下角定位
                self.count_label.move(self.thumb_container.width() - self.count_label.width() - 5, 
                                      self.thumb_container.height() - self.count_label.height() - 5)
                self.count_label.show()
            else:
                self.count_label.hide()
    
    def _on_rating_clicked(self, rating):
        """星级被点击"""
        self.file_data['rating'] = rating
        self.rating_changed.emit(rating)

    def update_rating_display(self):
        """更新评分显示"""
        rating = self.file_data.get('rating', 0)
        self.rating_widget.set_rating(rating)

    def update_color_display(self):
        """更新样式：边框、星级颜色、文件名背景"""
        color = self.file_data.get('label_color')
        
        # 1. 缩略图容器样式
        # 选中时显示蓝色边框，背景透明
        # 使用 ID 选择器 #thumb_container 防止样式继承到子控件
        if self.is_selected:
            self.thumb_container.setStyleSheet("#thumb_container { background-color: transparent; border: 2px solid #0078d7; border-radius: 5px; }")
        else:
            self.thumb_container.setStyleSheet("#thumb_container { background-color: transparent; border: none; border-radius: 5px; }")
        
        # 2. 星级评分颜色 (始终使用默认金色，不随标签变色)
        self.rating_widget.set_color(None)

        # 3. 文件名样式 (颜色标签应用在此)
        if color and color != 'none':
            # 有颜色标签: 背景色为标签色
            # 简单判断黑色文字的情况 (黄色)
            text_color = "black" if color in ['yellow', '#FFD700', '#FFFF00'] else "white"
            font_weight = "bold" if self.is_selected else "normal"
            
            self.name_label.setStyleSheet(f"""
                background-color: {color}; 
                color: {text_color}; 
                border-radius: 4px; 
                padding: 2px;
                font-size: 12px;
                font-weight: {font_weight};
            """)
        else:
            # 无颜色标签: 默认样式
            if self.is_selected:
                self.name_label.setStyleSheet("background-color: transparent; color: white; font-weight: bold; font-size: 12px;")
            else:
                self.name_label.setStyleSheet("background-color: transparent; color: #ccc; font-size: 12px;")

    def mousePressEvent(self, event):
        """忽略鼠标按下事件，让QListWidget处理选择"""
        # from logger import get_logger
        # logger = get_logger("FileItem")
        # logger.debug(f"FileItemWidget mousePress: {self.file_data.get('filename')}")
        event.ignore()
        
    def mouseDoubleClickEvent(self, event):
        """忽略双击事件，让QListWidget处理打开"""
        event.ignore()

    def set_thumbnail(self, pixmap):
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(130, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.thumb_label.setPixmap(scaled)
            self.thumb_label.setText("") # Clear text
            self.thumb_label.adjustSize()
            # Center in container
            x = (140 - scaled.width()) // 2
            y = (140 - scaled.height()) // 2
            self.thumb_label.move(x, y)

    def set_selected(self, selected):
        self.is_selected = selected
        self.update_color_display() # 统一更新样式

class EnhancedFileListWidget(QListWidget):
    item_clicked = pyqtSignal(str) # Path
    selection_changed = pyqtSignal(list) # List of paths
    go_up_requested = pyqtSignal() # Backspace pressed
    rename_file_requested = pyqtSignal(str, str) # old, new
    
    def __init__(self, cache_manager):
        super().__init__()
        self.cache = cache_manager
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        # 关键修复：设置固定的网格大小，防止布局死循环和闪退
        self.setGridSize(QSize(180, 230)) 
        self.setSpacing(10)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True) # 启用拖拽
        self.setIconSize(QSize(160, 210)) 
        
        # 优化样式，确保居中
        self.setStyleSheet("""
            QListWidget {
                background-color: #222;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background-color: transparent;
                border: none;
                border-radius: 5px;
                /* 确保项目在网格中居中 */
                padding: 5px; 
            }
            QListWidget::item:selected {
                background-color: transparent; /* 由 widget 处理选中样式 */
                border: none; /* 不显示边框 */
                outline: none;
            }
            QListWidget::item:focus {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
        """)
        
        # 使用自定义delegate禁用焦点矩形
        self.setItemDelegate(NoFocusDelegate(self))
        
        # 双击打开文件/文件夹
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        
        # 初始化缩略图加载器 (单例)
        self.loader_thread = ThumbnailLoader(self.cache)
        self.loader_thread.thumbnail_ready.connect(self.update_thumbnail)
        self.loader_thread.start()
        
        # 缩放相关
        self.current_icon_size = 160  # 当前图标大小
        self.current_grid_size = 180  # 当前网格大小
        
        # 预览窗口
        self.preview_dialog = None

    def mousePressEvent(self, event):
        """调试鼠标按下事件"""
        # item = self.itemAt(event.pos())
        # print(f"ListWidget mousePress at {event.pos()}, item: {item}")
        super().mousePressEvent(event)

    def closeEvent(self, event):
        """关闭时停止线程"""
        if hasattr(self, 'loader_thread'):
            self.loader_thread.stop()
        super().closeEvent(event)

    def wheelEvent(self, event):
        """处理鼠标滚轮事件 - Ctrl+滚轮缩放"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮：缩放
            delta = event.angleDelta().y()
            if delta > 0:
                self.current_icon_size = min(self.current_icon_size + 10, 300)
            else:
                self.current_icon_size = max(self.current_icon_size - 10, 80)
            
            # 更新网格大小
            self.setGridSize(QSize(self.current_icon_size + 20, self.current_icon_size + 70))
            self.setIconSize(QSize(self.current_icon_size, self.current_icon_size + 50))
            
            # 更新所有 ItemWidget 的大小
            for i in range(self.count()):
                item = self.item(i)
                item.setSizeHint(QSize(self.current_icon_size, self.current_icon_size + 50))
                widget = self.itemWidget(item)
                if widget:
                    widget.set_size(self.current_icon_size)
            
            event.accept()
        else:
            # 正常滚动
            super().wheelEvent(event)
    
    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key.Key_Space:
            # 空格键：切换预览
            if self.preview_dialog and self.preview_dialog.isVisible():
                self.preview_dialog.close()
            else:
                selected_items = self.selectedItems()
                if len(selected_items) == 1:
                    item = selected_items[0]
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                    if not is_folder:
                        path = file_data.get('path', '')
                        self._show_preview(path)
            event.accept()
            return

        elif event.key() == Qt.Key.Key_Backspace:
            # 退格键：返回上一级
            self.go_up_requested.emit()
            event.accept()
            return
            
        elif event.key() == Qt.Key.Key_F2 or event.key() == Qt.Key.Key_Return:
            # F2 或 回车：重命名
            selected_items = self.selectedItems()
            if len(selected_items) == 1:
                widget = self.itemWidget(selected_items[0])
                if widget:
                    widget.start_rename()
            event.accept()
            return
        
        super().keyPressEvent(event)
    
    def _show_preview(self, path):
        """显示文件预览"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QScrollArea
        
        if not os.path.exists(path):
            return
        
        ext = os.path.splitext(path)[1].lower()
        
        # 图片预览
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            self._show_image_preview(path)
        # 文本预览/编辑
        elif ext in ['.txt', '.md', '.log', '.json', '.xml', '.py', '.js', '.css', '.html']:
            self._show_text_preview(path)
    
    def _show_image_preview(self, path):
        """显示图片预览"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
        
        if self.preview_dialog:
            self.preview_dialog.close()
        
        self.preview_dialog = QDialog(self)
        self.preview_dialog.setWindowTitle(f"预览: {os.path.basename(path)}")
        self.preview_dialog.resize(800, 600)
        
        layout = QVBoxLayout(self.preview_dialog)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        label = QLabel()
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            label.setText("无法加载图片")
        
        scroll.setWidget(label)
        layout.addWidget(scroll)
        
        self.preview_dialog.show()
    
    def _show_text_preview(self, path):
        """显示文本预览/编辑"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QMessageBox
        
        if self.preview_dialog:
            self.preview_dialog.close()
        
        self.preview_dialog = QDialog(self)
        self.preview_dialog.setWindowTitle(f"编辑: {os.path.basename(path)}")
        self.preview_dialog.resize(800, 600)
        
        layout = QVBoxLayout(self.preview_dialog)
        
        text_edit = QTextEdit()
        text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            text_edit.setPlainText(content)
        except Exception as e:
            text_edit.setPlainText(f"无法读取文件: {e}")
            text_edit.setReadOnly(True)
        
        layout.addWidget(text_edit)
        
        # 按钮
        btn_layout = QHBoxLayout()
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(lambda: self._save_text(path, text_edit.toPlainText()))
        btn_layout.addWidget(save_btn)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.preview_dialog.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
        self.preview_dialog.show()
    
    def _save_text(self, path, content):
        """保存文本内容"""
        from PyQt6.QtWidgets import QMessageBox
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            QMessageBox.information(self, "成功", "文件已保存")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
    
    def set_view_mode(self, mode):
        """设置视图模式"""
        if mode == 'grid':
            self.setViewMode(QListWidget.ViewMode.IconMode)
            self.setGridSize(QSize(self.current_grid_size, self.current_grid_size + 50))
            self.setIconSize(QSize(self.current_icon_size, self.current_icon_size + 50))
        elif mode == 'list':
            self.setViewMode(QListWidget.ViewMode.ListMode)
            self.setGridSize(QSize(-1, -1))  # 列表模式下不使用网格


    def load_files(self, file_data_list):
        """加载文件列表"""
        self.clear()
        
        file_paths = []
        for file_data in file_data_list:
            self._add_item(file_data)
            file_paths.append(file_data['path'])
            
        # 添加任务到队列
        if file_paths:
            self.loader_thread.add_paths(file_paths)

    def append_files(self, files, folders=None):
        """追加文件到列表 (支持置顶排序: 置顶文件夹 -> 置顶文件 -> 普通文件夹 -> 普通文件)"""
        t0 = time.time()
        from logger import get_logger
        logger = get_logger("FileList")
        
        file_paths = []
        
        # 1. 分类
        pinned_folders = []
        unpinned_folders = []
        if folders:
            for f in folders:
                if f.get('is_pinned'):
                    pinned_folders.append(f)
                else:
                    unpinned_folders.append(f)
                    
        pinned_files = []
        unpinned_files = []
        for f in files:
            # 预处理扩展名
            if 'extension' not in f and 'path' in f:
                f['extension'] = os.path.splitext(f['path'])[1]
            
            if f.get('is_pinned'):
                pinned_files.append(f)
            else:
                unpinned_files.append(f)
        
        t1 = time.time()
        
        # 2. 按顺序添加 (禁用更新以提高性能)
        self.setUpdatesEnabled(False)
        try:
            # 置顶文件夹
            for f in pinned_folders:
                self._add_item(f, is_folder=True)
                
            # 置顶文件
            for f in pinned_files:
                file_paths.append(f['path'])
                self._add_item(f, is_folder=False)
                
            # 普通文件夹
            for f in unpinned_folders:
                self._add_item(f, is_folder=True)
                
            # 普通文件
            for f in unpinned_files:
                file_paths.append(f['path'])
                self._add_item(f, is_folder=False)
        finally:
            self.setUpdatesEnabled(True)
        
        t2 = time.time()
        # 添加任务到队列
        if file_paths:
            self.loader_thread.add_paths(file_paths)
            
        # 强制刷新布局，防止出现空白区域
        self.doItemsLayout()
        t3 = time.time()
        logger.debug(f"AppendFiles耗时: 分类={t1-t0:.4f}s, 添加={t2-t1:.4f}s, 布局={t3-t2:.4f}s, 总计={t3-t0:.4f}s")

    def _add_item(self, file_data, is_folder=False):
        item = QListWidgetItem(self)
        item.setSizeHint(QSize(160, 210))
        
        # 关键修复：正确设置item的flags，使其可选择、可拖拽
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled |
            Qt.ItemFlag.ItemIsSelectable |
            Qt.ItemFlag.ItemIsDragEnabled
        )
        
        # Store data in item
        item.setData(Qt.ItemDataRole.UserRole, file_data)
        item.setData(Qt.ItemDataRole.UserRole + 1, is_folder) # Store is_folder
        
        # Create widget
        # 如果是文件夹，file_data 可能结构不同，需要适配
        if is_folder:
            # 确保 file_data 有 path 字段
            if 'path' not in file_data: return
            file_data['is_folder'] = True
            
        widget = FileItemWidget(file_data, self.cache)
        widget.rename_requested.connect(lambda p, n: self.rename_file_requested.emit(p, n))
        self.setItemWidget(item, widget)
        
        # 设置 Item 文本以便支持键盘搜索 (Type-to-Select)
        filename = file_data.get('filename', '')
        if not filename and 'path' in file_data:
            filename = os.path.basename(file_data['path'])
        item.setText(filename)
        # 隐藏默认文本显示，因为我们有自定义 Widget
        item.setForeground(QColor(0,0,0,0))

    def mimeData(self, items):
        """创建拖拽数据，包含文件路径"""
        mime = QMimeData()
        urls = []
        for item in items:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and 'path' in data:
                urls.append(QUrl.fromLocalFile(data['path']))
        
        if urls:
            mime.setUrls(urls)
            
        return mime

    def update_thumbnail(self, path, thumb_path):
        """更新缩略图"""
        from logger import get_logger
        logger = get_logger("FileList")
        # logger.debug(f"尝试更新缩略图: {path} -> {thumb_path}")
        
        try:
            norm_path = os.path.normpath(path).lower()
            
            # Find item with this path
            for i in range(self.count()):
                item = self.item(i)
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and 'path' in data:
                    item_path = os.path.normpath(data['path']).lower()
                    if item_path == norm_path:
                        widget = self.itemWidget(item)
                        if widget:
                            pixmap = QPixmap(thumb_path)
                            if not pixmap.isNull():
                                widget.set_thumbnail(pixmap)
                            else:
                                logger.warning(f"无法加载缩略图: {thumb_path}")
                        else:
                            logger.warning(f"未找到widget: {path}")
                        break
            else:
                # logger.warning(f"未找到匹配的item: {path}")
                pass
        except Exception as e:
            logger.error(f"更新缩略图出错: {e}")

    def _on_item_double_clicked(self, item):
        """双击项目时触发"""
        data = item.data(Qt.ItemDataRole.UserRole)
        self.item_clicked.emit(data['path'])
        
        # Update selection state visually
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if w: w.set_selected(it.isSelected())

    def _on_selection_changed(self):
        paths = []
        for item in self.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            paths.append(data['path'])
            
        # Update visual state
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if w: w.set_selected(it.isSelected())
            
        self.selection_changed.emit(paths)

    # Drag and Drop support
    def startDrag(self, supportedActions):
        paths = []
        for item in self.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            paths.append(data['path'])
            
        if paths:
            drag = QDrag(self)
            mime_data = self.mimeData(self.selectedItems())
            
            # Set urls
            urls = [QUrl.fromLocalFile(p) for p in paths]
            mime_data.setUrls(urls)
            
            drag.setMimeData(mime_data)
            
            # Set pixmap
            if len(paths) == 1:
                widget = self.itemWidget(self.selectedItems()[0])
                if widget:
                    drag.setPixmap(widget.thumb_label.pixmap().scaled(64, 64))
            
            drag.exec(supportedActions)

    def apply_filters(self, filters):
        """应用筛选器 (支持分面筛选)"""
        for i in range(self.count()):
            item = self.item(i)
            file_data = item.data(Qt.ItemDataRole.UserRole)
            is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
            
            if is_folder:
                # 文件夹通常不被过滤，除非有特殊需求
                item.setHidden(False)
                continue
                
            visible = True
            
            # 1. 评级过滤
            if filters['rating']:
                rating = file_data.get('rating', 0)
                if rating not in filters['rating']: visible = False
            
            # 2. 颜色过滤
            if visible and filters['color']:
                color = file_data.get('label_color', 'none') or 'none'
                if color not in filters['color']: visible = False
            
            # 3. 扩展名过滤
            if visible and filters['extensions']:
                ext = file_data.get('extension', '').upper() or "无扩展名"
                if ext not in filters['extensions']:
                    visible = False
            
            # 4. 日期过滤 (按天)
            if visible and filters['date']:
                ts = file_data.get('created_time') or file_data.get('ctime')
                if ts:
                    date_str = datetime.fromtimestamp(ts).strftime('%Y/%m/%d')
                    if date_str not in filters['date']: visible = False
                else:
                    visible = False

            # 5. 标签过滤 (暂不支持，因为 item data 里没有 tags)
            # 如果需要支持，必须在加载文件时把 tags 放进 file_data
            
            item.setHidden(not visible)

    # ================= 右键菜单 =================
    
    def contextMenuEvent(self, event):
        """右键菜单 - 扁平化结构，常用功能在顶层"""
        import subprocess
        import shutil
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        
        item = self.itemAt(event.pos())
        
        # 空白处右键
        if not item:
            menu = QMenu(self)
            new_folder_action = QAction("📁 新建文件夹", self)
            new_folder_action.triggered.connect(self._create_new_folder)
            menu.addAction(new_folder_action)
            menu.exec(event.globalPos())
            return
        
        # 获取选中的项目
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        # 创建菜单
        menu = QMenu(self)
        
        # === 打开 ===
        if len(selected_items) == 1:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
            path = file_data.get('path', '')
            
            if is_folder:
                open_action = QAction("📂 打开", self)
            else:
                open_action = QAction("📄 打开", self)
            open_action.triggered.connect(lambda: self._open_file(path))
            menu.addAction(open_action)
            
            menu.addSeparator()
        
        # === 星级评分 (6个选项) ===
        rating_menu = menu.addMenu("⭐ 设置星级")
        for rating in range(6):
            stars = "★" * rating if rating > 0 else "无评分"
            rating_action = QAction(f"{stars}", self)
            rating_action.triggered.connect(lambda checked, r=rating: self._set_rating(r))
            rating_menu.addAction(rating_action)
        
        # === 颜色标签 ===
        color_menu = menu.addMenu("🎨 颜色标签")
        colors = [
            ("红色", "red", "#FF0000"),
            ("黄色", "yellow", "#FFD700"),
            ("绿色", "green", "#00FF00"),
            ("蓝色", "blue", "#0080FF"),
            ("无", None, "")
        ]
        for color_name, color_value, color_hex in colors:
            if color_hex:
                color_action = QAction(f"● {color_name}", self)
                pixmap = QPixmap(16, 16)
                pixmap.fill(QColor(color_hex))
                color_action.setIcon(QIcon(pixmap))
            else:
                color_action = QAction(f"○ {color_name}", self)
            color_action.triggered.connect(lambda checked, c=color_value: self._set_color(c))
            color_menu.addAction(color_action)
        
        # === 标签操作 ===
        tag_menu = menu.addMenu("🏷️ 标签")
        add_tag_action = QAction("添加标签...", self)
        add_tag_action.triggered.connect(self._add_tag)
        tag_menu.addAction(add_tag_action)
        
        remove_tag_action = QAction("移除标签...", self)
        remove_tag_action.triggered.connect(self._remove_tag)
        tag_menu.addAction(remove_tag_action)
        
        # === 置顶 ===
        pin_action = QAction("📌 置顶/取消置顶", self)
        pin_action.triggered.connect(self._toggle_pin)
        menu.addAction(pin_action)
        
        menu.addSeparator()
        
        # === 文件操作 ===
        copy_action = QAction("📋 复制", self)
        copy_action.triggered.connect(self._copy_files)
        menu.addAction(copy_action)
        
        # 移动到 - 带常用文件夹子菜单
        move_menu = menu.addMenu("✂️ 移动到")
        self._add_common_folders_to_menu(move_menu, self._move_to_folder)
        move_menu.addSeparator()
        move_other_action = QAction("其他位置...", self)
        move_other_action.triggered.connect(self._move_to)
        move_menu.addAction(move_other_action)
        
        # 复制到 - 带常用文件夹子菜单
        copy_menu = menu.addMenu("📑 复制到")
        self._add_common_folders_to_menu(copy_menu, self._copy_to_folder)
        copy_menu.addSeparator()
        copy_other_action = QAction("其他位置...", self)
        copy_other_action.triggered.connect(self._copy_to)
        copy_menu.addAction(copy_other_action)
        
        menu.addSeparator()
        
        # === 重命名 ===
        if len(selected_items) == 1:
            rename_action = QAction("✏️ 重命名", self)
            rename_action.triggered.connect(self._rename_file)
            menu.addAction(rename_action)
        else:
            batch_rename_action = QAction("✏️ 批量重命名...", self)
            batch_rename_action.triggered.connect(self._batch_rename)
            menu.addAction(batch_rename_action)
        
        menu.addSeparator()
        
        # === 资源管理器 ===
        if len(selected_items) == 1:
            show_action = QAction("📁 在资源管理器中显示", self)
            show_action.triggered.connect(lambda: self._show_in_explorer(path))
            menu.addAction(show_action)
            
            copy_path_action = QAction("📋 复制路径", self)
            copy_path_action.triggered.connect(lambda: self._copy_path(path))
            menu.addAction(copy_path_action)
            
            menu.addSeparator()
        
        # === 收藏夹 ===
        folders_selected = sum(1 for item in selected_items if item.data(Qt.ItemDataRole.UserRole + 1))
        if folders_selected > 0:
            add_fav_action = QAction("⭐ 添加到收藏夹", self)
            add_fav_action.triggered.connect(self._add_selected_to_favorites)
            menu.addAction(add_fav_action)
            menu.addSeparator()
        
        # === 删除 ===
        delete_action = QAction("🗑️ 删除数据库记录", self)
        delete_action.triggered.connect(self._delete_selected_records)
        menu.addAction(delete_action)
        
        # 显示菜单
        menu.exec(event.globalPos())
    
    def _add_common_folders_to_menu(self, menu, callback):
        """添加常用文件夹到菜单"""
        # 获取常用文件夹
        common_folders = [
            ("桌面", os.path.join(os.path.expanduser("~"), "Desktop")),
            ("文档", os.path.join(os.path.expanduser("~"), "Documents")),
            ("下载", os.path.join(os.path.expanduser("~"), "Downloads")),
            ("图片", os.path.join(os.path.expanduser("~"), "Pictures")),
            ("音乐", os.path.join(os.path.expanduser("~"), "Music")),
            ("视频", os.path.join(os.path.expanduser("~"), "Videos")),
        ]
        
        # 添加收藏夹中的文件夹
        main_window = self.window()
        if hasattr(main_window, 'db'):
            favorites = main_window.db.get_all_favorites()
            if favorites:
                for fav in favorites[:5]:  # 最多显示5个收藏
                    if os.path.exists(fav['path']):
                        common_folders.append((fav['name'], fav['path']))
        
        # 添加到菜单
        for name, path in common_folders:
            if os.path.exists(path):
                action = QAction(f"📁 {name}", self)
                action.triggered.connect(lambda checked, p=path: callback(p))
                menu.addAction(action)
    
    def _move_to_folder(self, dest_dir):
        """移动文件到指定文件夹"""
        from PyQt6.QtWidgets import QMessageBox
        import shutil
        
        selected_items = self.selectedItems()
        moved_count = 0
        
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            src_path = file_data.get('path', '')
            if src_path and os.path.exists(src_path):
                dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                try:
                    shutil.move(src_path, dest_path)
                    moved_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"移动失败: {src_path}\n{e}")
        
        if moved_count > 0:
            QMessageBox.information(self, "完成", f"已移动 {moved_count} 个项目到 {os.path.basename(dest_dir)}")
            main_window = self.window()
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _copy_to_folder(self, dest_dir):
        """复制文件到指定文件夹"""
        from PyQt6.QtWidgets import QMessageBox
        import shutil
        
        selected_items = self.selectedItems()
        copied_count = 0
        
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            src_path = file_data.get('path', '')
            if src_path and os.path.exists(src_path):
                dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                try:
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dest_path)
                    else:
                        shutil.copy2(src_path, dest_path)
                    copied_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"复制失败: {src_path}\n{e}")
        
        if copied_count > 0:
            QMessageBox.information(self, "完成", f"已复制 {copied_count} 个项目到 {os.path.basename(dest_dir)}")
    
    # === 菜单处理函数 ===
    
    def _create_new_folder(self):
        """在当前路径创建新文件夹"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        main_window = self.window()
        if hasattr(main_window, 'current_folder_path') and main_window.current_folder_path:
            folder_name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称:")
            if ok and folder_name:
                new_path = os.path.join(main_window.current_folder_path, folder_name)
                try:
                    os.makedirs(new_path, exist_ok=True)
                    QMessageBox.information(self, "成功", f"已创建文件夹: {folder_name}")
                    if hasattr(main_window, 'refresh_current_view'):
                        main_window.refresh_current_view()
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"创建文件夹失败: {e}")
    
    def _set_rating(self, rating):
        """设置评分"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                file_id = file_data.get('id')
                if file_id:
                    if is_folder:
                        main_window.db.set_folder_rating(file_id, rating)
                    else:
                        main_window.db.set_file_rating(file_id, rating)
            
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _set_color(self, color):
        """设置颜色标签"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                file_id = file_data.get('id')
                if file_id:
                    if is_folder:
                        main_window.db.set_folder_label_color(file_id, color)
                    else:
                        main_window.db.set_file_label_color(file_id, color)
            
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _add_tag(self):
        """添加标签"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            # 获取所有标签
            tags = main_window.db.get_all_tags()
            if not tags:
                QMessageBox.warning(self, "提示", "请先创建标签")
                return
            
            tag_names = [t['name'] for t in tags]
            tag_name, ok = QInputDialog.getItem(self, "选择标签", "添加标签:", tag_names, 0, False)
            
            if ok and tag_name:
                tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                    file_id = file_data.get('id')
                    if file_id:
                        if is_folder:
                            main_window.db.link_folder_tag(file_id, tag_id)
                        else:
                            main_window.db.link_file_tag(file_id, tag_id)
                
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
                QMessageBox.information(self, "完成", f"已添加标签 '{tag_name}'")
    
    def _remove_tag(self):
        """移除标签"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            tags = main_window.db.get_all_tags()
            if not tags:
                return
            
            tag_names = [t['name'] for t in tags]
            tag_name, ok = QInputDialog.getItem(self, "选择标签", "移除标签:", tag_names, 0, False)
            
            if ok and tag_name:
                tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                    file_id = file_data.get('id')
                    if file_id:
                        if is_folder:
                            main_window.db.remove_folder_tag(file_id, tag_id)
                        else:
                            main_window.db.remove_file_tag(file_id, tag_id)
                
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
                QMessageBox.information(self, "完成", f"已移除标签 '{tag_name}'")
    
    def _toggle_pin(self):
        """切换置顶状态"""
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                file_id = file_data.get('id')
                is_pinned = file_data.get('is_pinned', 0)
                
                if file_id:
                    if is_folder:
                        if is_pinned:
                            main_window.db.unpin_folder(file_id)
                        else:
                            main_window.db.pin_folder(file_id)
                    else:
                        if is_pinned:
                            main_window.db.unpin_file(file_id)
                        else:
                            main_window.db.pin_file(file_id)
            
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _copy_files(self):
        """复制文件到剪贴板"""
        from PyQt6.QtCore import QMimeData, QUrl
        selected_items = self.selectedItems()
        
        urls = []
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            path = file_data.get('path', '')
            if path:
                urls.append(QUrl.fromLocalFile(path))
        
        if urls:
            mime_data = QMimeData()
            mime_data.setUrls(urls)
            clipboard = QApplication.clipboard()
            clipboard.setMimeData(mime_data)
    
    def _move_to(self):
        """移动文件到指定位置"""
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        import shutil
        
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        dest_dir = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if dest_dir:
            moved_count = 0
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                src_path = file_data.get('path', '')
                if src_path and os.path.exists(src_path):
                    dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                    try:
                        shutil.move(src_path, dest_path)
                        moved_count += 1
                    except Exception as e:
                        QMessageBox.warning(self, "错误", f"移动失败: {src_path}\n{e}")
            
            if moved_count > 0:
                QMessageBox.information(self, "完成", f"已移动 {moved_count} 个项目")
                main_window = self.window()
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
    
    def _copy_to(self):
        """复制文件到指定位置"""
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        import shutil
        
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        dest_dir = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if dest_dir:
            copied_count = 0
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                src_path = file_data.get('path', '')
                if src_path and os.path.exists(src_path):
                    dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                    try:
                        if os.path.isdir(src_path):
                            shutil.copytree(src_path, dest_path)
                        else:
                            shutil.copy2(src_path, dest_path)
                        copied_count += 1
                    except Exception as e:
                        QMessageBox.warning(self, "错误", f"复制失败: {src_path}\n{e}")
            
            if copied_count > 0:
                QMessageBox.information(self, "完成", f"已复制 {copied_count} 个项目")
    
    def _rename_file(self):
        """重命名文件"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        
        selected_items = self.selectedItems()
        if len(selected_items) != 1:
            return
        
        item = selected_items[0]
        file_data = item.data(Qt.ItemDataRole.UserRole)
        old_path = file_data.get('path', '')
        old_name = os.path.basename(old_path)
        
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            try:
                os.rename(old_path, new_path)
                QMessageBox.information(self, "成功", "重命名成功")
                main_window = self.window()
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
            except Exception as e:
                QMessageBox.warning(self, "错误", f"重命名失败: {e}")
    
    def _batch_rename(self):
        """批量重命名"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        prefix, ok = QInputDialog.getText(self, "批量重命名", "输入前缀（将添加编号）:")
        if ok and prefix:
            renamed_count = 0
            for i, item in enumerate(selected_items, 1):
                file_data = item.data(Qt.ItemDataRole.UserRole)
                old_path = file_data.get('path', '')
                ext = os.path.splitext(old_path)[1]
                new_name = f"{prefix}_{i:03d}{ext}"
                new_path = os.path.join(os.path.dirname(old_path), new_name)
                
                try:
                    os.rename(old_path, new_path)
                    renamed_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"重命名失败: {old_path}\n{e}")
            
            if renamed_count > 0:
                QMessageBox.information(self, "完成", f"已重命名 {renamed_count} 个项目")
                main_window = self.window()
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
    
    def _open_file(self, path):
        """打开文件或文件夹"""
        import subprocess
        if os.path.exists(path):
            if os.name == 'nt':  # Windows
                os.startfile(path)
            elif os.name == 'posix':  # macOS/Linux
                subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', path])
    
    def _show_in_explorer(self, path):
        """在资源管理器中显示"""
        import subprocess
        if os.path.exists(path):
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', '/select,', path])
            elif sys.platform == 'darwin':  # macOS
                subprocess.run(['open', '-R', path])
            else:  # Linux
                subprocess.run(['xdg-open', os.path.dirname(path)])
    
    def _copy_path(self, path):
        """复制路径到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
    
    def _add_selected_to_favorites(self):
        """添加选中的文件夹到收藏夹"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        folders = [item.data(Qt.ItemDataRole.UserRole)['path'] 
                  for item in selected_items 
                  if item.data(Qt.ItemDataRole.UserRole + 1)]
        
        if folders:
            main_window = self.window()
            if hasattr(main_window, 'favorites_panel'):
                for folder_path in folders:
                    main_window.favorites_panel.add_favorite(folder_path)
                QMessageBox.information(self, "完成", f"已添加 {len(folders)} 个文件夹到收藏夹")
            else:
                QMessageBox.warning(self, "错误", "无法访问收藏夹面板")
    
    def _delete_selected_records(self):
        """删除选中的记录"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要从数据库中删除 {len(selected_items)} 个文件/文件夹的记录吗？\n\n注意：这不会删除实际文件，只删除数据库记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            main_window = self.window()
            if hasattr(main_window, 'db'):
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    file_id = file_data.get('id')
                    if file_id:
                        main_window.db.delete_file(file_id)
                
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
                QMessageBox.information(self, "完成", f"已删除 {len(selected_items)} 条记录")
                
                
# =================== 4 ===================    
            
# db_manager.py
import sqlite3
import os
import time
from datetime import datetime
from logger import get_logger

logger = get_logger("DatabaseManager")

DB_PATH = "file_manager.db"

class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = db_path if db_path else DB_PATH
        self.conn = None
    
    def connect(self):
        """连接数据库"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        except Exception as e:
            print(f"Error connecting to database: {e}")
            raise

    def get_cursor(self):
        """获取游标"""
        if not self.conn:
            self.connect()
        return self.conn.cursor()

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def init_db(self):
        """初始化数据库，创建所有必要的表"""
        try:
            self.connect()
            cursor = self.conn.cursor()
    
            # 创建 files 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                filename TEXT,
                extension TEXT,
                size INTEGER,
                modified_time REAL,
                created_time REAL,
                access_count INTEGER DEFAULT 0,
                last_access_time REAL,
                rating INTEGER DEFAULT 0 CHECK(rating >= 0 AND rating <= 5),
                label_color TEXT,
                is_pinned INTEGER DEFAULT 0,
                pin_order INTEGER DEFAULT 0
            )
            ''')
    
            # 创建 folders 表 (使用 parent_id)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                parent_id INTEGER,
                name TEXT,
                last_scanned REAL,
                created_time REAL,
                modified_time REAL,
                children_file_count INTEGER DEFAULT 0,
                children_folder_count INTEGER DEFAULT 0,
                rating INTEGER DEFAULT 0 CHECK(rating >= 0 AND rating <= 5),
                label_color TEXT,
                is_pinned INTEGER DEFAULT 0,
                pin_order INTEGER DEFAULT 0,
                FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE SET NULL
            )
            ''')
    
            # 创建 tags 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT
            )
            ''')
    
            # 创建 file_tags 关联表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (file_id, tag_id),
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
            ''')
    
            # 创建 folder_tags 关联表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS folder_tags (
                folder_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (folder_id, tag_id),
                FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
            ''')
    
            # 创建 favorites 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                path TEXT UNIQUE NOT NULL,
                sort_order INTEGER,
                created_at REAL
            )
            ''')
    
            # 创建 collections 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                is_smart INTEGER DEFAULT 0,
                smart_criteria TEXT,
                created_at REAL,
                updated_at REAL
            )
            ''')
    
            # 创建 file_collections 关联表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_collections (
                file_id INTEGER,
                collection_id INTEGER,
                added_at REAL,
                PRIMARY KEY (file_id, collection_id),
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
            ''')
    
            # 为 path 列创建索引以提高查询速度
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_path ON files (path)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_path ON folders (path)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_parent_id ON folders (parent_id)')
    
            self.conn.commit()
            
            # 检查并迁移架构
            self._check_and_migrate_schema()
            
            logger.info("数据库初始化成功，所有表已创建。")
    
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}", exc_info=True)
        finally:
            self.close()

    def _check_and_migrate_schema(self):
        """检查并迁移数据库架构，添加缺失的列"""
        try:
            cursor = self.conn.cursor()
            
            # 检查 files 表
            cursor.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # 需要检查的列及其类型
            required_columns = {
                'created_time': 'REAL',
                'modified_time': 'REAL',
                'extension': 'TEXT',
                'last_access_time': 'REAL',
                'rating': 'INTEGER DEFAULT 0',
                'label_color': 'TEXT',
                'is_pinned': 'INTEGER DEFAULT 0',
                'pin_order': 'INTEGER DEFAULT 0'
            }
            
            for col, col_type in required_columns.items():
                if col not in columns:
                    logger.info(f"Adding missing column '{col}' to files table...")
                    try:
                        cursor.execute(f"ALTER TABLE files ADD COLUMN {col} {col_type}")
                    except Exception as e:
                        logger.error(f"Failed to add column {col}: {e}")

            # 检查 folders 表
            cursor.execute("PRAGMA table_info(folders)")
            columns = {row[1] for row in cursor.fetchall()}
            
            required_columns = {
                'created_time': 'REAL',
                'modified_time': 'REAL',
                'last_scanned': 'REAL',
                'children_file_count': 'INTEGER DEFAULT 0',
                'children_folder_count': 'INTEGER DEFAULT 0',
                'rating': 'INTEGER DEFAULT 0',
                'label_color': 'TEXT',
                'is_pinned': 'INTEGER DEFAULT 0',
                'pin_order': 'INTEGER DEFAULT 0'
            }
            
            for col, col_type in required_columns.items():
                if col not in columns:
                    logger.info(f"Adding missing column '{col}' to folders table...")
                    try:
                        cursor.execute(f"ALTER TABLE folders ADD COLUMN {col} {col_type}")
                    except Exception as e:
                        logger.error(f"Failed to add column {col}: {e}")
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Schema migration failed: {e}")

    # ==================== 文件操作 ====================
    
    def upsert_file(self, path):
        """插入或更新文件信息（增强版，包含所有新字段）"""
        if not os.path.exists(path):
            return None
        
        stat = os.stat(path)
        filename = os.path.basename(path)
        extension = os.path.splitext(filename)[1].lower().lstrip('.')
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO files (
                    path, filename, extension, size,
                    created_time, modified_time, access_count
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size,
                    modified_time=excluded.modified_time,
                    extension=excluded.extension
            ''', (path, filename, extension, stat.st_size,
                  stat.st_ctime, stat.st_mtime))
            
            file_id = cursor.lastrowid if cursor.lastrowid else self._get_file_id_by_path(path)
            self.conn.commit()
            return file_id
        except Exception as e:
            logger.error(f"Error upserting file: {e}", exc_info=True)
            return None
        finally:
            self.close()
    
    def _get_file_id_by_path(self, path):
        """根据路径获取文件ID（内部方法）"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM files WHERE path = ?', (path,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def increment_file_access_count(self, file_id):
        """增加文件访问计数"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE files 
                SET access_count = access_count + 1 
                WHERE id = ?
            ''', (file_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error incrementing access count: {e}")
        finally:
            self.close()
    
    def get_files_by_extension(self, extension):
        """按扩展名查询文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE extension = ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (extension.lower().lstrip('.'),))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by extension: {e}")
            return []
        finally:
            self.close()
    
    def get_most_accessed_files(self, limit=20):
        """获取访问次数最多的文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE access_count > 0
                ORDER BY access_count DESC, filename
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting most accessed files: {e}")
            return []
        finally:
            self.close()
    
    def get_all_files(self):
        """获取所有文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM files ORDER BY is_pinned DESC, pin_order, filename')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all files: {e}")
            return []
        finally:
            self.close()
    
    def get_file_by_id(self, file_id):
        """根据ID获取文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting file by id: {e}")
            return None
        finally:
            self.close()

    # ==================== 标签操作 ====================
    
    def create_tag(self, name, color="#FFFFFF"):
        """创建新标签"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)
            ''', (name, color))
            
            if cursor.lastrowid:
                tag_id = cursor.lastrowid
            else:
                cursor.execute('SELECT id FROM tags WHERE name = ?', (name,))
                tag_id = cursor.fetchone()[0]
            
            self.conn.commit()
            return tag_id
        except Exception as e:
            logger.error(f"Error creating tag: {e}")
            return None
        finally:
            self.close()

    def link_file_tag(self, file_id, tag_id):
        """将文件关联到标签"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO file_tags (file_id, tag_id) 
                VALUES (?, ?)
            ''', (file_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error linking file tag: {e}")
        finally:
            self.close()
    
    def link_folder_tag(self, folder_id, tag_id):
        """将文件夹关联到标签（新增）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO folder_tags (folder_id, tag_id) 
                VALUES (?, ?)
            ''', (folder_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error linking folder tag: {e}")
        finally:
            self.close()

    def get_files_by_tag(self, tag_id):
        """获取指定标签下的所有文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM files f
                JOIN file_tags ft ON f.id = ft.file_id
                WHERE ft.tag_id = ?
                ORDER BY f.is_pinned DESC, f.pin_order, f.filename
            ''', (tag_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by tag: {e}")
            return []
        finally:
            self.close()
    
    def get_folders_by_tag(self, tag_id):
        """获取指定标签下的所有文件夹（新增）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM folders f
                JOIN folder_tags ft ON f.id = ft.folder_id
                WHERE ft.tag_id = ?
                ORDER BY f.is_pinned DESC, f.pin_order, f.name
            ''', (tag_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folders by tag: {e}")
            return []
        finally:
            self.close()

    def get_all_tags(self):
        """获取所有标签"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM tags ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all tags: {e}")
            return []
        finally:
            self.close()

    def get_file_tags(self, file_id):
        """获取某个文件已关联的标签"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT t.*
                FROM tags t
                JOIN file_tags ft ON t.id = ft.tag_id
                WHERE ft.file_id = ?
                ORDER BY t.name
            ''', (file_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting file tags: {e}")
            return []
        finally:
            self.close()
    
    def get_folder_tags(self, folder_id):
        """获取某个文件夹已关联的标签（新增）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT t.*
                FROM tags t
                JOIN folder_tags ft ON t.id = ft.tag_id
                WHERE ft.folder_id = ?
                ORDER BY t.name
            ''', (folder_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folder tags: {e}")
            return []
        finally:
            self.close()

    # ==================== 评级操作 ====================
    
    def set_file_rating(self, file_id, rating):
        """设置文件评级 (0-5)"""
        if not 0 <= rating <= 5:
            raise ValueError("Rating must be between 0 and 5")
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE files SET rating = ? WHERE id = ?', (rating, file_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting file rating: {e}")
        finally:
            self.close()
    
    def set_folder_rating(self, folder_id, rating):
        """设置文件夹评级 (0-5)（新增）"""
        if not 0 <= rating <= 5:
            raise ValueError("Rating must be between 0 and 5")
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE folders SET rating = ? WHERE id = ?', (rating, folder_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting folder rating: {e}")
        finally:
            self.close()
    
    def get_files_by_rating(self, min_rating=0, max_rating=5):
        """按评级范围查询文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE rating BETWEEN ? AND ?
                ORDER BY is_pinned DESC, pin_order, rating DESC, filename
            ''', (min_rating, max_rating))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by rating: {e}")
            return []
        finally:
            self.close()
    
    def get_folders_by_rating(self, min_rating=0, max_rating=5):
        """按评级范围查询文件夹（新增）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM folders 
                WHERE rating BETWEEN ? AND ?
                ORDER BY is_pinned DESC, pin_order, rating DESC, name
            ''', (min_rating, max_rating))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folders by rating: {e}")
            return []
        finally:
            self.close()

    # ==================== 彩色标记操作 ====================
    
    def set_file_label_color(self, file_id, color):
        """设置文件颜色标签 (red/yellow/green/blue/purple/None)"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE files SET label_color = ? WHERE id = ?', (color, file_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting file label color: {e}")
        finally:
            self.close()
    
    def set_folder_label_color(self, folder_id, color):
        """设置文件夹颜色标签"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE folders SET label_color = ? WHERE id = ?', (color, folder_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting folder label color: {e}")
        finally:
            self.close()
    
    def get_files_by_label_color(self, color):
        """按颜色标签查询文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE label_color = ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (color,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by label color: {e}")
            return []
        finally:
            self.close()
    
    def get_folders_by_label_color(self, color):
        """按颜色标签查询文件夹（新增）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM folders 
                WHERE label_color = ?
                ORDER BY is_pinned DESC, pin_order, name
            ''', (color,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folders by label color: {e}")
            return []
        finally:
            self.close()

    # ==================== 置顶操作 ====================
    
    def pin_file(self, file_id, pin_order=None):
        """置顶文件"""
        if pin_order is None:
            try:
                self.connect()
                cursor = self.conn.cursor()
                cursor.execute('SELECT MAX(pin_order) FROM files WHERE is_pinned = 1')
                max_order = cursor.fetchone()[0]
                pin_order = (max_order or 0) + 1
            finally:
                self.close()
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE files SET is_pinned = 1, pin_order = ? WHERE id = ?
            ''', (pin_order, file_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error pinning file: {e}")
        finally:
            self.close()
    
    def unpin_file(self, file_id):
        """取消置顶文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE files SET is_pinned = 0, pin_order = 0 WHERE id = ?
            ''', (file_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error unpinning file: {e}")
        finally:
            self.close()
    
    def pin_folder(self, folder_id, pin_order=None):
        """置顶文件夹"""
        if pin_order is None:
            try:
                self.connect()
                cursor = self.conn.cursor()
                cursor.execute('SELECT MAX(pin_order) FROM folders WHERE is_pinned = 1')
                max_order = cursor.fetchone()[0]
                pin_order = (max_order or 0) + 1
            finally:
                self.close()
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE folders SET is_pinned = 1, pin_order = ? WHERE id = ?
            ''', (pin_order, folder_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error pinning folder: {e}")
        finally:
            self.close()
    
    def unpin_folder(self, folder_id):
        """取消置顶文件夹（新增）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE folders SET is_pinned = 0, pin_order = 0 WHERE id = ?
            ''', (folder_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error unpinning folder: {e}")
        finally:
            self.close()
    
    def reorder_pinned_items(self, item_type, item_ids):
        """重新排序置顶项 (item_type: 'file' or 'folder')"""
        table = 'files' if item_type == 'file' else 'folders'
        try:
            self.connect()
            cursor = self.conn.cursor()
            for order, item_id in enumerate(item_ids, 1):
                cursor.execute(f'UPDATE {table} SET pin_order = ? WHERE id = ?', (order, item_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error reordering pinned items: {e}")
        finally:
            self.close()

    # ==================== 收藏夹操作 ====================
    
    def add_favorite(self, path, name=None):
        """添加收藏夹"""
        if name is None:
            name = os.path.basename(path) or path
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT MAX(sort_order) FROM favorites')
            max_order = cursor.fetchone()[0]
            sort_order = (max_order or 0) + 1
            
            cursor.execute('''
                INSERT INTO favorites (name, path, sort_order, created_at)
                VALUES (?, ?, ?, ?)
            ''', (name, path, sort_order, time.time()))
            
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding favorite: {e}")
            return None
        finally:
            self.close()
    
    def remove_favorite(self, path_or_id):
        """删除收藏夹"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            
            if isinstance(path_or_id, int):
                cursor.execute('DELETE FROM favorites WHERE id = ?', (path_or_id,))
            else:
                cursor.execute('DELETE FROM favorites WHERE path = ?', (path_or_id,))
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error removing favorite: {e}")
        finally:
            self.close()
    
    def get_all_favorites(self):
        """获取所有收藏夹"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM favorites ORDER BY sort_order')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting favorites: {e}")
            return []
        finally:
            self.close()
    
    def get_favorites(self):
        """获取所有收藏夹 (别名)"""
        return self.get_all_favorites()
    
    def reorder_favorites(self, favorite_ids):
        """重新排序收藏夹"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            for order, fav_id in enumerate(favorite_ids, 1):
                cursor.execute('UPDATE favorites SET sort_order = ? WHERE id = ?', (order, fav_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error reordering favorites: {e}")
        finally:
            self.close()

    # ==================== 集合操作 ====================
    
    def create_collection(self, name, description="", is_smart=False, smart_criteria=None):
        """创建集合"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            now = time.time()
            cursor.execute('''
                INSERT INTO collections (name, description, is_smart, smart_criteria, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, description, 1 if is_smart else 0, smart_criteria, now, now))
            
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return None
        finally:
            self.close()
    
    def add_file_to_collection(self, file_id, collection_id):
        """将文件添加到集合"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO file_collections (file_id, collection_id, added_at)
                VALUES (?, ?, ?)
            ''', (file_id, collection_id, time.time()))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding file to collection: {e}")
        finally:
            self.close()
    
    def get_files_in_collection(self, collection_id):
        """获取集合中的所有文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM files f
                JOIN file_collections fc ON f.id = fc.file_id
                WHERE fc.collection_id = ?
                ORDER BY f.is_pinned DESC, f.pin_order, fc.added_at DESC
            ''', (collection_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files in collection: {e}")
            return []
        finally:
            self.close()
    
    def get_all_collections(self):
        """获取所有集合"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM collections ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting collections: {e}")
            return []
        finally:
            self.close()

    # ==================== 文件夹操作（增强版）====================
    
    def upsert_folder(self, path, recursive=False):
        """
        插入或更新文件夹信息（增强版）
        
        Args:
            path: 文件夹路径
            recursive: 是否递归扫描子文件和子文件夹
        
        Returns:
            folder_id or None
        """
        if not os.path.exists(path) or not os.path.isdir(path):
            return None
        
        name = os.path.basename(path) or path
        parent_path = os.path.dirname(path)

        try:
            self.connect()
            cursor = self.conn.cursor()
            parent_id = self._get_folder_id_by_path(parent_path) if parent_path != path else None
            stat = os.stat(path)
            created_time = stat.st_ctime
            modified_time = stat.st_mtime
            
            self.connect()
            cursor = self.conn.cursor()
            
            # 计算子文件数和子文件夹数
            children_file_count = 0
            children_folder_count = 0
            
            if recursive:
                # 递归扫描子项
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path):
                            children_file_count += 1
                            # 递归插入文件
                            self.upsert_file(item_path)
                        elif os.path.isdir(item_path):
                            children_folder_count += 1
                            # 递归插入子文件夹
                            self.upsert_folder(item_path, recursive=True)
                    except (PermissionError, OSError):
                        continue
            else:
                # 只统计数量，不插入
                try:
                    for item in os.listdir(path):
                        item_path = os.path.join(path, item)
                        if os.path.isfile(item_path):
                            children_file_count += 1
                        elif os.path.isdir(item_path):
                            children_folder_count += 1
                except (PermissionError, OSError):
                    pass
            
            cursor.execute('''
                INSERT INTO folders (
                    path, parent_id, name,
                    created_time, modified_time, 
                    children_file_count, children_folder_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    parent_id=excluded.parent_id,
                    modified_time=excluded.modified_time,
                    children_file_count=excluded.children_file_count,
                    children_folder_count=excluded.children_folder_count
            ''', (path, parent_id, name,
                  created_time, modified_time,
                  children_file_count, children_folder_count))
            
            folder_id = cursor.lastrowid if cursor.lastrowid else self._get_folder_id_by_path(path)
            self.conn.commit()
            return folder_id
        except Exception as e:
            logger.error(f"Error upserting folder: {e}", exc_info=True)
            return None
        finally:
            self.close()
    
    def _get_folder_id_by_path(self, path):
        """根据路径获取文件夹ID（内部方法）"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM folders WHERE path = ?', (path,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def update_folder_children_count(self, folder_id):
        """更新文件夹的子项计数（手动触发）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            
            # 获取文件夹路径
            cursor.execute('SELECT path FROM folders WHERE id = ?', (folder_id,))
            row = cursor.fetchone()
            if not row:
                return
            
            folder_path = row[0]
            
            # 统计子文件
            cursor.execute('''
                SELECT COUNT(*) FROM files 
                WHERE path LIKE ? AND path NOT LIKE ?
            ''', (folder_path + os.sep + '%', folder_path + os.sep + '%' + os.sep + '%'))
            children_file_count = cursor.fetchone()[0]
            
            # 统计子文件夹
            cursor.execute('''
                SELECT COUNT(*) FROM folders 
                WHERE parent_id = ?
            ''', (folder_id,))
            children_folder_count = cursor.fetchone()[0]
            
            # 更新
            cursor.execute('''
                UPDATE folders 
                SET children_file_count = ?, children_folder_count = ?
                WHERE id = ?
            ''', (children_file_count, children_folder_count, folder_id))
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating folder children count: {e}")
        finally:
            self.close()
    
    def get_folder_by_path(self, path):
        """根据路径获取文件夹"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM folders WHERE path = ?', (path,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting folder: {e}")
            return None
        finally:
            self.close()
    
    def get_files_in_folder(self, folder_path):
        """获取文件夹中的所有直接子文件（不包括子文件夹中的）"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            folder_path_pattern = folder_path.rstrip(os.sep) + os.sep
            cursor.execute('''
                SELECT * FROM files 
                WHERE path LIKE ? AND path NOT LIKE ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (folder_path_pattern + '%', folder_path_pattern + '%' + os.sep + '%'))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files in folder: {e}")
            return []
        finally:
            self.close()
    
    
    def get_all_folders(self):
        """获取所有文件夹"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM folders ORDER BY is_pinned DESC, pin_order, name')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all folders: {e}")
            return []
        finally:
            self.close()

    # ==================== 搜索操作 ====================
    
    def search_files_by_name(self, keyword):
        """按文件名搜索文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE filename LIKE ? OR path LIKE ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (f'%{keyword}%', f'%{keyword}%'))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error searching files by name: {e}")
            return []
        finally:
            self.close()
    
    def search_files_by_tag_name(self, tag_name):
        """按标签名搜索文件"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM files f
                JOIN file_tags ft ON f.id = ft.file_id
                JOIN tags t ON ft.tag_id = t.id
                WHERE t.name LIKE ?
                ORDER BY f.is_pinned DESC, f.pin_order, f.filename
            ''', (f'%{tag_name}%',))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error searching files by tag name: {e}")
            return []
        finally:
            self.close()
    
    def remove_file_tag(self, file_id, tag_id):
        """移除文件的标签关联"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error removing file tag: {e}")
        finally:
            self.close()
    
    def remove_folder_tag(self, folder_id, tag_id):
        """移除文件夹的标签关联"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM folder_tags WHERE folder_id = ? AND tag_id = ?', (folder_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error removing folder tag: {e}")
        finally:
            self.close()
    
    def delete_file(self, file_id):
        """删除文件记录"""
        self.connect()
        cursor = self.get_cursor()
        try:
            cursor.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
            cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
            return False
        finally:
            self.close()

    def get_files_recursive(self, folder_path):
        """递归获取文件夹下的所有文件（基于数据库）"""
        try:
            self.connect()
            cursor = self.get_cursor()
            folder_path = os.path.normpath(folder_path)
            # 确保路径以分隔符结尾
            if not folder_path.endswith(os.sep):
                folder_path += os.sep
            
            # 使用 LIKE 查询匹配子路径
            query = "SELECT * FROM files WHERE path LIKE ? ORDER BY filename"
            cursor.execute(query, (f"{folder_path}%",))
            
            columns = [description[0] for description in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        except Exception as e:
            logger.error(f"Error getting files recursively: {e}")
            return []
        finally:
            self.close()

    def get_folders_recursive(self, folder_path):
        """递归获取文件夹下的所有子文件夹（基于数据库）"""
        try:
            self.connect()
            cursor = self.get_cursor()
            folder_path = os.path.normpath(folder_path)
            if not folder_path.endswith(os.sep):
                folder_path += os.sep
                
            query = "SELECT * FROM folders WHERE path LIKE ? ORDER BY name"
            cursor.execute(query, (f"{folder_path}%",))
            
            columns = [description[0] for description in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        except Exception as e:
            logger.error(f"Error getting folders recursively: {e}")
            return []
        finally:
            self.close()

# ===================|===================
# 文件名: bottom_bar.py


# ===================|===================
# 文件名: cache_manager.py
import os
import hashlib
import subprocess
import json
from PIL import Image, ExifTags
from db_manager import DatabaseManager
import time

from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtCore import QSize, QThread, pyqtSignal

import queue

class ThumbnailLoader(QThread):
    """鍚庡彴鍔犺浇缂╃暐鍥剧嚎绋?- 闃熷垪妯″紡"""
    thumbnail_ready = pyqtSignal(str, str) # path, thumb_path

    def __init__(self, cache_manager):
        super().__init__()
        self.cache = cache_manager
        self.queue = queue.Queue()
        self.is_running = True
        self._lock = False # 绠€鍗曠殑閿佹爣蹇?

    def add_paths(self, file_paths):
        """娣诲姞浠诲姟鍒伴槦鍒?""
        for path in file_paths:
            self.queue.put(path)

    def run(self):
        while self.is_running:
            try:
                # 闈為樆濉炶幏鍙栵紝浠ヤ究鑳藉搷搴?stop
                path = self.queue.get(timeout=0.1)
                
                # 鑾峰彇鎴栫敓鎴愮缉鐣ュ浘
                thumb_path = self.cache.get_thumbnail(path)
                if thumb_path:
                    self.thumbnail_ready.emit(path, thumb_path)
                
                self.queue.task_done()
                
                # Small sleep to yield UI/CPU
                time.sleep(0.005)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Thumbnail loader error: {e}")

    def stop(self):
        self.is_running = False
        self.wait()

class ThumbnailCache:
    def __init__(self, cache_dir=None):
        # 榛樿缂撳瓨鐩綍鍦ㄥ綋鍓嶈剼鏈洰褰曚笅鐨?.thumbnails
        if cache_dir is None:
            # 鑾峰彇褰撳墠鑴氭湰鎵€鍦ㄧ洰褰?(PythonBridgeTool)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.cache_dir = os.path.join(current_dir, ".thumbnails")
        else:
            self.cache_dir = cache_dir
            
        if not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir)
            except Exception as e:
                print(f"Error creating cache dir {self.cache_dir}: {e}")
        
        print(f"Thumbnail Cache Dir: {self.cache_dir}")

    def get_thumbnail(self, file_path):
        """鑾峰彇缂╃暐鍥捐矾寰勶紝濡傛灉涓嶅瓨鍦ㄦ垨杩囨湡鍒欑敓鎴?""
        try:
            # 瑙勮寖鍖栬矾寰勶紝纭繚璺ㄥ钩鍙板拰澶у皬鍐欎竴鑷存€?
            norm_path = os.path.normpath(file_path).lower()
            
            # 浣跨敤鏂囦欢璺緞鐨?MD5 浣滀负缂╃暐鍥炬枃浠跺悕
            file_hash = hashlib.md5(norm_path.encode('utf-8')).hexdigest()
            thumb_name = f"{file_hash}.jpg"
            thumb_path = os.path.join(self.cache_dir, thumb_name)
            
            # print(f"[ThumbCache] Path: {file_path} -> Norm: {norm_path} -> Hash: {file_hash}")

            if os.path.exists(thumb_path):
                # Check if stale
                if self.is_stale(file_path, thumb_path):
                    print(f"[ThumbCache] Stale thumbnail for: {file_path}")
                    return self.generate_thumbnail(file_path, thumb_path)
                return thumb_path
            
            print(f"[ThumbCache] Generating new thumbnail for: {file_path}")
            return self.generate_thumbnail(file_path, thumb_path)
        except Exception as e:
            print(f"[ThumbCache] Error in get_thumbnail: {e}")
            return None

    def queue_thumbnail(self, file_path):
        """Queue thumbnail generation (for now just call get_thumbnail)"""
        # In a more advanced implementation, this would add to a background worker queue
        # For now, we rely on the threaded loader calling get_thumbnail
        return self.get_thumbnail(file_path)

    def is_stale(self, source_path, thumb_path):
        """妫€鏌ョ缉鐣ュ浘鏄惁杩囨湡"""
        try:
            source_mtime = os.path.getmtime(source_path)
            thumb_mtime = os.path.getmtime(thumb_path)
            return source_mtime > thumb_mtime
        except OSError:
            return True

    def generate_thumbnail(self, file_path, save_path):
        """鐢熸垚骞朵繚瀛樼缉鐣ュ浘"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            # Image formats (including .ico, .psd, .ai, .eps)
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.ico', '.icon', '.psd', '.ai', '.eps'):
                return self.generate_image_thumbnail(file_path, save_path)
            
            # SVG format
            elif ext == '.svg':
                return self.generate_svg_thumbnail(file_path, save_path)
            
            # Video formats
            elif ext in ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv'):
                return self.generate_video_thumbnail(file_path, save_path)
            
            return None
        except Exception as e:
            print(f"Error generating thumbnail for {file_path}: {e}")
            return None

    def generate_image_thumbnail(self, file_path, save_path):
        with Image.open(file_path) as img:
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.thumbnail((256, 256))
            img.save(save_path, "JPEG", quality=80)
        return save_path

    def generate_svg_thumbnail(self, file_path, save_path):
        """Generate thumbnail for SVG using QtSvg"""
        try:
            renderer = QSvgRenderer(file_path)
            if not renderer.isValid():
                return None
            
            # Create a white background image
            image = QImage(256, 256, QImage.Format.Format_RGB32)
            image.fill(QColor("white"))
            
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            
            image.save(save_path, "JPEG", 80)
            return save_path
        except Exception as e:
            print(f"Error generating SVG thumbnail: {e}")
            return None

    def generate_video_thumbnail(self, file_path, save_path):
        """Use ffmpeg to generate video thumbnail"""
        try:
            # Extract frame at 1 second mark
            cmd = [
                'ffmpeg', '-y', 
                '-ss', '00:00:01.000', 
                '-i', file_path, 
                '-vframes', '1', 
                '-q:v', '2', 
                '-vf', 'scale=256:-1', # Scale width to 256, keep aspect ratio
                save_path
            ]
            # Suppress output
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return save_path
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"FFmpeg failed or not found for {file_path}")
            return None

class MetadataCache:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def update_metadata(self, file_id, file_path):
        """鎻愬彇鍏冩暟鎹苟鏇存柊鍒版暟鎹簱"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if not ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.psd', '.ai', '.eps'):
                return

            with Image.open(file_path) as img:
                width, height = img.size
                
                # Extract EXIF
                exif_data = {}
                if hasattr(img, '_getexif') and img._getexif():
                    for tag, value in img._getexif().items():
                        tag_name = ExifTags.TAGS.get(tag, tag)
                        # Filter out binary data or too long strings
                        if isinstance(value, (bytes, bytearray)) or len(str(value)) > 100:
                            continue
                        exif_data[str(tag_name)] = str(value)
                
                exif_json = json.dumps(exif_data) if exif_data else None

                self.db.connect()
                cursor = self.db.get_cursor()
                cursor.execute('''
                    INSERT INTO metadata (file_id, width, height, exif_data)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(file_id) DO UPDATE SET
                        width=excluded.width,
                        height=excluded.height,
                        exif_data=excluded.exif_data
                ''', (file_id, width, height, exif_json))
                self.db.conn.commit()
                self.db.close()
        except Exception as e:
            print(f"Error extracting metadata for {file_path}: {e}")


# ===================|===================
# 文件名: check_db_schema.py
import sqlite3
import os

DB_PATH = "file_manager.db"

def check_schema():
    if not os.path.exists(DB_PATH):
        print("Database file not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Files Table Columns ---")
    try:
        cursor.execute("PRAGMA table_info(files)")
        columns = cursor.fetchall()
        for col in columns:
            print(col)
    except Exception as e:
        print(f"Error reading files table: {e}")

    print("\n--- Folders Table Columns ---")
    try:
        cursor.execute("PRAGMA table_info(folders)")
        columns = cursor.fetchall()
        for col in columns:
            print(col)
    except Exception as e:
        print(f"Error reading folders table: {e}")

    conn.close()

if __name__ == "__main__":
    check_schema()


# ===================|===================
# 文件名: color_label.py
"""
褰╄壊鏍囩缁勪欢

鏀寔 5 绉嶉鑹叉爣绛撅細
- 绾㈣壊 (red) - 閲嶈/绱ф€?
- 榛勮壊 (yellow) - 寰呭鐞?
- 缁胯壊 (green) - 宸叉壒鍑?瀹屾垚
- 钃濊壊 (blue) - 娆¤/鍙傝€?
- 绱壊 (purple) - 鑷畾涔夌敤閫?
"""

from PyQt6.QtWidgets import QWidget, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QAction

# 棰滆壊瀹氫箟
COLOR_LABELS = {
    'red': {'name': '绾㈣壊', 'color': QColor(220, 50, 50), 'desc': '閲嶈/绱ф€?},
    'yellow': {'name': '榛勮壊', 'color': QColor(255, 200, 0), 'desc': '寰呭鐞?},
    'green': {'name': '缁胯壊', 'color': QColor(50, 180, 50), 'desc': '宸叉壒鍑?瀹屾垚'},
    'blue': {'name': '钃濊壊', 'color': QColor(50, 120, 220), 'desc': '娆¤/鍙傝€?},
    'purple': {'name': '绱壊', 'color': QColor(150, 50, 200), 'desc': '鑷畾涔夌敤閫?},
}

class ColorDot(QWidget):
    """褰╄壊鍦嗙偣缁勪欢"""
    
    def __init__(self, color=None, size=12):
        super().__init__()
        self.color = color
        self.dot_size = size
        self.setFixedSize(size, size)
    
    def set_color(self, color):
        """璁剧疆棰滆壊"""
        self.color = color
        self.update()
    
    def paintEvent(self, event):
        """缁樺埗褰╄壊鍦嗙偣"""
        if not self.color or self.color not in COLOR_LABELS:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        color_info = COLOR_LABELS[self.color]
        painter.setBrush(QBrush(color_info['color']))
        painter.setPen(QPen(color_info['color'].darker(120), 1))
        
        # 缁樺埗鍦嗗舰
        margin = 2
        painter.drawEllipse(margin, margin, self.dot_size - 2*margin, self.dot_size - 2*margin)


class ColorLabelMenu(QMenu):
    """褰╄壊鏍囩閫夋嫨鑿滃崟"""
    color_selected = pyqtSignal(str)  # 閫変腑鐨勯鑹?
    
    def __init__(self, parent=None, current_color=None):
        super().__init__("棰滆壊鏍囩", parent)
        self.current_color = current_color
        self._setup_menu()
    
    def _setup_menu(self):
        """璁剧疆鑿滃崟椤?""
        # 娣诲姞娓呴櫎棰滆壊閫夐」
        clear_action = QAction("娓呴櫎棰滆壊", self)
        clear_action.triggered.connect(lambda: self.color_selected.emit(''))
        self.addAction(clear_action)
        
        self.addSeparator()
        
        # 娣诲姞棰滆壊閫夐」
        for color_key, color_info in COLOR_LABELS.items():
            action = QAction(f"{color_info['name']} - {color_info['desc']}", self)
            action.triggered.connect(lambda checked, c=color_key: self.color_selected.emit(c))
            
            # 濡傛灉鏄綋鍓嶉鑹诧紝娣诲姞鍕鹃€夋爣璁?
            if color_key == self.current_color:
                action.setCheckable(True)
                action.setChecked(True)
            
            self.addAction(action)


class ColorLabelWidget(QWidget):
    """褰╄壊鏍囩缁勪欢锛堝寘鍚渾鐐瑰拰鑿滃崟锛?""
    color_changed = pyqtSignal(str)
    
    def __init__(self, color=None, size=12, editable=True):
        super().__init__()
        self.color = color
        self.editable = editable
        self.dot = ColorDot(color, size)
        
        from PyQt6.QtWidgets import QHBoxLayout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.dot)
        
        if editable:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._show_color_menu)
    
    def set_color(self, color):
        """璁剧疆棰滆壊"""
        self.color = color
        self.dot.set_color(color)
    
    def _show_color_menu(self, pos):
        """鏄剧ず棰滆壊閫夋嫨鑿滃崟"""
        menu = ColorLabelMenu(self, self.color)
        menu.color_selected.connect(self._on_color_selected)
        menu.exec(self.mapToGlobal(pos))
    
    def _on_color_selected(self, color):
        """棰滆壊琚€変腑"""
        self.set_color(color)
        self.color_changed.emit(color)


def get_color_qcolor(color_key):
    """鑾峰彇棰滆壊鐨?QColor 瀵硅薄"""
    if color_key in COLOR_LABELS:
        return COLOR_LABELS[color_key]['color']
    return None


def get_color_name(color_key):
    """鑾峰彇棰滆壊鐨勪腑鏂囧悕绉?""
    if color_key in COLOR_LABELS:
        return COLOR_LABELS[color_key]['name']
    return "鏃?


# ===================|===================
# 文件名: data_source_manager.py
"""
鏁版嵁婧愮鐞嗗櫒妯″潡

鎻愪緵缁熶竴鎺ュ彛绠＄悊鏂囦欢鍏冩暟鎹紝鏀寔鍙屽啓妯″紡锛堝悓鏃跺啓鍏?JSON 鍜?SQLite锛?
"""

import os
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from logger import get_logger

logger = get_logger("DataSourceManager")


class BaseDataSource(ABC):
    """鏁版嵁婧愬熀绫伙紝瀹氫箟缁熶竴鎺ュ彛"""
    
    @abstractmethod
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """鑾峰彇鏂囦欢/鏂囦欢澶圭殑鍏冩暟鎹?""
        pass
    
    @abstractmethod
    def set_pin(self, path: str, pinned: bool) -> bool:
        """璁剧疆缃《鐘舵€?""
        pass
    
    @abstractmethod
    def set_rating(self, path: str, rating: int) -> bool:
        """璁剧疆璇勭骇 (0-5)"""
        pass
    
    @abstractmethod
    def set_label(self, path: str, label: str) -> bool:
        """璁剧疆鏂囨湰鏍囩"""
        pass
    
    @abstractmethod
    def set_color(self, path: str, color: str) -> bool:
        """璁剧疆棰滆壊鏍囩"""
        pass
    
    @abstractmethod
    def get_all_items(self) -> List[Dict[str, Any]]:
        """鑾峰彇褰撳墠鑼冨洿鍐呮墍鏈夐」鐩強鍏跺厓鏁版嵁"""
        pass


class JSONDataSource(BaseDataSource):
    """JSON 鏂囦欢鏁版嵁婧愶紙鐢ㄤ簬灞€閮?鍗曟枃浠跺す鑼冨洿锛?""
    
    METADATA_FILENAME = ".bridge_metadata.json"
    
    def __init__(self, folder_path: str):
        """
        鍒濆鍖?JSON 鏁版嵁婧?
        
        Args:
            folder_path: 鏂囦欢澶硅矾寰?
        """
        self.folder_path = folder_path
        self.metadata_file = os.path.join(folder_path, self.METADATA_FILENAME)
        self._cache = None
        logger.info(f"鍒濆鍖?JSON 鏁版嵁婧? {folder_path}")
    
    def _load_metadata(self) -> Dict[str, Any]:
        """鍔犺浇 JSON 鍏冩暟鎹枃浠?""
        if self._cache is not None:
            return self._cache
        
        if not os.path.exists(self.metadata_file):
            # 鍒涘缓榛樿缁撴瀯
            self._cache = {
                "bridgedata": {
                    "version": "1",
                    "labels": {"version": "1", "items": []},
                    "ratings": {"version": "1", "items": []},
                    "pins": {"version": "1", "items": []},
                    "colors": {"version": "1", "items": []}
                }
            }
            return self._cache
        
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                self._cache = json.load(f)
                logger.debug(f"鎴愬姛鍔犺浇鍏冩暟鎹? {self.metadata_file}")
                return self._cache
        except Exception as e:
            logger.error(f"鍔犺浇鍏冩暟鎹枃浠跺け璐? {e}")
            # 杩斿洖榛樿缁撴瀯
            self._cache = {
                "bridgedata": {
                    "version": "1",
                    "labels": {"version": "1", "items": []},
                    "ratings": {"version": "1", "items": []},
                    "pins": {"version": "1", "items": []},
                    "colors": {"version": "1", "items": []}
                }
            }
            return self._cache
    
    def _save_metadata(self, data: Dict[str, Any]) -> bool:
        """淇濆瓨鍏冩暟鎹埌 JSON 鏂囦欢"""
        try:
            # 纭繚鐩綍瀛樺湪
            os.makedirs(os.path.dirname(self.metadata_file), exist_ok=True)
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self._cache = data
            logger.debug(f"鎴愬姛淇濆瓨鍏冩暟鎹? {self.metadata_file}")
            return True
        except Exception as e:
            logger.error(f"淇濆瓨鍏冩暟鎹枃浠跺け璐? {e}")
            return False
    
    def _get_filename(self, path: str) -> str:
        """鑾峰彇鏂囦欢鍚嶏紙鐩稿浜庡綋鍓嶆枃浠跺す锛?""
        return os.path.basename(path)
    
    def _find_item(self, items: List[Dict], key: str) -> Optional[Dict]:
        """鍦ㄥ垪琛ㄤ腑鏌ユ壘鎸囧畾 key 鐨勯」"""
        for item in items:
            if item.get("key") == key:
                return item
        return None
    
    def _update_or_add_item(self, items: List[Dict], key: str, **kwargs) -> List[Dict]:
        """鏇存柊鎴栨坊鍔犻」"""
        item = self._find_item(items, key)
        if item:
            item.update(kwargs)
        else:
            items.append({"key": key, **kwargs})
        return items
    
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """鑾峰彇鏂囦欢/鏂囦欢澶圭殑鍏冩暟鎹?""
        data = self._load_metadata()
        bridge = data.get("bridgedata", {})
        filename = self._get_filename(path)
        
        metadata = {
            "path": path,
            "is_pinned": False,
            "rating": 0,
            "label": None,
            "label_color": None
        }
        
        # 璇诲彇缃《鐘舵€?
        pins = bridge.get("pins", {}).get("items", [])
        pin_item = self._find_item(pins, filename)
        if pin_item:
            metadata["is_pinned"] = pin_item.get("pinned", False)
        
        # 璇诲彇璇勭骇
        ratings = bridge.get("ratings", {}).get("items", [])
        rating_item = self._find_item(ratings, filename)
        if rating_item:
            metadata["rating"] = int(rating_item.get("rating", 0))
        
        # 璇诲彇鏍囩
        labels = bridge.get("labels", {}).get("items", [])
        label_item = self._find_item(labels, filename)
        if label_item:
            metadata["label"] = label_item.get("label")
        
        # 璇诲彇棰滆壊
        colors = bridge.get("colors", {}).get("items", [])
        color_item = self._find_item(colors, filename)
        if color_item:
            metadata["label_color"] = color_item.get("color")
        
        return metadata
    
    def set_pin(self, path: str, pinned: bool) -> bool:
        """璁剧疆缃《鐘舵€?""
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        pins = bridge["pins"]["items"]
        self._update_or_add_item(pins, filename, pinned=pinned)
        bridge["pins"]["items"] = pins
        
        logger.info(f"璁剧疆缃《: {filename} = {pinned}")
        return self._save_metadata(data)
    
    def set_rating(self, path: str, rating: int) -> bool:
        """璁剧疆璇勭骇 (0-5)"""
        if not 0 <= rating <= 5:
            logger.warning(f"鏃犳晥鐨勮瘎绾? {rating}")
            return False
        
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        ratings = bridge["ratings"]["items"]
        self._update_or_add_item(ratings, filename, rating=str(rating))
        bridge["ratings"]["items"] = ratings
        
        logger.info(f"璁剧疆璇勭骇: {filename} = {rating}")
        return self._save_metadata(data)
    
    def set_label(self, path: str, label: str) -> bool:
        """璁剧疆鏂囨湰鏍囩"""
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        labels = bridge["labels"]["items"]
        if label:
            self._update_or_add_item(labels, filename, label=label)
        else:
            # 鍒犻櫎鏍囩
            labels = [item for item in labels if item.get("key") != filename]
        bridge["labels"]["items"] = labels
        
        logger.info(f"璁剧疆鏍囩: {filename} = {label}")
        return self._save_metadata(data)
    
    def set_color(self, path: str, color: str) -> bool:
        """璁剧疆棰滆壊鏍囩"""
        data = self._load_metadata()
        bridge = data["bridgedata"]
        filename = self._get_filename(path)
        
        colors = bridge["colors"]["items"]
        if color:
            self._update_or_add_item(colors, filename, color=color)
        else:
            # 鍒犻櫎棰滆壊
            colors = [item for item in colors if item.get("key") != filename]
        bridge["colors"]["items"] = colors
        
        logger.info(f"璁剧疆棰滆壊: {filename} = {color}")
        return self._save_metadata(data)
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """鑾峰彇褰撳墠鏂囦欢澶瑰唴鎵€鏈夐」鐩強鍏跺厓鏁版嵁"""
        items = []
        if not os.path.exists(self.folder_path):
            return items
        
        try:
            for item_name in os.listdir(self.folder_path):
                # 璺宠繃鍏冩暟鎹枃浠舵湰韬?
                if item_name == self.METADATA_FILENAME:
                    continue
                
                item_path = os.path.join(self.folder_path, item_name)
                metadata = self.get_item_metadata(item_path)
                items.append(metadata)
            
            return items
        except Exception as e:
            logger.error(f"鑾峰彇鏂囦欢澶归」鐩け璐? {e}")
            return []


class SQLiteDataSource(BaseDataSource):
    """SQLite 鏁版嵁婧愶紙鐢ㄤ簬鍏ㄥ眬鑼冨洿锛?""
    
    def __init__(self, db_manager):
        """
        鍒濆鍖?SQLite 鏁版嵁婧?
        
        Args:
            db_manager: DatabaseManager 瀹炰緥
        """
        self.db = db_manager
        logger.info("鍒濆鍖?SQLite 鏁版嵁婧?)
    
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """鑾峰彇鏂囦欢/鏂囦欢澶圭殑鍏冩暟鎹?""
        metadata = {
            "path": path,
            "is_pinned": False,
            "rating": 0,
            "label": None,
            "label_color": None
        }
        
        is_dir = os.path.isdir(path)
        
        try:
            if is_dir:
                # 鏂囦欢澶?
                folder_data = self.db.get_folder_by_path(path)
                if folder_data:
                    metadata["is_pinned"] = folder_data.get("is_pinned", False)
                    metadata["rating"] = folder_data.get("rating", 0)
                    metadata["label_color"] = folder_data.get("label_color")
                    # 鑾峰彇鏍囩
                    tags = self.db.get_folder_tags(folder_data["id"])
                    if tags:
                        metadata["label"] = tags[0].get("name")
            else:
                # 鏂囦欢
                file_id = self.db._get_file_id_by_path(path)
                if file_id:
                    file_data = self.db.get_file_by_id(file_id)
                    if file_data:
                        metadata["is_pinned"] = file_data.get("is_pinned", False)
                        metadata["rating"] = file_data.get("rating", 0)
                        metadata["label_color"] = file_data.get("label_color")
                        # 鑾峰彇鏍囩
                        tags = self.db.get_file_tags(file_id)
                        if tags:
                            metadata["label"] = tags[0].get("name")
        except Exception as e:
            logger.error(f"鑾峰彇鍏冩暟鎹け璐? {e}")
        
        return metadata
    
    def set_pin(self, path: str, pinned: bool) -> bool:
        """璁剧疆缃《鐘舵€?""
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    if pinned:
                        self.db.pin_folder(folder_id)
                    else:
                        self.db.unpin_folder(folder_id)
                    logger.info(f"璁剧疆鏂囦欢澶圭疆椤? {path} = {pinned}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    if pinned:
                        self.db.pin_file(file_id)
                    else:
                        self.db.unpin_file(file_id)
                    logger.info(f"璁剧疆鏂囦欢缃《: {path} = {pinned}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"璁剧疆缃《澶辫触: {e}")
            return False
    
    def set_rating(self, path: str, rating: int) -> bool:
        """璁剧疆璇勭骇 (0-5)"""
        if not 0 <= rating <= 5:
            logger.warning(f"鏃犳晥鐨勮瘎绾? {rating}")
            return False
        
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    self.db.set_folder_rating(folder_id, rating)
                    logger.info(f"璁剧疆鏂囦欢澶硅瘎绾? {path} = {rating}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    self.db.set_file_rating(file_id, rating)
                    logger.info(f"璁剧疆鏂囦欢璇勭骇: {path} = {rating}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"璁剧疆璇勭骇澶辫触: {e}")
            return False
    
    def set_label(self, path: str, label: str) -> bool:
        """璁剧疆鏂囨湰鏍囩"""
        try:
            is_dir = os.path.isdir(path)
            
            # 鍏堣幏鍙栨垨鍒涘缓鏍囩
            tag_id = None
            if label:
                tag_id = self.db.create_tag(label)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id and tag_id:
                    self.db.link_folder_tag(folder_id, tag_id)
                    logger.info(f"璁剧疆鏂囦欢澶规爣绛? {path} = {label}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id and tag_id:
                    self.db.link_file_tag(file_id, tag_id)
                    logger.info(f"璁剧疆鏂囦欢鏍囩: {path} = {label}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"璁剧疆鏍囩澶辫触: {e}")
            return False
    
    def set_color(self, path: str, color: str) -> bool:
        """璁剧疆棰滆壊鏍囩"""
        try:
            is_dir = os.path.isdir(path)
            
            if is_dir:
                folder_id = self.db.upsert_folder(path, recursive=False)
                if folder_id:
                    self.db.set_folder_label_color(folder_id, color)
                    logger.info(f"璁剧疆鏂囦欢澶归鑹? {path} = {color}")
                    return True
            else:
                file_id = self.db.upsert_file(path)
                if file_id:
                    self.db.set_file_label_color(file_id, color)
                    logger.info(f"璁剧疆鏂囦欢棰滆壊: {path} = {color}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"璁剧疆棰滆壊澶辫触: {e}")
            return False
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """鑾峰彇鎵€鏈夋枃浠跺強鍏跺厓鏁版嵁锛堝叏灞€鑼冨洿锛?""
        items = []
        try:
            files = self.db.get_all_files()
            for file_data in files:
                metadata = self.get_item_metadata(file_data["path"])
                items.append(metadata)
            return items
        except Exception as e:
            logger.error(f"鑾峰彇鎵€鏈夋枃浠跺け璐? {e}")
            return []


class DataSourceManager:
    """
    鏁版嵁婧愮鐞嗗櫒
    
    瀹炵幇鍙屽啓绛栫暐锛氭墍鏈夊厓鏁版嵁鎿嶄綔鍚屾椂鍐欏叆 JSON 鍜?SQLite
    """
    
    SCOPE_GLOBAL = "global"
    SCOPE_LOCAL = "local"
    
    def __init__(self, db_manager):
        """
        鍒濆鍖栨暟鎹簮绠＄悊鍣?
        
        Args:
            db_manager: DatabaseManager 瀹炰緥锛堢敤浜庡叏灞€鑼冨洿锛?
        """
        self.db_manager = db_manager
        self.sqlite_source = SQLiteDataSource(db_manager)
        self.json_source = None
        self.current_scope = self.SCOPE_GLOBAL
        self.current_folder = None
        logger.info("鏁版嵁婧愮鐞嗗櫒鍒濆鍖栧畬鎴?)
    
    def set_scope(self, scope: str, folder_path: str = None):
        """
        璁剧疆褰撳墠鎿嶄綔鑼冨洿
        
        Args:
            scope: 鑼冨洿绫诲瀷 ('global' 鎴?'local')
            folder_path: 鏂囦欢澶硅矾寰勶紙local 鑼冨洿鏃跺繀闇€锛?
        """
        self.current_scope = scope
        
        if scope == self.SCOPE_LOCAL and folder_path:
            self.current_folder = folder_path
            self.json_source = JSONDataSource(folder_path)
            logger.info(f"鍒囨崲鍒板眬閮ㄨ寖鍥? {folder_path}")
        else:
            self.current_folder = None
            self.json_source = None
            logger.info("鍒囨崲鍒板叏灞€鑼冨洿")
    
    def _get_current_source(self) -> BaseDataSource:
        """鑾峰彇褰撳墠娲诲姩鐨勬暟鎹簮"""
        if self.current_scope == self.SCOPE_LOCAL and self.json_source:
            return self.json_source
        return self.sqlite_source
    
    def get_item_metadata(self, path: str) -> Dict[str, Any]:
        """鑾峰彇鏂囦欢/鏂囦欢澶圭殑鍏冩暟鎹紙浼樺厛浠?JSON 璇诲彇锛?""
        # 濡傛灉鍦ㄥ眬閮ㄨ寖鍥达紝浼樺厛浠?JSON 璇诲彇
        if self.current_scope == self.SCOPE_LOCAL and self.json_source:
            metadata = self.json_source.get_item_metadata(path)
            # 濡傛灉 JSON 涓病鏈夋暟鎹紝灏濊瘯浠庢暟鎹簱璇诲彇
            if metadata['rating'] == 0 and not metadata['is_pinned'] and not metadata['label'] and not metadata['label_color']:
                db_metadata = self.sqlite_source.get_item_metadata(path)
                if db_metadata['rating'] != 0 or db_metadata['is_pinned'] or db_metadata['label'] or db_metadata['label_color']:
                    return db_metadata
            return metadata
        else:
            return self.sqlite_source.get_item_metadata(path)
    
    def _update_json_metadata(self, path: str, callback) -> bool:
        """
        杈呭姪鏂规硶锛氭洿鏂版寚瀹氭枃浠剁殑 JSON 鍏冩暟鎹?
        
        Args:
            path: 鏂囦欢缁濆璺緞
            callback: 鎺ュ彈 JSONDataSource 鍜?relative_path 鐨勫洖璋冨嚱鏁?
            
        Returns:
            bool: 鏄惁鎴愬姛鍐欏叆 JSON
        """
        try:
            folder_path = os.path.dirname(path)
            # 瀹炰緥鍖栦复鏃剁殑 JSONDataSource
            json_source = JSONDataSource(folder_path)
            return callback(json_source)
        except Exception as e:
            logger.error(f"鏇存柊 JSON 鍏冩暟鎹け璐? {e}")
            return False

    def set_pin(self, path: str, pinned: bool) -> bool:
        """璁剧疆缃《鐘舵€侊紙鍙屽啓锛氬悓鏃跺啓鍏?JSON 鍜屾暟鎹簱锛?""
        # 1. 鍐欏叆鏁版嵁搴?(鎬绘槸鎵ц)
        success_db = self.sqlite_source.set_pin(path, pinned)
        
        # 2. 鍐欏叆 JSON (鎬绘槸灏濊瘯鎵ц锛屾牴鎹枃浠惰矾寰勫姩鎬佸畾浣?
        success_json = self._update_json_metadata(path, lambda js: js.set_pin(path, pinned))
        
        logger.info(f"鍙屽啓缃《 - DB: {success_db}, JSON: {success_json}")
        return success_db or success_json
    
    def set_rating(self, path: str, rating: int) -> bool:
        """璁剧疆璇勭骇 (0-5)锛堝弻鍐欙細鍚屾椂鍐欏叆 JSON 鍜屾暟鎹簱锛?""
        # 1. 鍐欏叆鏁版嵁搴?
        success_db = self.sqlite_source.set_rating(path, rating)
        
        # 2. 鍐欏叆 JSON
        success_json = self._update_json_metadata(path, lambda js: js.set_rating(path, rating))
        
        logger.info(f"鍙屽啓璇勭骇 - DB: {success_db}, JSON: {success_json}")
        return success_db or success_json
    
    def set_label(self, path: str, label: str) -> bool:
        """璁剧疆鏂囨湰鏍囩锛堝弻鍐欙細鍚屾椂鍐欏叆 JSON 鍜屾暟鎹簱锛?""
        # 1. 鍐欏叆鏁版嵁搴?
        success_db = self.sqlite_source.set_label(path, label)
        
        # 2. 鍐欏叆 JSON
        success_json = self._update_json_metadata(path, lambda js: js.set_label(path, label))
        
        logger.info(f"鍙屽啓鏍囩 - DB: {success_db}, JSON: {success_json}")
        return success_db or success_json
    
    def set_color(self, path: str, color: str) -> bool:
        """璁剧疆棰滆壊鏍囩锛堝弻鍐欙細鍚屾椂鍐欏叆 JSON 鍜屾暟鎹簱锛?""
        # 1. 鍐欏叆鏁版嵁搴?
        success_db = self.sqlite_source.set_color(path, color)
        
        # 2. 鍐欏叆 JSON
        success_json = self._update_json_metadata(path, lambda js: js.set_color(path, color))
        
        logger.info(f"鍙屽啓棰滆壊 - DB: {success_db}, JSON: {success_json}")
        return success_db or success_json
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """鑾峰彇褰撳墠鑼冨洿鍐呮墍鏈夐」鐩強鍏跺厓鏁版嵁"""
        return self._get_current_source().get_all_items()
    
    def get_current_scope(self) -> str:
        """鑾峰彇褰撳墠鑼冨洿"""
        return self.current_scope
    
    def is_local_scope(self) -> bool:
        """鍒ゆ柇鏄惁涓哄眬閮ㄨ寖鍥?""
        return self.current_scope == self.SCOPE_LOCAL


# ===================|===================
# 文件名: db_manager.py
import sqlite3
import os
import time
from datetime import datetime
from logger import get_logger

logger = get_logger("DatabaseManager")

DB_PATH = "file_manager.db"

class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = db_path if db_path else DB_PATH
        self.conn = None
    
    def connect(self):
        """杩炴帴鏁版嵁搴?""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        except Exception as e:
            print(f"Error connecting to database: {e}")
            raise

    def get_cursor(self):
        """鑾峰彇娓告爣"""
        if not self.conn:
            self.connect()
        return self.conn.cursor()

    def close(self):
        """鍏抽棴鏁版嵁搴撹繛鎺?""
        if self.conn:
            self.conn.close()
            self.conn = None

    def init_db(self):
        """鍒濆鍖栨暟鎹簱锛屽垱寤烘墍鏈夊繀瑕佺殑琛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
    
            # 鍒涘缓 files 琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                filename TEXT,
                extension TEXT,
                size INTEGER,
                modified_time REAL,
                created_time REAL,
                access_count INTEGER DEFAULT 0,
                last_access_time REAL,
                rating INTEGER DEFAULT 0 CHECK(rating >= 0 AND rating <= 5),
                label_color TEXT,
                is_pinned INTEGER DEFAULT 0,
                pin_order INTEGER DEFAULT 0
            )
            ''')
    
            # 鍒涘缓 folders 琛?(浣跨敤 parent_id)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                parent_id INTEGER,
                name TEXT,
                last_scanned REAL,
                created_time REAL,
                modified_time REAL,
                children_file_count INTEGER DEFAULT 0,
                children_folder_count INTEGER DEFAULT 0,
                rating INTEGER DEFAULT 0 CHECK(rating >= 0 AND rating <= 5),
                label_color TEXT,
                is_pinned INTEGER DEFAULT 0,
                pin_order INTEGER DEFAULT 0,
                FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE SET NULL
            )
            ''')
    
            # 鍒涘缓 tags 琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT
            )
            ''')
    
            # 鍒涘缓 file_tags 鍏宠仈琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (file_id, tag_id),
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
            ''')
    
            # 鍒涘缓 folder_tags 鍏宠仈琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS folder_tags (
                folder_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (folder_id, tag_id),
                FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
            ''')
    
            # 鍒涘缓 favorites 琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                path TEXT UNIQUE NOT NULL,
                sort_order INTEGER,
                created_at REAL
            )
            ''')
    
            # 鍒涘缓 collections 琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                is_smart INTEGER DEFAULT 0,
                smart_criteria TEXT,
                created_at REAL,
                updated_at REAL
            )
            ''')
    
            # 鍒涘缓 file_collections 鍏宠仈琛?            cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_collections (
                file_id INTEGER,
                collection_id INTEGER,
                added_at REAL,
                PRIMARY KEY (file_id, collection_id),
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
            ''')
    
            # 涓?path 鍒楀垱寤虹储寮曚互鎻愰珮鏌ヨ閫熷害
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_path ON files (path)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_path ON folders (path)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_parent_id ON folders (parent_id)')
    
            self.conn.commit()
            
            # 妫€鏌ュ苟杩佺Щ鏋舵瀯
            self._check_and_migrate_schema()
            
            logger.info("鏁版嵁搴撳垵濮嬪寲鎴愬姛锛屾墍鏈夎〃宸插垱寤恒€?)
    
        except Exception as e:
            logger.error(f"鏁版嵁搴撳垵濮嬪寲澶辫触: {e}", exc_info=True)
        finally:
            self.close()

    def _check_and_migrate_schema(self):
        """妫€鏌ュ苟杩佺Щ鏁版嵁搴撴灦鏋勶紝娣诲姞缂哄け鐨勫垪"""
        try:
            cursor = self.conn.cursor()
            
            # 妫€鏌?files 琛?            cursor.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # 闇€瑕佹鏌ョ殑鍒楀強鍏剁被鍨?            required_columns = {
                'created_time': 'REAL',
                'modified_time': 'REAL',
                'extension': 'TEXT',
                'last_access_time': 'REAL',
                'rating': 'INTEGER DEFAULT 0',
                'label_color': 'TEXT',
                'is_pinned': 'INTEGER DEFAULT 0',
                'pin_order': 'INTEGER DEFAULT 0'
            }
            
            for col, col_type in required_columns.items():
                if col not in columns:
                    logger.info(f"Adding missing column '{col}' to files table...")
                    try:
                        cursor.execute(f"ALTER TABLE files ADD COLUMN {col} {col_type}")
                    except Exception as e:
                        logger.error(f"Failed to add column {col}: {e}")

            # 妫€鏌?folders 琛?            cursor.execute("PRAGMA table_info(folders)")
            columns = {row[1] for row in cursor.fetchall()}
            
            required_columns = {
                'created_time': 'REAL',
                'modified_time': 'REAL',
                'last_scanned': 'REAL',
                'children_file_count': 'INTEGER DEFAULT 0',
                'children_folder_count': 'INTEGER DEFAULT 0',
                'rating': 'INTEGER DEFAULT 0',
                'label_color': 'TEXT',
                'is_pinned': 'INTEGER DEFAULT 0',
                'pin_order': 'INTEGER DEFAULT 0'
            }
            
            for col, col_type in required_columns.items():
                if col not in columns:
                    logger.info(f"Adding missing column '{col}' to folders table...")
                    try:
                        cursor.execute(f"ALTER TABLE folders ADD COLUMN {col} {col_type}")
                    except Exception as e:
                        logger.error(f"Failed to add column {col}: {e}")
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Schema migration failed: {e}")

    # ==================== 鏂囦欢鎿嶄綔 ====================
    
    def upsert_file(self, path):
        """鎻掑叆鎴栨洿鏂版枃浠朵俊鎭紙澧炲己鐗堬紝鍖呭惈鎵€鏈夋柊瀛楁锛?""
        if not os.path.exists(path):
            return None
        
        stat = os.stat(path)
        filename = os.path.basename(path)
        extension = os.path.splitext(filename)[1].lower().lstrip('.')
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO files (
                    path, filename, extension, size,
                    created_time, modified_time, access_count
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size,
                    modified_time=excluded.modified_time,
                    extension=excluded.extension
            ''', (path, filename, extension, stat.st_size,
                  stat.st_ctime, stat.st_mtime))
            
            file_id = cursor.lastrowid if cursor.lastrowid else self._get_file_id_by_path(path)
            self.conn.commit()
            return file_id
        except Exception as e:
            logger.error(f"Error upserting file: {e}", exc_info=True)
            return None
        finally:
            self.close()
    
    def _get_file_id_by_path(self, path):
        """鏍规嵁璺緞鑾峰彇鏂囦欢ID锛堝唴閮ㄦ柟娉曪級"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM files WHERE path = ?', (path,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def increment_file_access_count(self, file_id):
        """澧炲姞鏂囦欢璁块棶璁℃暟"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE files 
                SET access_count = access_count + 1 
                WHERE id = ?
            ''', (file_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error incrementing access count: {e}")
        finally:
            self.close()
    
    def get_files_by_extension(self, extension):
        """鎸夋墿灞曞悕鏌ヨ鏂囦欢"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE extension = ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (extension.lower().lstrip('.'),))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by extension: {e}")
            return []
        finally:
            self.close()
    
    def get_most_accessed_files(self, limit=20):
        """鑾峰彇璁块棶娆℃暟鏈€澶氱殑鏂囦欢"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE access_count > 0
                ORDER BY access_count DESC, filename
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting most accessed files: {e}")
            return []
        finally:
            self.close()
    
    def get_all_files(self):
        """鑾峰彇鎵€鏈夋枃浠?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM files ORDER BY is_pinned DESC, pin_order, filename')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all files: {e}")
            return []
        finally:
            self.close()
    
    def get_file_by_id(self, file_id):
        """鏍规嵁ID鑾峰彇鏂囦欢"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting file by id: {e}")
            return None
        finally:
            self.close()

    # ==================== 鏍囩鎿嶄綔 ====================
    
    def create_tag(self, name, color="#FFFFFF"):
        """鍒涘缓鏂版爣绛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)
            ''', (name, color))
            
            if cursor.lastrowid:
                tag_id = cursor.lastrowid
            else:
                cursor.execute('SELECT id FROM tags WHERE name = ?', (name,))
                tag_id = cursor.fetchone()[0]
            
            self.conn.commit()
            return tag_id
        except Exception as e:
            logger.error(f"Error creating tag: {e}")
            return None
        finally:
            self.close()

    def link_file_tag(self, file_id, tag_id):
        """灏嗘枃浠跺叧鑱斿埌鏍囩"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO file_tags (file_id, tag_id) 
                VALUES (?, ?)
            ''', (file_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error linking file tag: {e}")
        finally:
            self.close()
    
    def link_folder_tag(self, folder_id, tag_id):
        """灏嗘枃浠跺す鍏宠仈鍒版爣绛撅紙鏂板锛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO folder_tags (folder_id, tag_id) 
                VALUES (?, ?)
            ''', (folder_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error linking folder tag: {e}")
        finally:
            self.close()

    def get_files_by_tag(self, tag_id):
        """鑾峰彇鎸囧畾鏍囩涓嬬殑鎵€鏈夋枃浠?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM files f
                JOIN file_tags ft ON f.id = ft.file_id
                WHERE ft.tag_id = ?
                ORDER BY f.is_pinned DESC, f.pin_order, f.filename
            ''', (tag_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by tag: {e}")
            return []
        finally:
            self.close()
    
    def get_folders_by_tag(self, tag_id):
        """鑾峰彇鎸囧畾鏍囩涓嬬殑鎵€鏈夋枃浠跺す锛堟柊澧烇級"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM folders f
                JOIN folder_tags ft ON f.id = ft.folder_id
                WHERE ft.tag_id = ?
                ORDER BY f.is_pinned DESC, f.pin_order, f.name
            ''', (tag_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folders by tag: {e}")
            return []
        finally:
            self.close()

    def get_all_tags(self):
        """鑾峰彇鎵€鏈夋爣绛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM tags ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all tags: {e}")
            return []
        finally:
            self.close()

    def get_file_tags(self, file_id):
        """鑾峰彇鏌愪釜鏂囦欢宸插叧鑱旂殑鏍囩"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT t.*
                FROM tags t
                JOIN file_tags ft ON t.id = ft.tag_id
                WHERE ft.file_id = ?
                ORDER BY t.name
            ''', (file_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting file tags: {e}")
            return []
        finally:
            self.close()
    
    def get_folder_tags(self, folder_id):
        """鑾峰彇鏌愪釜鏂囦欢澶瑰凡鍏宠仈鐨勬爣绛撅紙鏂板锛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT t.*
                FROM tags t
                JOIN folder_tags ft ON t.id = ft.tag_id
                WHERE ft.folder_id = ?
                ORDER BY t.name
            ''', (folder_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folder tags: {e}")
            return []
        finally:
            self.close()

    # ==================== 璇勭骇鎿嶄綔 ====================
    
    def set_file_rating(self, file_id, rating):
        """璁剧疆鏂囦欢璇勭骇 (0-5)"""
        if not 0 <= rating <= 5:
            raise ValueError("Rating must be between 0 and 5")
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE files SET rating = ? WHERE id = ?', (rating, file_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting file rating: {e}")
        finally:
            self.close()
    
    def set_folder_rating(self, folder_id, rating):
        """璁剧疆鏂囦欢澶硅瘎绾?(0-5)锛堟柊澧烇級"""
        if not 0 <= rating <= 5:
            raise ValueError("Rating must be between 0 and 5")
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE folders SET rating = ? WHERE id = ?', (rating, folder_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting folder rating: {e}")
        finally:
            self.close()
    
    def get_files_by_rating(self, min_rating=0, max_rating=5):
        """鎸夎瘎绾ц寖鍥存煡璇㈡枃浠?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE rating BETWEEN ? AND ?
                ORDER BY is_pinned DESC, pin_order, rating DESC, filename
            ''', (min_rating, max_rating))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by rating: {e}")
            return []
        finally:
            self.close()
    
    def get_folders_by_rating(self, min_rating=0, max_rating=5):
        """鎸夎瘎绾ц寖鍥存煡璇㈡枃浠跺す锛堟柊澧烇級"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM folders 
                WHERE rating BETWEEN ? AND ?
                ORDER BY is_pinned DESC, pin_order, rating DESC, name
            ''', (min_rating, max_rating))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folders by rating: {e}")
            return []
        finally:
            self.close()

    # ==================== 褰╄壊鏍囪鎿嶄綔 ====================
    
    def set_file_label_color(self, file_id, color):
        """璁剧疆鏂囦欢棰滆壊鏍囩 (red/yellow/green/blue/purple/None)"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE files SET label_color = ? WHERE id = ?', (color, file_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting file label color: {e}")
        finally:
            self.close()
    
    def set_folder_label_color(self, folder_id, color):
        """璁剧疆鏂囦欢澶归鑹叉爣绛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('UPDATE folders SET label_color = ? WHERE id = ?', (color, folder_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting folder label color: {e}")
        finally:
            self.close()
    
    def get_files_by_label_color(self, color):
        """鎸夐鑹叉爣绛炬煡璇㈡枃浠?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE label_color = ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (color,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files by label color: {e}")
            return []
        finally:
            self.close()
    
    def get_folders_by_label_color(self, color):
        """鎸夐鑹叉爣绛炬煡璇㈡枃浠跺す锛堟柊澧烇級"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM folders 
                WHERE label_color = ?
                ORDER BY is_pinned DESC, pin_order, name
            ''', (color,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting folders by label color: {e}")
            return []
        finally:
            self.close()

    # ==================== 缃《鎿嶄綔 ====================
    
    def pin_file(self, file_id, pin_order=None):
        """缃《鏂囦欢"""
        if pin_order is None:
            try:
                self.connect()
                cursor = self.conn.cursor()
                cursor.execute('SELECT MAX(pin_order) FROM files WHERE is_pinned = 1')
                max_order = cursor.fetchone()[0]
                pin_order = (max_order or 0) + 1
            finally:
                self.close()
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE files SET is_pinned = 1, pin_order = ? WHERE id = ?
            ''', (pin_order, file_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error pinning file: {e}")
        finally:
            self.close()
    
    def unpin_file(self, file_id):
        """鍙栨秷缃《鏂囦欢"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE files SET is_pinned = 0, pin_order = 0 WHERE id = ?
            ''', (file_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error unpinning file: {e}")
        finally:
            self.close()
    
    def pin_folder(self, folder_id, pin_order=None):
        """缃《鏂囦欢澶?""
        if pin_order is None:
            try:
                self.connect()
                cursor = self.conn.cursor()
                cursor.execute('SELECT MAX(pin_order) FROM folders WHERE is_pinned = 1')
                max_order = cursor.fetchone()[0]
                pin_order = (max_order or 0) + 1
            finally:
                self.close()
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE folders SET is_pinned = 1, pin_order = ? WHERE id = ?
            ''', (pin_order, folder_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error pinning folder: {e}")
        finally:
            self.close()
    
    def unpin_folder(self, folder_id):
        """鍙栨秷缃《鏂囦欢澶癸紙鏂板锛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE folders SET is_pinned = 0, pin_order = 0 WHERE id = ?
            ''', (folder_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error unpinning folder: {e}")
        finally:
            self.close()
    
    def reorder_pinned_items(self, item_type, item_ids):
        """閲嶆柊鎺掑簭缃《椤?(item_type: 'file' or 'folder')"""
        table = 'files' if item_type == 'file' else 'folders'
        try:
            self.connect()
            cursor = self.conn.cursor()
            for order, item_id in enumerate(item_ids, 1):
                cursor.execute(f'UPDATE {table} SET pin_order = ? WHERE id = ?', (order, item_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error reordering pinned items: {e}")
        finally:
            self.close()

    # ==================== 鏀惰棌澶规搷浣?====================
    
    def add_favorite(self, path, name=None):
        """娣诲姞鏀惰棌澶?""
        if name is None:
            name = os.path.basename(path) or path
        
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT MAX(sort_order) FROM favorites')
            max_order = cursor.fetchone()[0]
            sort_order = (max_order or 0) + 1
            
            cursor.execute('''
                INSERT INTO favorites (name, path, sort_order, created_at)
                VALUES (?, ?, ?, ?)
            ''', (name, path, sort_order, time.time()))
            
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding favorite: {e}")
            return None
        finally:
            self.close()
    
    def remove_favorite(self, path_or_id):
        """鍒犻櫎鏀惰棌澶?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            
            if isinstance(path_or_id, int):
                cursor.execute('DELETE FROM favorites WHERE id = ?', (path_or_id,))
            else:
                cursor.execute('DELETE FROM favorites WHERE path = ?', (path_or_id,))
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error removing favorite: {e}")
        finally:
            self.close()
    
    def get_all_favorites(self):
        """鑾峰彇鎵€鏈夋敹钘忓す"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM favorites ORDER BY sort_order')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting favorites: {e}")
            return []
        finally:
            self.close()
    
    def get_favorites(self):
        """鑾峰彇鎵€鏈夋敹钘忓す (鍒悕)"""
        return self.get_all_favorites()
    
    def reorder_favorites(self, favorite_ids):
        """閲嶆柊鎺掑簭鏀惰棌澶?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            for order, fav_id in enumerate(favorite_ids, 1):
                cursor.execute('UPDATE favorites SET sort_order = ? WHERE id = ?', (order, fav_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error reordering favorites: {e}")
        finally:
            self.close()

    # ==================== 闆嗗悎鎿嶄綔 ====================
    
    def create_collection(self, name, description="", is_smart=False, smart_criteria=None):
        """鍒涘缓闆嗗悎"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            now = time.time()
            cursor.execute('''
                INSERT INTO collections (name, description, is_smart, smart_criteria, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, description, 1 if is_smart else 0, smart_criteria, now, now))
            
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return None
        finally:
            self.close()
    
    def add_file_to_collection(self, file_id, collection_id):
        """灏嗘枃浠舵坊鍔犲埌闆嗗悎"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO file_collections (file_id, collection_id, added_at)
                VALUES (?, ?, ?)
            ''', (file_id, collection_id, time.time()))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding file to collection: {e}")
        finally:
            self.close()
    
    def get_files_in_collection(self, collection_id):
        """鑾峰彇闆嗗悎涓殑鎵€鏈夋枃浠?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM files f
                JOIN file_collections fc ON f.id = fc.file_id
                WHERE fc.collection_id = ?
                ORDER BY f.is_pinned DESC, f.pin_order, fc.added_at DESC
            ''', (collection_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files in collection: {e}")
            return []
        finally:
            self.close()
    
    def get_all_collections(self):
        """鑾峰彇鎵€鏈夐泦鍚?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM collections ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting collections: {e}")
            return []
        finally:
            self.close()

    # ==================== 鏂囦欢澶规搷浣滐紙澧炲己鐗堬級====================
    
    def upsert_folder(self, path, recursive=False):
        """
        鎻掑叆鎴栨洿鏂版枃浠跺す淇℃伅锛堝寮虹増锛?        
        Args:
            path: 鏂囦欢澶硅矾寰?            recursive: 鏄惁閫掑綊鎵弿瀛愭枃浠跺拰瀛愭枃浠跺す
        
        Returns:
            folder_id or None
        """
        if not os.path.exists(path) or not os.path.isdir(path):
            return None
        
        name = os.path.basename(path) or path
        parent_path = os.path.dirname(path)

        try:
            self.connect()
            cursor = self.conn.cursor()
            parent_id = self._get_folder_id_by_path(parent_path) if parent_path != path else None
            stat = os.stat(path)
            created_time = stat.st_ctime
            modified_time = stat.st_mtime
            
            self.connect()
            cursor = self.conn.cursor()
            
            # 璁＄畻瀛愭枃浠舵暟鍜屽瓙鏂囦欢澶规暟
            children_file_count = 0
            children_folder_count = 0
            
            if recursive:
                # 閫掑綊鎵弿瀛愰」
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path):
                            children_file_count += 1
                            # 閫掑綊鎻掑叆鏂囦欢
                            self.upsert_file(item_path)
                        elif os.path.isdir(item_path):
                            children_folder_count += 1
                            # 閫掑綊鎻掑叆瀛愭枃浠跺す
                            self.upsert_folder(item_path, recursive=True)
                    except (PermissionError, OSError):
                        continue
            else:
                # 鍙粺璁℃暟閲忥紝涓嶆彃鍏?                try:
                    for item in os.listdir(path):
                        item_path = os.path.join(path, item)
                        if os.path.isfile(item_path):
                            children_file_count += 1
                        elif os.path.isdir(item_path):
                            children_folder_count += 1
                except (PermissionError, OSError):
                    pass
            
            cursor.execute('''
                INSERT INTO folders (
                    path, parent_id, name,
                    created_time, modified_time, 
                    children_file_count, children_folder_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    parent_id=excluded.parent_id,
                    modified_time=excluded.modified_time,
                    children_file_count=excluded.children_file_count,
                    children_folder_count=excluded.children_folder_count
            ''', (path, parent_id, name,
                  created_time, modified_time,
                  children_file_count, children_folder_count))
            
            folder_id = cursor.lastrowid if cursor.lastrowid else self._get_folder_id_by_path(path)
            self.conn.commit()
            return folder_id
        except Exception as e:
            logger.error(f"Error upserting folder: {e}", exc_info=True)
            return None
        finally:
            self.close()
    
    def _get_folder_id_by_path(self, path):
        """鏍规嵁璺緞鑾峰彇鏂囦欢澶笽D锛堝唴閮ㄦ柟娉曪級"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM folders WHERE path = ?', (path,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def update_folder_children_count(self, folder_id):
        """鏇存柊鏂囦欢澶圭殑瀛愰」璁℃暟锛堟墜鍔ㄨЕ鍙戯級"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            
            # 鑾峰彇鏂囦欢澶硅矾寰?            cursor.execute('SELECT path FROM folders WHERE id = ?', (folder_id,))
            row = cursor.fetchone()
            if not row:
                return
            
            folder_path = row[0]
            
            # 缁熻瀛愭枃浠?            cursor.execute('''
                SELECT COUNT(*) FROM files 
                WHERE path LIKE ? AND path NOT LIKE ?
            ''', (folder_path + os.sep + '%', folder_path + os.sep + '%' + os.sep + '%'))
            children_file_count = cursor.fetchone()[0]
            
            # 缁熻瀛愭枃浠跺す
            cursor.execute('''
                SELECT COUNT(*) FROM folders 
                WHERE parent_id = ?
            ''', (folder_id,))
            children_folder_count = cursor.fetchone()[0]
            
            # 鏇存柊
            cursor.execute('''
                UPDATE folders 
                SET children_file_count = ?, children_folder_count = ?
                WHERE id = ?
            ''', (children_file_count, children_folder_count, folder_id))
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating folder children count: {e}")
        finally:
            self.close()
    
    def get_folder_by_path(self, path):
        """鏍规嵁璺緞鑾峰彇鏂囦欢澶?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM folders WHERE path = ?', (path,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting folder: {e}")
            return None
        finally:
            self.close()
    
    def get_files_in_folder(self, folder_path):
        """鑾峰彇鏂囦欢澶逛腑鐨勬墍鏈夌洿鎺ュ瓙鏂囦欢锛堜笉鍖呮嫭瀛愭枃浠跺す涓殑锛?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            folder_path_pattern = folder_path.rstrip(os.sep) + os.sep
            cursor.execute('''
                SELECT * FROM files 
                WHERE path LIKE ? AND path NOT LIKE ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (folder_path_pattern + '%', folder_path_pattern + '%' + os.sep + '%'))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting files in folder: {e}")
            return []
        finally:
            self.close()
    
    
    def get_all_folders(self):
        """鑾峰彇鎵€鏈夋枃浠跺す"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM folders ORDER BY is_pinned DESC, pin_order, name')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all folders: {e}")
            return []
        finally:
            self.close()

    # ==================== 鎼滅储鎿嶄綔 ====================
    
    def search_files_by_name(self, keyword):
        """鎸夋枃浠跺悕鎼滅储鏂囦欢"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files 
                WHERE filename LIKE ? OR path LIKE ?
                ORDER BY is_pinned DESC, pin_order, filename
            ''', (f'%{keyword}%', f'%{keyword}%'))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error searching files by name: {e}")
            return []
        finally:
            self.close()
    
    def search_files_by_tag_name(self, tag_name):
        """鎸夋爣绛惧悕鎼滅储鏂囦欢"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT f.* 
                FROM files f
                JOIN file_tags ft ON f.id = ft.file_id
                JOIN tags t ON ft.tag_id = t.id
                WHERE t.name LIKE ?
                ORDER BY f.is_pinned DESC, f.pin_order, f.filename
            ''', (f'%{tag_name}%',))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error searching files by tag name: {e}")
            return []
        finally:
            self.close()
    
    def remove_file_tag(self, file_id, tag_id):
        """绉婚櫎鏂囦欢鐨勬爣绛惧叧鑱?""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error removing file tag: {e}")
        finally:
            self.close()
    
    def remove_folder_tag(self, folder_id, tag_id):
        """绉婚櫎鏂囦欢澶圭殑鏍囩鍏宠仈"""
        try:
            self.connect()
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM folder_tags WHERE folder_id = ? AND tag_id = ?', (folder_id, tag_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error removing folder tag: {e}")
        finally:
            self.close()
    
    def delete_file(self, file_id):
        """鍒犻櫎鏂囦欢璁板綍"""
        self.connect()
        cursor = self.get_cursor()
        try:
            cursor.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
            cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"鍒犻櫎鏂囦欢澶辫触: {e}")
            return False
        finally:
            self.close()

    def get_files_recursive(self, folder_path):
        """閫掑綊鑾峰彇鏂囦欢澶逛笅鐨勬墍鏈夋枃浠讹紙鍩轰簬鏁版嵁搴擄級"""
        try:
            self.connect()
            cursor = self.get_cursor()
            folder_path = os.path.normpath(folder_path)
            # 纭繚璺緞浠ュ垎闅旂缁撳熬
            if not folder_path.endswith(os.sep):
                folder_path += os.sep
            
            # 浣跨敤 LIKE 鏌ヨ鍖归厤瀛愯矾寰?            query = "SELECT * FROM files WHERE path LIKE ? ORDER BY filename"
            cursor.execute(query, (f"{folder_path}%",))
            
            columns = [description[0] for description in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        except Exception as e:
            logger.error(f"Error getting files recursively: {e}")
            return []
        finally:
            self.close()

    def get_folders_recursive(self, folder_path):
        """閫掑綊鑾峰彇鏂囦欢澶逛笅鐨勬墍鏈夊瓙鏂囦欢澶癸紙鍩轰簬鏁版嵁搴擄級"""
        try:
            self.connect()
            cursor = self.get_cursor()
            folder_path = os.path.normpath(folder_path)
            if not folder_path.endswith(os.sep):
                folder_path += os.sep
                
            query = "SELECT * FROM folders WHERE path LIKE ? ORDER BY name"
            cursor.execute(query, (f"{folder_path}%",))
            
            columns = [description[0] for description in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        except Exception as e:
            logger.error(f"Error getting folders recursively: {e}")
            return []
        finally:
            self.close()


# ===================|===================
# 文件名: db_migration.py
"""
鏁版嵁搴撹縼绉昏剼鏈?- 涓ユ牸閬靛惊鐢ㄦ埛瑕佹眰鐨?涓€绛夊叕姘?鏋舵瀯
"""
import sqlite3
import os
import sys

# 璁剧疆鎺у埗鍙扮紪鐮佷负 UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = "file_manager.db"

def migrate_database():
    """鎵ц鏁版嵁搴撻噸鏋勮縼绉?""
    print("寮€濮嬫暟鎹簱閲嶆瀯 (Strict Schema)...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. 閲嶅懡鍚嶆棫琛?(濡傛灉瀛樺湪) 浠ヤ究澶囦唤鏁版嵁 (鍙€夛紝杩欓噷涓轰簡寮哄埗涓€鑷存€э紝鎴戜滑鍏堝皾璇曚繚鐣欐暟鎹紝浣嗙粨鏋勫彉鍖栬緝澶?
        # 涓虹畝鍗曡捣瑙佸拰纭繚缁撴瀯姝ｇ‘锛屾垜浠厛鍒涘缓鏂拌〃锛屾棫鏁版嵁杩佺Щ閫昏緫姣旇緝澶嶆潅锛?
        # 杩欓噷鎴戜滑鍋囪鐢ㄦ埛鎺ュ彈閲嶅缓绱㈠紩(鍥犱负鏄?浠庨浂鏋勫缓"鐨勬彁绀鸿瘝)锛屾垨鑰呮垜浠皾璇曚繚鐣欓儴鍒嗘暟鎹€?
        # 閴翠簬鐢ㄦ埛瑕佹眰"浠庨浂鏋勫缓"鐨勮摑鍥撅紝鎴戜滑浼樺厛淇濊瘉缁撴瀯姝ｇ‘銆?
        
        # 鍚敤澶栭敭鏀寔
        cursor.execute("PRAGMA foreign_keys = ON")

        # --- Files Table ---
        # 瀛楁: id, path, filename, extension, rating, label_color, is_pinned, created_time, modified_time, size, access_count
        # 娉ㄦ剰: tags 鏄€氳繃鍏宠仈琛ㄥ疄鐜扮殑
        print("閰嶇疆 files 琛?..")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                extension TEXT,
                rating INTEGER DEFAULT 0,
                label_color TEXT,
                is_pinned INTEGER DEFAULT 0,
                created_time REAL,
                modified_time REAL,
                size INTEGER,
                access_count INTEGER DEFAULT 0,
                folder_id INTEGER -- 涓轰簡鏂逛究鏌ヨ鐖跺瓙鍏崇郴锛屼繚鐣?folder_id (瀵瑰簲 parent_id 姒傚康)
            )
        ''')

        # --- Folders Table ---
        # 瀛楁: id, path, name, parent_id, rating, label_color, is_pinned, created_time, modified_time, children_file_count, children_folder_count
        print("閰嶇疆 folders 琛?..")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                parent_id INTEGER,
                rating INTEGER DEFAULT 0,
                label_color TEXT,
                is_pinned INTEGER DEFAULT 0,
                created_time REAL,
                modified_time REAL,
                children_file_count INTEGER DEFAULT 0,
                children_folder_count INTEGER DEFAULT 0
            )
        ''')

        # --- Tags Table (Shared) ---
        print("閰嶇疆 tags 琛?..")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT DEFAULT '#FFFFFF'
            )
        ''')

        # --- File Tags Relation ---
        print("閰嶇疆 file_tags 琛?..")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (file_id, tag_id),
                FOREIGN KEY (file_id) REFERENCES files_new(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        ''')

        # --- Folder Tags Relation ---
        print("閰嶇疆 folder_tags 琛?..")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folder_tags (
                folder_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (folder_id, tag_id),
                FOREIGN KEY (folder_id) REFERENCES folders_new(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        ''')
        
        # --- Metadata Table (淇濈暀鐢ㄤ簬瀛樺偍棰濆淇℃伅濡侲XIF) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                file_id INTEGER PRIMARY KEY,
                width INTEGER,
                height INTEGER,
                duration REAL,
                exif_data TEXT,
                keywords TEXT,
                title TEXT,
                author TEXT,
                copyright TEXT,
                FOREIGN KEY (file_id) REFERENCES files_new(id) ON DELETE CASCADE
            )
        ''')

        # --- Favorites Table (淇濈暀) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at REAL
            )
        ''')

        # --- Collections Table (淇濈暀) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                is_smart INTEGER DEFAULT 0,
                smart_criteria TEXT,
                color TEXT DEFAULT '#FFFFFF',
                created_at REAL,
                updated_at REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_collections (
                file_id INTEGER,
                collection_id INTEGER,
                added_at REAL,
                PRIMARY KEY (file_id, collection_id),
                FOREIGN KEY (file_id) REFERENCES files_new(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
        ''')

        # 杩佺Щ鏁版嵁 (濡傛灉鏃ц〃瀛樺湪)
        # 杩欓噷鍋氫竴涓畝鍗曠殑灏濊瘯锛氬鏋?files 琛ㄥ瓨鍦紝灏濊瘯杩佺Щ鏁版嵁鍒?files_new
        # 杩欐槸涓€涓牬鍧忔€ф搷浣滐紝浣嗕负浜嗘弧瓒虫柊鏋舵瀯鏄繀椤荤殑
        
        # 妫€鏌ユ棫琛ㄦ槸鍚﹀瓨鍦?
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='files'")
        if cursor.fetchone():
            print("杩佺Щ鏃?files 鏁版嵁...")
            # 灏濊瘯灏藉彲鑳藉尮閰嶅瓧娈?
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO files_new (path, filename, size, created_time, modified_time, rating, label_color, is_pinned)
                    SELECT path, filename, size, mtime, mtime, rating, label_color, is_pinned FROM files
                ''')
            except Exception as e:
                print(f"閮ㄥ垎鏁版嵁杩佺Щ澶辫触 (files): {e}")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='folders'")
        if cursor.fetchone():
            print("杩佺Щ鏃?folders 鏁版嵁...")
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO folders_new (path, name, parent_path, created_time, modified_time, label_color, is_pinned)
                    SELECT path, name, parent_path, last_scanned, last_scanned, NULL, 0 FROM folders
                ''')
                # 娉ㄦ剰: parent_path 闇€瑕佽浆鎹负 parent_id锛岃繖闇€瑕佸悗缁鐞嗭紝鎴栬€呮垜浠湪鏂拌〃閲屾殏鏃朵繚鐣?parent_path 瀛楁鐢ㄤ簬杈呭姪
            except Exception as e:
                print(f"閮ㄥ垎鏁版嵁杩佺Щ澶辫触 (folders): {e}")

        # 鏇挎崲琛?
        print("搴旂敤鏂版灦鏋?..")
        cursor.execute("DROP TABLE IF EXISTS files")
        cursor.execute("ALTER TABLE files_new RENAME TO files")
        
        cursor.execute("DROP TABLE IF EXISTS folders")
        cursor.execute("ALTER TABLE folders_new RENAME TO folders")
        
        # 鍒涘缓绱㈠紩
        print("鍒涘缓绱㈠紩...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_rating ON files(rating)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_label_color ON files(label_color)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_is_pinned ON files(is_pinned)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension)')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_path ON folders(path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_parent_id ON folders(parent_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_rating ON folders(rating)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_folders_is_pinned ON folders(is_pinned)')

        conn.commit()
        print("[SUCCESS] 鏁版嵁搴撻噸鏋勫畬鎴愶紒")
        
    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] 閲嶆瀯澶辫触: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()


# ===================|===================
# 文件名: draggable_favorites.py
"""
鍙嫋鎷界殑鏀惰棌澶归潰鏉?
鏀寔锛?
- 鏄剧ず鏀惰棌澶瑰垪琛?
- 鎷栨嫿鏂囦欢/鏂囦欢澶规坊鍔犳敹钘?
- 鍐呴儴鎷栨嫿鎺掑簭
- 鍙抽敭鑿滃崟鎿嶄綔
"""
import os
from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QMenu, QMessageBox, 
                             QInputDialog, QAbstractItemView, QFileIconProvider)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QMimeData, QFileInfo
from PyQt6.QtGui import QIcon, QDrag, QAction

from logger import get_logger

logger = get_logger("FavoritesPanel")

class DraggableFavoritesPanel(QListWidget):
    favorite_clicked = pyqtSignal(str)  # path
    
    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        self.icon_provider = QFileIconProvider()
        
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        
        # 鏍峰紡
        self.setStyleSheet("""
            QListWidget {
                background-color: #2b2b2b;
                border: none;
                color: #ddd;
            }
            QListWidget::item {
                padding: 5px;
                border-radius: 3px;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
            QListWidget::item:selected {
                background-color: #4a4a4a;
                color: white;
            }
        """)
        
        self.itemClicked.connect(self._on_item_clicked)
        self.refresh_favorites()

    def refresh_favorites(self):
        """鍒锋柊鏀惰棌澶瑰垪琛?""
        self.clear()
        favorites = self.db.get_all_favorites()
        for fav in favorites:
            item = QListWidgetItem(fav['name'])
            item.setData(Qt.ItemDataRole.UserRole, fav)
            
            # 鑾峰彇绯荤粺鍥炬爣
            path = fav['path']
            if os.path.exists(path):
                icon = self.icon_provider.icon(QFileInfo(path))
                item.setIcon(icon)
            else:
                # 璺緞涓嶅瓨鍦ㄦ椂鐨勯粯璁ゅ浘鏍?
                item.setIcon(QIcon("assets/folder_error.png")) 
            
            self.addItem(item)

    def _on_item_clicked(self, item):
        """鐐瑰嚮鏀惰棌椤?""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and 'path' in data:
            self.favorite_clicked.emit(data['path'])

    # ================= 鎷栨嫿鏀寔 =================
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # 澶栭儴鏂囦欢鎷栧叆 -> 娣诲姞鏀惰棌
            urls = event.mimeData().urls()
            for url in urls:
                path = url.toLocalFile()
                if os.path.exists(path):
                    self.add_favorite(path)
            event.accept()
        elif event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            # 鍐呴儴鎺掑簭
            super().dropEvent(event)
            self._save_order()
        else:
             event.ignore()

    def _save_order(self):
        """淇濆瓨鏂扮殑椤哄簭"""
        fav_ids = []
        for i in range(self.count()):
            item = self.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                fav_ids.append(data['id'])
        
        if fav_ids:
            self.db.reorder_favorites(fav_ids)

    def add_favorite(self, path):
        """娣诲姞鏀惰棌"""
        if self.db.add_favorite(path):
            self.refresh_favorites()
            logger.info(f"娣诲姞鏀惰棌: {path}")
        else:
            logger.error(f"娣诲姞鏀惰棌澶辫触: {path}")

    # ================= 鍙抽敭鑿滃崟 =================
    
    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if not item:
            # 绌虹櫧澶勫彸閿?
            menu = QMenu(self)
            add_action = QAction("娣诲姞褰撳墠鏂囦欢澶?, self)
            add_action.triggered.connect(self._add_current_folder)
            menu.addAction(add_action)
            menu.exec(event.globalPos())
            return

        # 椤圭洰鍙抽敭
        data = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        
        open_action = QAction("鎵撳紑", self)
        open_action.triggered.connect(lambda: self.favorite_clicked.emit(data['path']))
        menu.addAction(open_action)
        
        rename_action = QAction("閲嶅懡鍚?, self)
        rename_action.triggered.connect(lambda: self._rename_favorite(item))
        menu.addAction(rename_action)
        
        menu.addSeparator()
        
        delete_action = QAction("绉婚櫎", self)
        delete_action.triggered.connect(lambda: self._delete_favorite(item))
        menu.addAction(delete_action)
        
        menu.exec(event.globalPos())

    def _add_current_folder(self):
        # 闇€瑕佽幏鍙栦富绐楀彛鐨勫綋鍓嶈矾寰勶紝杩欓噷鍙互閫氳繃淇″彿鎴栬€?parent 鑾峰彇
        # 绠€鍗曡捣瑙侊紝鎴戜滑鏆備笉鏀寔浠庤繖閲岀洿鎺ヨ幏鍙栧綋鍓嶈矾寰勶紝闄ら潪浼犲叆
        # 鎴栬€呭湪 main.py 涓繛鎺ヤ俊鍙?
        pass 

    def _rename_favorite(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        new_name, ok = QInputDialog.getText(self, "閲嶅懡鍚?, "鏂板悕绉?", text=data['name'])
        if ok and new_name:
            # 闇€瑕佸湪 db_manager 娣诲姞 update_favorite_name
            # 鏆傛椂鍏堝垹闄ゅ啀娣诲姞(浼氫涪澶辨帓搴?锛屾垨鑰呯洿鎺ユ洿鏂版暟鎹簱
            try:
                self.db.connect()
                self.db.conn.execute("UPDATE favorites SET name = ? WHERE id = ?", (new_name, data['id']))
                self.db.conn.commit()
                self.db.close()
                self.refresh_favorites()
            except Exception as e:
                logger.error(f"閲嶅懡鍚嶅け璐? {e}")

    def _delete_favorite(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        # 鐩存帴绉婚櫎锛屼笉璇㈤棶
        self.db.remove_favorite(data['id'])
        self.refresh_favorites()


# ===================|===================
# 文件名: enhanced_file_list.py
from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QWidget, QVBoxLayout, 
                             QLabel, QMenu, QApplication, QAbstractItemView, QFrame, QLineEdit,
                             QStyledItemDelegate)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QUrl, QMimeData
from PyQt6.QtGui import QIcon, QPixmap, QDrag, QAction, QColor, QPainter, QBrush, QPen
import os
import sys
import time
from datetime import datetime
from cache_manager import ThumbnailLoader
from rating_widget import RatingWidget

# 鑷畾涔塂elegate,瀹屽叏涓嶇粯鍒秈tem鑳屾櫙
class NoFocusDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # 瀹屽叏涓嶇粯鍒秈tem,鍙樉绀簑idget
        pass

class FileItemWidget(QWidget):
    rating_changed = pyqtSignal(int)  # 璇勫垎鏀瑰彉淇″彿
    rename_requested = pyqtSignal(str, str) # old_path, new_name
    
    def __init__(self, file_data, cache_manager, parent=None):
        super().__init__(parent)
        self.file_data = file_data
        self.cache = cache_manager
        self.is_selected = False
        self.is_folder = file_data.get('is_folder', False)
        
        self.setup_ui()
        
    def mousePressEvent(self, event):
        """蹇界暐榧犳爣鎸変笅浜嬩欢锛岃QListWidget澶勭悊閫夋嫨"""
        # print(f"FileItemWidget mousePress: {self.file_data.get('filename')}")
        event.ignore()
        
    def mouseDoubleClickEvent(self, event):
        """蹇界暐鍙屽嚮浜嬩欢锛岃QListWidget澶勭悊鎵撳紑"""
        # print(f"FileItemWidget mouseDoubleClick: {self.file_data.get('filename')}")
        event.ignore()
        
    def setup_ui(self):
        self.setFixedSize(160, 210)  # 鍥哄畾澶у皬锛岄槻姝㈠竷灞€鎶栧姩鍜屽榻愰棶棰?        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 寮哄埗灞呬腑瀵归綈
        
        # 缂╃暐鍥惧鍣?        self.thumb_container = QLabel()
        self.thumb_container.setObjectName("thumb_container") # 璁剧疆瀵硅薄鍚嶄互闃叉鏍峰紡缁ф壙
        self.thumb_container.setFixedSize(140, 140)
        self.thumb_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_container.setStyleSheet("#thumb_container { background-color: transparent; border-radius: 5px; }")
        
        # 缂╃暐鍥?        self.thumb_label = QLabel(self.thumb_container)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 榛樿鍥炬爣
        if self.is_folder:
            self.thumb_label.setText("馃搧")
            self.thumb_label.setStyleSheet("font-size: 48px; color: #888;")
        else:
            self.thumb_label.setText("馃搫")
            self.thumb_label.setStyleSheet("font-size: 48px; color: #888;")
            
        layout.addWidget(self.thumb_container, 0, Qt.AlignmentFlag.AlignCenter)
        
        # === 鎮诞/鐘舵€佸浘鏍囧眰 (Overlay) ===
        # 缃《鍥炬爣
        self.pin_label = QLabel("馃搶", self.thumb_container)
        self.pin_label.setStyleSheet("font-size: 16px; background: transparent;")
        # Move to top-right corner (container is 140x140)
        self.pin_label.move(115, 0) 
        self.pin_label.hide()
        
        # 鏂囦欢澶瑰瓙椤硅鏁?        self.count_label = QLabel("", self.thumb_container)
        self.count_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 150);
            color: white;
            font-size: 10px;
            padding: 2px 5px;
            border-radius: 8px;
        """)
        self.count_label.hide()
        
        # 绫诲瀷鏍囪瘑 (鏂囦欢澶规樉绀?FOLDER",鏂囦欢鏄剧ず鎵╁睍鍚?
        if self.is_folder:
            type_badge = QLabel("FOLDER", self.thumb_container)
            type_badge.setStyleSheet("""
                background-color: rgba(0, 0, 0, 150);
                color: white;
                font-size: 10px;
                padding: 2px 4px;
                border-bottom-right-radius: 4px;
            """)
            type_badge.move(0, 0)
            type_badge.show()
        else:
            # 鏄剧ず鏂囦欢鎵╁睍鍚?            extension = self.file_data.get('extension', '')
            if extension:
                ext_badge = QLabel(extension.upper().lstrip('.'), self.thumb_container)
                ext_badge.setStyleSheet("""
                    background-color: rgba(42, 130, 218, 180);
                    color: white;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 2px 4px;
                    border-bottom-right-radius: 4px;
                """)
                ext_badge.adjustSize()
                ext_badge.move(0, 0)
                ext_badge.show()
        
        # 鏄熺骇璇勫垎 (濮嬬粓鏄剧ず,鍙偣鍑?
        self.rating_widget = RatingWidget(self.file_data.get('rating', 0))
        self.rating_widget.rating_changed.connect(self._on_rating_clicked)
        layout.addWidget(self.rating_widget, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 鏂囦欢鍚?        filename = self.file_data.get('filename', '')
        if not filename and 'path' in self.file_data:
            filename = os.path.basename(self.file_data['path'])
            
        self.name_label = QLabel(filename)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("color: #ccc; font-size: 12px;")
        self.name_label.setFixedWidth(150) # 鍥哄畾瀹藉害锛岀暐灏忎簬 widget 瀹藉害
        self.name_label.setFixedHeight(35)
        layout.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 鏇存柊棰滆壊鍜岀姸鎬?        self.update_color_display()
        self.update_status_icons()

    def set_size(self, size):
        """鍔ㄦ€佽皟鏁村ぇ灏?""
        self.setFixedSize(size, size + 50)
        thumb_size = size - 20
        self.thumb_container.setFixedSize(thumb_size, thumb_size)
        
        # Update pin position (Top-Right)
        self.pin_label.move(thumb_size - 25, 0)
        
        # Update badges
        # Count label (Bottom-Right)
        self.count_label.move(thumb_size - self.count_label.width() - 5, 
                              thumb_size - self.count_label.height() - 5)
                              
        # Name label width
        self.name_label.setFixedWidth(size - 10)

    def start_rename(self):
        """寮€濮嬮噸鍛藉悕"""
        self.name_label.hide()
        self.rename_edit = QLineEdit(self.name_label.text(), self)
        self.rename_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rename_edit.setStyleSheet("background-color: #333; color: white; border: 1px solid #0078d7;")
        self.rename_edit.setFixedWidth(self.width() - 10)
        self.rename_edit.move(5, self.height() - 40)
        self.rename_edit.show()
        self.rename_edit.setFocus()
        self.rename_edit.selectAll()
        self.rename_edit.returnPressed.connect(self.finish_rename)
        self.rename_edit.focusOutEvent = self._on_rename_focus_out

    def _on_rename_focus_out(self, event):
        """澶卞幓鐒︾偣鏃跺彇娑堟垨鎻愪氦 (杩欓噷閫夋嫨鎻愪氦)"""
        self.finish_rename()
        QLineEdit.focusOutEvent(self.rename_edit, event)

    def finish_rename(self):
        """瀹屾垚閲嶅懡鍚?""
        if hasattr(self, 'rename_edit') and self.rename_edit:
            new_name = self.rename_edit.text().strip()
            if new_name and new_name != self.name_label.text():
                self.rename_requested.emit(self.file_data['path'], new_name)
                self.name_label.setText(new_name)
            
            self.rename_edit.deleteLater()
            self.rename_edit = None
            self.name_label.show()

    def update_status_icons(self):
        """鏇存柊缃《銆佽鏁扮瓑鐘舵€佸浘鏍?""
        # 缃《
        if self.file_data.get('is_pinned'):
            self.pin_label.show()
        else:
            self.pin_label.hide()
            
        # 鏂囦欢澶硅鏁?        if self.is_folder:
            file_count = self.file_data.get('children_file_count', 0)
            folder_count = self.file_data.get('children_folder_count', 0)
            total = file_count + folder_count
            if total > 0:
                self.count_label.setText(f"{total}")
                self.count_label.adjustSize()
                # 鍙充笅瑙掑畾浣?                self.count_label.move(self.thumb_container.width() - self.count_label.width() - 5, 
                                      self.thumb_container.height() - self.count_label.height() - 5)
                self.count_label.show()
            else:
                self.count_label.hide()
    
    def _on_rating_clicked(self, rating):
        """鏄熺骇琚偣鍑?""
        self.file_data['rating'] = rating
        self.rating_changed.emit(rating)

    def update_rating_display(self):
        """鏇存柊璇勫垎鏄剧ず"""
        rating = self.file_data.get('rating', 0)
        self.rating_widget.set_rating(rating)

    def update_color_display(self):
        """鏇存柊鏍峰紡锛氳竟妗嗐€佹槦绾ч鑹层€佹枃浠跺悕鑳屾櫙"""
        color = self.file_data.get('label_color')
        
        # 1. 缂╃暐鍥惧鍣ㄦ牱寮?        # 閫変腑鏃舵樉绀鸿摑鑹茶竟妗嗭紝鑳屾櫙閫忔槑
        # 浣跨敤 ID 閫夋嫨鍣?#thumb_container 闃叉鏍峰紡缁ф壙鍒板瓙鎺т欢
        if self.is_selected:
            self.thumb_container.setStyleSheet("#thumb_container { background-color: transparent; border: 2px solid #0078d7; border-radius: 5px; }")
        else:
            self.thumb_container.setStyleSheet("#thumb_container { background-color: transparent; border: none; border-radius: 5px; }")
        
        # 2. 鏄熺骇璇勫垎棰滆壊 (濮嬬粓浣跨敤榛樿閲戣壊锛屼笉闅忔爣绛惧彉鑹?
        self.rating_widget.set_color(None)

        # 3. 鏂囦欢鍚嶆牱寮?(棰滆壊鏍囩搴旂敤鍦ㄦ)
        if color and color != 'none':
            # 鏈夐鑹叉爣绛? 鑳屾櫙鑹蹭负鏍囩鑹?            # 绠€鍗曞垽鏂粦鑹叉枃瀛楃殑鎯呭喌 (榛勮壊)
            text_color = "black" if color in ['yellow', '#FFD700', '#FFFF00'] else "white"
            font_weight = "bold" if self.is_selected else "normal"
            
            self.name_label.setStyleSheet(f"""
                background-color: {color}; 
                color: {text_color}; 
                border-radius: 4px; 
                padding: 2px;
                font-size: 12px;
                font-weight: {font_weight};
            """)
        else:
            # 鏃犻鑹叉爣绛? 榛樿鏍峰紡
            if self.is_selected:
                self.name_label.setStyleSheet("background-color: transparent; color: white; font-weight: bold; font-size: 12px;")
            else:
                self.name_label.setStyleSheet("background-color: transparent; color: #ccc; font-size: 12px;")

    def mousePressEvent(self, event):
        """蹇界暐榧犳爣鎸変笅浜嬩欢锛岃QListWidget澶勭悊閫夋嫨"""
        # from logger import get_logger
        # logger = get_logger("FileItem")
        # logger.debug(f"FileItemWidget mousePress: {self.file_data.get('filename')}")
        event.ignore()
        
    def mouseDoubleClickEvent(self, event):
        """蹇界暐鍙屽嚮浜嬩欢锛岃QListWidget澶勭悊鎵撳紑"""
        event.ignore()

    def set_thumbnail(self, pixmap):
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(130, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.thumb_label.setPixmap(scaled)
            self.thumb_label.setText("") # Clear text
            self.thumb_label.adjustSize()
            # Center in container
            x = (140 - scaled.width()) // 2
            y = (140 - scaled.height()) // 2
            self.thumb_label.move(x, y)

    def set_selected(self, selected):
        self.is_selected = selected
        self.update_color_display() # 缁熶竴鏇存柊鏍峰紡

class EnhancedFileListWidget(QListWidget):
    item_clicked = pyqtSignal(str) # Path
    selection_changed = pyqtSignal(list) # List of paths
    go_up_requested = pyqtSignal() # Backspace pressed
    rename_file_requested = pyqtSignal(str, str) # old, new
    
    def __init__(self, cache_manager):
        super().__init__()
        self.cache = cache_manager
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        # 鍏抽敭淇锛氳缃浐瀹氱殑缃戞牸澶у皬锛岄槻姝㈠竷灞€姝诲惊鐜拰闂€€
        self.setGridSize(QSize(180, 230)) 
        self.setSpacing(10)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True) # 鍚敤鎷栨嫿
        self.setIconSize(QSize(160, 210)) 
        
        # 浼樺寲鏍峰紡锛岀‘淇濆眳涓?        self.setStyleSheet("""
            QListWidget {
                background-color: #222;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background-color: transparent;
                border: none;
                border-radius: 5px;
                /* 纭繚椤圭洰鍦ㄧ綉鏍间腑灞呬腑 */
                padding: 5px; 
            }
            QListWidget::item:selected {
                background-color: transparent; /* 鐢?widget 澶勭悊閫変腑鏍峰紡 */
                border: none; /* 涓嶆樉绀鸿竟妗?*/
                outline: none;
            }
            QListWidget::item:focus {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
        """)
        
        # 浣跨敤鑷畾涔塪elegate绂佺敤鐒︾偣鐭╁舰
        self.setItemDelegate(NoFocusDelegate(self))
        
        # 鍙屽嚮鎵撳紑鏂囦欢/鏂囦欢澶?        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        
        # 鍒濆鍖栫缉鐣ュ浘鍔犺浇鍣?(鍗曚緥)
        self.loader_thread = ThumbnailLoader(self.cache)
        self.loader_thread.thumbnail_ready.connect(self.update_thumbnail)
        self.loader_thread.start()
        
        # 缂╂斁鐩稿叧
        self.current_icon_size = 160  # 褰撳墠鍥炬爣澶у皬
        self.current_grid_size = 180  # 褰撳墠缃戞牸澶у皬
        
        # 棰勮绐楀彛
        self.preview_dialog = None

    def mousePressEvent(self, event):
        """璋冭瘯榧犳爣鎸変笅浜嬩欢"""
        # item = self.itemAt(event.pos())
        # print(f"ListWidget mousePress at {event.pos()}, item: {item}")
        super().mousePressEvent(event)

    def closeEvent(self, event):
        """鍏抽棴鏃跺仠姝㈢嚎绋?""
        if hasattr(self, 'loader_thread'):
            self.loader_thread.stop()
        super().closeEvent(event)

    def wheelEvent(self, event):
        """澶勭悊榧犳爣婊氳疆浜嬩欢 - Ctrl+婊氳疆缂╂斁"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+婊氳疆锛氱缉鏀?            delta = event.angleDelta().y()
            if delta > 0:
                self.current_icon_size = min(self.current_icon_size + 10, 300)
            else:
                self.current_icon_size = max(self.current_icon_size - 10, 80)
            
            # 鏇存柊缃戞牸澶у皬
            self.setGridSize(QSize(self.current_icon_size + 20, self.current_icon_size + 70))
            self.setIconSize(QSize(self.current_icon_size, self.current_icon_size + 50))
            
            # 鏇存柊鎵€鏈?ItemWidget 鐨勫ぇ灏?            for i in range(self.count()):
                item = self.item(i)
                item.setSizeHint(QSize(self.current_icon_size, self.current_icon_size + 50))
                widget = self.itemWidget(item)
                if widget:
                    widget.set_size(self.current_icon_size)
            
            event.accept()
        else:
            # 姝ｅ父婊氬姩
            super().wheelEvent(event)
    
    def keyPressEvent(self, event):
        """澶勭悊閿洏浜嬩欢"""
        if event.key() == Qt.Key.Key_Space:
            # 绌烘牸閿細鍒囨崲棰勮
            if self.preview_dialog and self.preview_dialog.isVisible():
                self.preview_dialog.close()
            else:
                selected_items = self.selectedItems()
                if len(selected_items) == 1:
                    item = selected_items[0]
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                    if not is_folder:
                        path = file_data.get('path', '')
                        self._show_preview(path)
            event.accept()
            return

        elif event.key() == Qt.Key.Key_Backspace:
            # 閫€鏍奸敭锛氳繑鍥炰笂涓€绾?            self.go_up_requested.emit()
            event.accept()
            return
            
        elif event.key() == Qt.Key.Key_F2 or event.key() == Qt.Key.Key_Return:
            # F2 鎴?鍥炶溅锛氶噸鍛藉悕
            selected_items = self.selectedItems()
            if len(selected_items) == 1:
                widget = self.itemWidget(selected_items[0])
                if widget:
                    widget.start_rename()
            event.accept()
            return
        
        super().keyPressEvent(event)
    
    def _show_preview(self, path):
        """鏄剧ず鏂囦欢棰勮"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QScrollArea
        
        if not os.path.exists(path):
            return
        
        ext = os.path.splitext(path)[1].lower()
        
        # 鍥剧墖棰勮
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            self._show_image_preview(path)
        # 鏂囨湰棰勮/缂栬緫
        elif ext in ['.txt', '.md', '.log', '.json', '.xml', '.py', '.js', '.css', '.html']:
            self._show_text_preview(path)
    
    def _show_image_preview(self, path):
        """鏄剧ず鍥剧墖棰勮"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
        
        if self.preview_dialog:
            self.preview_dialog.close()
        
        self.preview_dialog = QDialog(self)
        self.preview_dialog.setWindowTitle(f"棰勮: {os.path.basename(path)}")
        self.preview_dialog.resize(800, 600)
        
        layout = QVBoxLayout(self.preview_dialog)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        label = QLabel()
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            label.setText("鏃犳硶鍔犺浇鍥剧墖")
        
        scroll.setWidget(label)
        layout.addWidget(scroll)
        
        self.preview_dialog.show()
    
    def _show_text_preview(self, path):
        """鏄剧ず鏂囨湰棰勮/缂栬緫"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QMessageBox
        
        if self.preview_dialog:
            self.preview_dialog.close()
        
        self.preview_dialog = QDialog(self)
        self.preview_dialog.setWindowTitle(f"缂栬緫: {os.path.basename(path)}")
        self.preview_dialog.resize(800, 600)
        
        layout = QVBoxLayout(self.preview_dialog)
        
        text_edit = QTextEdit()
        text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            text_edit.setPlainText(content)
        except Exception as e:
            text_edit.setPlainText(f"鏃犳硶璇诲彇鏂囦欢: {e}")
            text_edit.setReadOnly(True)
        
        layout.addWidget(text_edit)
        
        # 鎸夐挳
        btn_layout = QHBoxLayout()
        
        save_btn = QPushButton("淇濆瓨")
        save_btn.clicked.connect(lambda: self._save_text(path, text_edit.toPlainText()))
        btn_layout.addWidget(save_btn)
        
        close_btn = QPushButton("鍏抽棴")
        close_btn.clicked.connect(self.preview_dialog.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
        self.preview_dialog.show()
    
    def _save_text(self, path, content):
        """淇濆瓨鏂囨湰鍐呭"""
        from PyQt6.QtWidgets import QMessageBox
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            QMessageBox.information(self, "鎴愬姛", "鏂囦欢宸蹭繚瀛?)
        except Exception as e:
            QMessageBox.warning(self, "閿欒", f"淇濆瓨澶辫触: {e}")
    
    def set_view_mode(self, mode):
        """璁剧疆瑙嗗浘妯″紡"""
        if mode == 'grid':
            self.setViewMode(QListWidget.ViewMode.IconMode)
            self.setGridSize(QSize(self.current_grid_size, self.current_grid_size + 50))
            self.setIconSize(QSize(self.current_icon_size, self.current_icon_size + 50))
        elif mode == 'list':
            self.setViewMode(QListWidget.ViewMode.ListMode)
            self.setGridSize(QSize(-1, -1))  # 鍒楄〃妯″紡涓嬩笉浣跨敤缃戞牸


    def load_files(self, file_data_list):
        """鍔犺浇鏂囦欢鍒楄〃"""
        self.clear()
        
        file_paths = []
        for file_data in file_data_list:
            self._add_item(file_data)
            file_paths.append(file_data['path'])
            
        # 娣诲姞浠诲姟鍒伴槦鍒?        if file_paths:
            self.loader_thread.add_paths(file_paths)

    def append_files(self, files, folders=None):
        """杩藉姞鏂囦欢鍒板垪琛?(鏀寔缃《鎺掑簭: 缃《鏂囦欢澶?-> 缃《鏂囦欢 -> 鏅€氭枃浠跺す -> 鏅€氭枃浠?"""
        t0 = time.time()
        from logger import get_logger
        logger = get_logger("FileList")
        
        file_paths = []
        
        # 1. 鍒嗙被
        pinned_folders = []
        unpinned_folders = []
        if folders:
            for f in folders:
                if f.get('is_pinned'):
                    pinned_folders.append(f)
                else:
                    unpinned_folders.append(f)
                    
        pinned_files = []
        unpinned_files = []
        for f in files:
            # 棰勫鐞嗘墿灞曞悕
            if 'extension' not in f and 'path' in f:
                f['extension'] = os.path.splitext(f['path'])[1]
            
            if f.get('is_pinned'):
                pinned_files.append(f)
            else:
                unpinned_files.append(f)
        
        t1 = time.time()
        
        # 2. 鎸夐『搴忔坊鍔?(绂佺敤鏇存柊浠ユ彁楂樻€ц兘)
        self.setUpdatesEnabled(False)
        try:
            # 缃《鏂囦欢澶?            for f in pinned_folders:
                self._add_item(f, is_folder=True)
                
            # 缃《鏂囦欢
            for f in pinned_files:
                file_paths.append(f['path'])
                self._add_item(f, is_folder=False)
                
            # 鏅€氭枃浠跺す
            for f in unpinned_folders:
                self._add_item(f, is_folder=True)
                
            # 鏅€氭枃浠?            for f in unpinned_files:
                file_paths.append(f['path'])
                self._add_item(f, is_folder=False)
        finally:
            self.setUpdatesEnabled(True)
        
        t2 = time.time()
        # 娣诲姞浠诲姟鍒伴槦鍒?        if file_paths:
            self.loader_thread.add_paths(file_paths)
            
        # 寮哄埗鍒锋柊甯冨眬锛岄槻姝㈠嚭鐜扮┖鐧藉尯鍩?        self.doItemsLayout()
        t3 = time.time()
        logger.debug(f"AppendFiles鑰楁椂: 鍒嗙被={t1-t0:.4f}s, 娣诲姞={t2-t1:.4f}s, 甯冨眬={t3-t2:.4f}s, 鎬昏={t3-t0:.4f}s")

    def _add_item(self, file_data, is_folder=False):
        item = QListWidgetItem(self)
        item.setSizeHint(QSize(160, 210))
        
        # 鍏抽敭淇锛氭纭缃甶tem鐨刦lags锛屼娇鍏跺彲閫夋嫨銆佸彲鎷栨嫿
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled |
            Qt.ItemFlag.ItemIsSelectable |
            Qt.ItemFlag.ItemIsDragEnabled
        )
        
        # Store data in item
        item.setData(Qt.ItemDataRole.UserRole, file_data)
        item.setData(Qt.ItemDataRole.UserRole + 1, is_folder) # Store is_folder
        
        # Create widget
        # 濡傛灉鏄枃浠跺す锛宖ile_data 鍙兘缁撴瀯涓嶅悓锛岄渶瑕侀€傞厤
        if is_folder:
            # 纭繚 file_data 鏈?path 瀛楁
            if 'path' not in file_data: return
            file_data['is_folder'] = True
            
        widget = FileItemWidget(file_data, self.cache)
        widget.rename_requested.connect(lambda p, n: self.rename_file_requested.emit(p, n))
        self.setItemWidget(item, widget)
        
        # 璁剧疆 Item 鏂囨湰浠ヤ究鏀寔閿洏鎼滅储 (Type-to-Select)
        filename = file_data.get('filename', '')
        if not filename and 'path' in file_data:
            filename = os.path.basename(file_data['path'])
        item.setText(filename)
        # 闅愯棌榛樿鏂囨湰鏄剧ず锛屽洜涓烘垜浠湁鑷畾涔?Widget
        item.setForeground(QColor(0,0,0,0))

    def mimeData(self, items):
        """鍒涘缓鎷栨嫿鏁版嵁锛屽寘鍚枃浠惰矾寰?""
        mime = QMimeData()
        urls = []
        for item in items:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and 'path' in data:
                urls.append(QUrl.fromLocalFile(data['path']))
        
        if urls:
            mime.setUrls(urls)
            
        return mime

    def update_thumbnail(self, path, thumb_path):
        """鏇存柊缂╃暐鍥?""
        from logger import get_logger
        logger = get_logger("FileList")
        # logger.debug(f"灏濊瘯鏇存柊缂╃暐鍥? {path} -> {thumb_path}")
        
        try:
            norm_path = os.path.normpath(path).lower()
            
            # Find item with this path
            for i in range(self.count()):
                item = self.item(i)
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and 'path' in data:
                    item_path = os.path.normpath(data['path']).lower()
                    if item_path == norm_path:
                        widget = self.itemWidget(item)
                        if widget:
                            pixmap = QPixmap(thumb_path)
                            if not pixmap.isNull():
                                widget.set_thumbnail(pixmap)
                            else:
                                logger.warning(f"鏃犳硶鍔犺浇缂╃暐鍥? {thumb_path}")
                        else:
                            logger.warning(f"鏈壘鍒皐idget: {path}")
                        break
            else:
                # logger.warning(f"鏈壘鍒板尮閰嶇殑item: {path}")
                pass
        except Exception as e:
            logger.error(f"鏇存柊缂╃暐鍥惧嚭閿? {e}")

    def _on_item_double_clicked(self, item):
        """鍙屽嚮椤圭洰鏃惰Е鍙?""
        data = item.data(Qt.ItemDataRole.UserRole)
        self.item_clicked.emit(data['path'])
        
        # Update selection state visually
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if w: w.set_selected(it.isSelected())

    def _on_selection_changed(self):
        paths = []
        for item in self.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            paths.append(data['path'])
            
        # Update visual state
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            if w: w.set_selected(it.isSelected())
            
        self.selection_changed.emit(paths)

    # Drag and Drop support
    def startDrag(self, supportedActions):
        paths = []
        for item in self.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            paths.append(data['path'])
            
        if paths:
            drag = QDrag(self)
            mime_data = self.mimeData(self.selectedItems())
            
            # Set urls
            urls = [QUrl.fromLocalFile(p) for p in paths]
            mime_data.setUrls(urls)
            
            drag.setMimeData(mime_data)
            
            # Set pixmap
            if len(paths) == 1:
                widget = self.itemWidget(self.selectedItems()[0])
                if widget:
                    drag.setPixmap(widget.thumb_label.pixmap().scaled(64, 64))
            
            drag.exec(supportedActions)

    def apply_filters(self, filters):
        """搴旂敤绛涢€夊櫒 (鏀寔鍒嗛潰绛涢€?"""
        for i in range(self.count()):
            item = self.item(i)
            file_data = item.data(Qt.ItemDataRole.UserRole)
            is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
            
            if is_folder:
                # 鏂囦欢澶归€氬父涓嶈杩囨护锛岄櫎闈炴湁鐗规畩闇€姹?                item.setHidden(False)
                continue
                
            visible = True
            
            # 1. 璇勭骇杩囨护
            if filters['rating']:
                rating = file_data.get('rating', 0)
                if rating not in filters['rating']: visible = False
            
            # 2. 棰滆壊杩囨护
            if visible and filters['color']:
                color = file_data.get('label_color', 'none') or 'none'
                if color not in filters['color']: visible = False
            
            # 3. 鎵╁睍鍚嶈繃婊?            if visible and filters['extensions']:
                ext = file_data.get('extension', '').upper() or "鏃犳墿灞曞悕"
                if ext not in filters['extensions']:
                    visible = False
            
            # 4. 鏃ユ湡杩囨护 (鎸夊ぉ)
            if visible and filters['date']:
                ts = file_data.get('created_time') or file_data.get('ctime')
                if ts:
                    date_str = datetime.fromtimestamp(ts).strftime('%Y/%m/%d')
                    if date_str not in filters['date']: visible = False
                else:
                    visible = False

            # 5. 鏍囩杩囨护 (鏆備笉鏀寔锛屽洜涓?item data 閲屾病鏈?tags)
            # 濡傛灉闇€瑕佹敮鎸侊紝蹇呴』鍦ㄥ姞杞芥枃浠舵椂鎶?tags 鏀捐繘 file_data
            
            item.setHidden(not visible)

    # ================= 鍙抽敭鑿滃崟 =================
    
    def contextMenuEvent(self, event):
        """鍙抽敭鑿滃崟 - 鎵佸钩鍖栫粨鏋勶紝甯哥敤鍔熻兘鍦ㄩ《灞?""
        import subprocess
        import shutil
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        
        item = self.itemAt(event.pos())
        
        # 绌虹櫧澶勫彸閿?        if not item:
            menu = QMenu(self)
            new_folder_action = QAction("馃搧 鏂板缓鏂囦欢澶?, self)
            new_folder_action.triggered.connect(self._create_new_folder)
            menu.addAction(new_folder_action)
            menu.exec(event.globalPos())
            return
        
        # 鑾峰彇閫変腑鐨勯」鐩?        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        # 鍒涘缓鑿滃崟
        menu = QMenu(self)
        
        # === 鎵撳紑 ===
        if len(selected_items) == 1:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
            path = file_data.get('path', '')
            
            if is_folder:
                open_action = QAction("馃搨 鎵撳紑", self)
            else:
                open_action = QAction("馃搫 鎵撳紑", self)
            open_action.triggered.connect(lambda: self._open_file(path))
            menu.addAction(open_action)
            
            menu.addSeparator()
        
        # === 鏄熺骇璇勫垎 (6涓€夐」) ===
        rating_menu = menu.addMenu("猸?璁剧疆鏄熺骇")
        for rating in range(6):
            stars = "鈽? * rating if rating > 0 else "鏃犺瘎鍒?
            rating_action = QAction(f"{stars}", self)
            rating_action.triggered.connect(lambda checked, r=rating: self._set_rating(r))
            rating_menu.addAction(rating_action)
        
        # === 棰滆壊鏍囩 ===
        color_menu = menu.addMenu("馃帹 棰滆壊鏍囩")
        colors = [
            ("绾㈣壊", "red", "#FF0000"),
            ("榛勮壊", "yellow", "#FFD700"),
            ("缁胯壊", "green", "#00FF00"),
            ("钃濊壊", "blue", "#0080FF"),
            ("鏃?, None, "")
        ]
        for color_name, color_value, color_hex in colors:
            if color_hex:
                color_action = QAction(f"鈼?{color_name}", self)
                pixmap = QPixmap(16, 16)
                pixmap.fill(QColor(color_hex))
                color_action.setIcon(QIcon(pixmap))
            else:
                color_action = QAction(f"鈼?{color_name}", self)
            color_action.triggered.connect(lambda checked, c=color_value: self._set_color(c))
            color_menu.addAction(color_action)
        
        # === 鏍囩鎿嶄綔 ===
        tag_menu = menu.addMenu("馃彿锔?鏍囩")
        add_tag_action = QAction("娣诲姞鏍囩...", self)
        add_tag_action.triggered.connect(self._add_tag)
        tag_menu.addAction(add_tag_action)
        
        remove_tag_action = QAction("绉婚櫎鏍囩...", self)
        remove_tag_action.triggered.connect(self._remove_tag)
        tag_menu.addAction(remove_tag_action)
        
        # === 缃《 ===
        pin_action = QAction("馃搶 缃《/鍙栨秷缃《", self)
        pin_action.triggered.connect(self._toggle_pin)
        menu.addAction(pin_action)
        
        menu.addSeparator()
        
        # === 鏂囦欢鎿嶄綔 ===
        copy_action = QAction("馃搵 澶嶅埗", self)
        copy_action.triggered.connect(self._copy_files)
        menu.addAction(copy_action)
        
        # 绉诲姩鍒?- 甯﹀父鐢ㄦ枃浠跺す瀛愯彍鍗?        move_menu = menu.addMenu("鉁傦笍 绉诲姩鍒?)
        self._add_common_folders_to_menu(move_menu, self._move_to_folder)
        move_menu.addSeparator()
        move_other_action = QAction("鍏朵粬浣嶇疆...", self)
        move_other_action.triggered.connect(self._move_to)
        move_menu.addAction(move_other_action)
        
        # 澶嶅埗鍒?- 甯﹀父鐢ㄦ枃浠跺す瀛愯彍鍗?        copy_menu = menu.addMenu("馃搼 澶嶅埗鍒?)
        self._add_common_folders_to_menu(copy_menu, self._copy_to_folder)
        copy_menu.addSeparator()
        copy_other_action = QAction("鍏朵粬浣嶇疆...", self)
        copy_other_action.triggered.connect(self._copy_to)
        copy_menu.addAction(copy_other_action)
        
        menu.addSeparator()
        
        # === 閲嶅懡鍚?===
        if len(selected_items) == 1:
            rename_action = QAction("鉁忥笍 閲嶅懡鍚?, self)
            rename_action.triggered.connect(self._rename_file)
            menu.addAction(rename_action)
        else:
            batch_rename_action = QAction("鉁忥笍 鎵归噺閲嶅懡鍚?..", self)
            batch_rename_action.triggered.connect(self._batch_rename)
            menu.addAction(batch_rename_action)
        
        menu.addSeparator()
        
        # === 璧勬簮绠＄悊鍣?===
        if len(selected_items) == 1:
            show_action = QAction("馃搧 鍦ㄨ祫婧愮鐞嗗櫒涓樉绀?, self)
            show_action.triggered.connect(lambda: self._show_in_explorer(path))
            menu.addAction(show_action)
            
            copy_path_action = QAction("馃搵 澶嶅埗璺緞", self)
            copy_path_action.triggered.connect(lambda: self._copy_path(path))
            menu.addAction(copy_path_action)
            
            menu.addSeparator()
        
        # === 鏀惰棌澶?===
        folders_selected = sum(1 for item in selected_items if item.data(Qt.ItemDataRole.UserRole + 1))
        if folders_selected > 0:
            add_fav_action = QAction("猸?娣诲姞鍒版敹钘忓す", self)
            add_fav_action.triggered.connect(self._add_selected_to_favorites)
            menu.addAction(add_fav_action)
            menu.addSeparator()
        
        # === 鍒犻櫎 ===
        delete_action = QAction("馃棏锔?鍒犻櫎鏁版嵁搴撹褰?, self)
        delete_action.triggered.connect(self._delete_selected_records)
        menu.addAction(delete_action)
        
        # 鏄剧ず鑿滃崟
        menu.exec(event.globalPos())
    
    def _add_common_folders_to_menu(self, menu, callback):
        """娣诲姞甯哥敤鏂囦欢澶瑰埌鑿滃崟"""
        # 鑾峰彇甯哥敤鏂囦欢澶?        common_folders = [
            ("妗岄潰", os.path.join(os.path.expanduser("~"), "Desktop")),
            ("鏂囨。", os.path.join(os.path.expanduser("~"), "Documents")),
            ("涓嬭浇", os.path.join(os.path.expanduser("~"), "Downloads")),
            ("鍥剧墖", os.path.join(os.path.expanduser("~"), "Pictures")),
            ("闊充箰", os.path.join(os.path.expanduser("~"), "Music")),
            ("瑙嗛", os.path.join(os.path.expanduser("~"), "Videos")),
        ]
        
        # 娣诲姞鏀惰棌澶逛腑鐨勬枃浠跺す
        main_window = self.window()
        if hasattr(main_window, 'db'):
            favorites = main_window.db.get_all_favorites()
            if favorites:
                for fav in favorites[:5]:  # 鏈€澶氭樉绀?涓敹钘?                    if os.path.exists(fav['path']):
                        common_folders.append((fav['name'], fav['path']))
        
        # 娣诲姞鍒拌彍鍗?        for name, path in common_folders:
            if os.path.exists(path):
                action = QAction(f"馃搧 {name}", self)
                action.triggered.connect(lambda checked, p=path: callback(p))
                menu.addAction(action)
    
    def _move_to_folder(self, dest_dir):
        """绉诲姩鏂囦欢鍒版寚瀹氭枃浠跺す"""
        from PyQt6.QtWidgets import QMessageBox
        import shutil
        
        selected_items = self.selectedItems()
        moved_count = 0
        
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            src_path = file_data.get('path', '')
            if src_path and os.path.exists(src_path):
                dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                try:
                    shutil.move(src_path, dest_path)
                    moved_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "閿欒", f"绉诲姩澶辫触: {src_path}\n{e}")
        
        if moved_count > 0:
            QMessageBox.information(self, "瀹屾垚", f"宸茬Щ鍔?{moved_count} 涓」鐩埌 {os.path.basename(dest_dir)}")
            main_window = self.window()
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _copy_to_folder(self, dest_dir):
        """澶嶅埗鏂囦欢鍒版寚瀹氭枃浠跺す"""
        from PyQt6.QtWidgets import QMessageBox
        import shutil
        
        selected_items = self.selectedItems()
        copied_count = 0
        
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            src_path = file_data.get('path', '')
            if src_path and os.path.exists(src_path):
                dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                try:
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dest_path)
                    else:
                        shutil.copy2(src_path, dest_path)
                    copied_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "閿欒", f"澶嶅埗澶辫触: {src_path}\n{e}")
        
        if copied_count > 0:
            QMessageBox.information(self, "瀹屾垚", f"宸插鍒?{copied_count} 涓」鐩埌 {os.path.basename(dest_dir)}")
    
    # === 鑿滃崟澶勭悊鍑芥暟 ===
    
    def _create_new_folder(self):
        """鍦ㄥ綋鍓嶈矾寰勫垱寤烘柊鏂囦欢澶?""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        main_window = self.window()
        if hasattr(main_window, 'current_folder_path') and main_window.current_folder_path:
            folder_name, ok = QInputDialog.getText(self, "鏂板缓鏂囦欢澶?, "鏂囦欢澶瑰悕绉?")
            if ok and folder_name:
                new_path = os.path.join(main_window.current_folder_path, folder_name)
                try:
                    os.makedirs(new_path, exist_ok=True)
                    QMessageBox.information(self, "鎴愬姛", f"宸插垱寤烘枃浠跺す: {folder_name}")
                    if hasattr(main_window, 'refresh_current_view'):
                        main_window.refresh_current_view()
                except Exception as e:
                    QMessageBox.warning(self, "閿欒", f"鍒涘缓鏂囦欢澶瑰け璐? {e}")
    
    def _set_rating(self, rating):
        """璁剧疆璇勫垎"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                file_id = file_data.get('id')
                if file_id:
                    if is_folder:
                        main_window.db.set_folder_rating(file_id, rating)
                    else:
                        main_window.db.set_file_rating(file_id, rating)
            
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _set_color(self, color):
        """璁剧疆棰滆壊鏍囩"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                file_id = file_data.get('id')
                if file_id:
                    if is_folder:
                        main_window.db.set_folder_label_color(file_id, color)
                    else:
                        main_window.db.set_file_label_color(file_id, color)
            
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _add_tag(self):
        """娣诲姞鏍囩"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            # 鑾峰彇鎵€鏈夋爣绛?            tags = main_window.db.get_all_tags()
            if not tags:
                QMessageBox.warning(self, "鎻愮ず", "璇峰厛鍒涘缓鏍囩")
                return
            
            tag_names = [t['name'] for t in tags]
            tag_name, ok = QInputDialog.getItem(self, "閫夋嫨鏍囩", "娣诲姞鏍囩:", tag_names, 0, False)
            
            if ok and tag_name:
                tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                    file_id = file_data.get('id')
                    if file_id:
                        if is_folder:
                            main_window.db.link_folder_tag(file_id, tag_id)
                        else:
                            main_window.db.link_file_tag(file_id, tag_id)
                
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
                QMessageBox.information(self, "瀹屾垚", f"宸叉坊鍔犳爣绛?'{tag_name}'")
    
    def _remove_tag(self):
        """绉婚櫎鏍囩"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            tags = main_window.db.get_all_tags()
            if not tags:
                return
            
            tag_names = [t['name'] for t in tags]
            tag_name, ok = QInputDialog.getItem(self, "閫夋嫨鏍囩", "绉婚櫎鏍囩:", tag_names, 0, False)
            
            if ok and tag_name:
                tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                    file_id = file_data.get('id')
                    if file_id:
                        if is_folder:
                            main_window.db.remove_folder_tag(file_id, tag_id)
                        else:
                            main_window.db.remove_file_tag(file_id, tag_id)
                
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
                QMessageBox.information(self, "瀹屾垚", f"宸茬Щ闄ゆ爣绛?'{tag_name}'")
    
    def _toggle_pin(self):
        """鍒囨崲缃《鐘舵€?""
        selected_items = self.selectedItems()
        main_window = self.window()
        
        if hasattr(main_window, 'db'):
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                is_folder = item.data(Qt.ItemDataRole.UserRole + 1)
                file_id = file_data.get('id')
                is_pinned = file_data.get('is_pinned', 0)
                
                if file_id:
                    if is_folder:
                        if is_pinned:
                            main_window.db.unpin_folder(file_id)
                        else:
                            main_window.db.pin_folder(file_id)
                    else:
                        if is_pinned:
                            main_window.db.unpin_file(file_id)
                        else:
                            main_window.db.pin_file(file_id)
            
            if hasattr(main_window, 'refresh_current_view'):
                main_window.refresh_current_view()
    
    def _copy_files(self):
        """澶嶅埗鏂囦欢鍒板壀璐存澘"""
        from PyQt6.QtCore import QMimeData, QUrl
        selected_items = self.selectedItems()
        
        urls = []
        for item in selected_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            path = file_data.get('path', '')
            if path:
                urls.append(QUrl.fromLocalFile(path))
        
        if urls:
            mime_data = QMimeData()
            mime_data.setUrls(urls)
            clipboard = QApplication.clipboard()
            clipboard.setMimeData(mime_data)
    
    def _move_to(self):
        """绉诲姩鏂囦欢鍒版寚瀹氫綅缃?""
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        import shutil
        
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        dest_dir = QFileDialog.getExistingDirectory(self, "閫夋嫨鐩爣鏂囦欢澶?)
        if dest_dir:
            moved_count = 0
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                src_path = file_data.get('path', '')
                if src_path and os.path.exists(src_path):
                    dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                    try:
                        shutil.move(src_path, dest_path)
                        moved_count += 1
                    except Exception as e:
                        QMessageBox.warning(self, "閿欒", f"绉诲姩澶辫触: {src_path}\n{e}")
            
            if moved_count > 0:
                QMessageBox.information(self, "瀹屾垚", f"宸茬Щ鍔?{moved_count} 涓」鐩?)
                main_window = self.window()
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
    
    def _copy_to(self):
        """澶嶅埗鏂囦欢鍒版寚瀹氫綅缃?""
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        import shutil
        
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        dest_dir = QFileDialog.getExistingDirectory(self, "閫夋嫨鐩爣鏂囦欢澶?)
        if dest_dir:
            copied_count = 0
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                src_path = file_data.get('path', '')
                if src_path and os.path.exists(src_path):
                    dest_path = os.path.join(dest_dir, os.path.basename(src_path))
                    try:
                        if os.path.isdir(src_path):
                            shutil.copytree(src_path, dest_path)
                        else:
                            shutil.copy2(src_path, dest_path)
                        copied_count += 1
                    except Exception as e:
                        QMessageBox.warning(self, "閿欒", f"澶嶅埗澶辫触: {src_path}\n{e}")
            
            if copied_count > 0:
                QMessageBox.information(self, "瀹屾垚", f"宸插鍒?{copied_count} 涓」鐩?)
    
    def _rename_file(self):
        """閲嶅懡鍚嶆枃浠?""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        
        selected_items = self.selectedItems()
        if len(selected_items) != 1:
            return
        
        item = selected_items[0]
        file_data = item.data(Qt.ItemDataRole.UserRole)
        old_path = file_data.get('path', '')
        old_name = os.path.basename(old_path)
        
        new_name, ok = QInputDialog.getText(self, "閲嶅懡鍚?, "鏂板悕绉?", text=old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            try:
                os.rename(old_path, new_path)
                QMessageBox.information(self, "鎴愬姛", "閲嶅懡鍚嶆垚鍔?)
                main_window = self.window()
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
            except Exception as e:
                QMessageBox.warning(self, "閿欒", f"閲嶅懡鍚嶅け璐? {e}")
    
    def _batch_rename(self):
        """鎵归噺閲嶅懡鍚?""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        prefix, ok = QInputDialog.getText(self, "鎵归噺閲嶅懡鍚?, "杈撳叆鍓嶇紑锛堝皢娣诲姞缂栧彿锛?")
        if ok and prefix:
            renamed_count = 0
            for i, item in enumerate(selected_items, 1):
                file_data = item.data(Qt.ItemDataRole.UserRole)
                old_path = file_data.get('path', '')
                ext = os.path.splitext(old_path)[1]
                new_name = f"{prefix}_{i:03d}{ext}"
                new_path = os.path.join(os.path.dirname(old_path), new_name)
                
                try:
                    os.rename(old_path, new_path)
                    renamed_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "閿欒", f"閲嶅懡鍚嶅け璐? {old_path}\n{e}")
            
            if renamed_count > 0:
                QMessageBox.information(self, "瀹屾垚", f"宸查噸鍛藉悕 {renamed_count} 涓」鐩?)
                main_window = self.window()
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
    
    def _open_file(self, path):
        """鎵撳紑鏂囦欢鎴栨枃浠跺す"""
        import subprocess
        if os.path.exists(path):
            if os.name == 'nt':  # Windows
                os.startfile(path)
            elif os.name == 'posix':  # macOS/Linux
                subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', path])
    
    def _show_in_explorer(self, path):
        """鍦ㄨ祫婧愮鐞嗗櫒涓樉绀?""
        import subprocess
        if os.path.exists(path):
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', '/select,', path])
            elif sys.platform == 'darwin':  # macOS
                subprocess.run(['open', '-R', path])
            else:  # Linux
                subprocess.run(['xdg-open', os.path.dirname(path)])
    
    def _copy_path(self, path):
        """澶嶅埗璺緞鍒板壀璐存澘"""
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
    
    def _add_selected_to_favorites(self):
        """娣诲姞閫変腑鐨勬枃浠跺す鍒版敹钘忓す"""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        folders = [item.data(Qt.ItemDataRole.UserRole)['path'] 
                  for item in selected_items 
                  if item.data(Qt.ItemDataRole.UserRole + 1)]
        
        if folders:
            main_window = self.window()
            if hasattr(main_window, 'favorites_panel'):
                for folder_path in folders:
                    main_window.favorites_panel.add_favorite(folder_path)
                QMessageBox.information(self, "瀹屾垚", f"宸叉坊鍔?{len(folders)} 涓枃浠跺す鍒版敹钘忓す")
            else:
                QMessageBox.warning(self, "閿欒", "鏃犳硶璁块棶鏀惰棌澶归潰鏉?)
    
    def _delete_selected_records(self):
        """鍒犻櫎閫変腑鐨勮褰?""
        from PyQt6.QtWidgets import QMessageBox
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        reply = QMessageBox.question(
            self, 
            "纭鍒犻櫎", 
            f"纭畾瑕佷粠鏁版嵁搴撲腑鍒犻櫎 {len(selected_items)} 涓枃浠?鏂囦欢澶圭殑璁板綍鍚楋紵\n\n娉ㄦ剰锛氳繖涓嶄細鍒犻櫎瀹為檯鏂囦欢锛屽彧鍒犻櫎鏁版嵁搴撹褰曘€?,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            main_window = self.window()
            if hasattr(main_window, 'db'):
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    file_id = file_data.get('id')
                    if file_id:
                        main_window.db.delete_file(file_id)
                
                if hasattr(main_window, 'refresh_current_view'):
                    main_window.refresh_current_view()
                QMessageBox.information(self, "瀹屾垚", f"宸插垹闄?{len(selected_items)} 鏉¤褰?)


# ===================|===================
# 文件名: folder_browser.py
"""
鏂囦欢澶规祻瑙堝櫒缁勪欢

浣跨敤 QFileSystemModel 鏄剧ず鏂囦欢绯荤粺鏍戝舰缁撴瀯
"""

from PyQt6.QtWidgets import QTreeView, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QDir, QStandardPaths
from PyQt6.QtGui import QFileSystemModel, QIcon
import os

class FolderBrowserWidget(QWidget):
    """鏂囦欢澶规祻瑙堝櫒缁勪欢"""
    folder_selected = pyqtSignal(str)  # 閫変腑鐨勬枃浠跺す璺緞
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """璁剧疆UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # 蹇€熻闂尯鍩?
        quick_access_layout = QHBoxLayout()
        quick_access_layout.setContentsMargins(5, 5, 5, 0)
        
        # 妗岄潰鎸夐挳
        desktop_btn = QPushButton("妗岄潰")
        desktop_btn.setToolTip("杞埌妗岄潰")
        desktop_btn.clicked.connect(self._go_to_desktop)
        quick_access_layout.addWidget(desktop_btn)
        
        # 姝ょ數鑴戞寜閽?
        computer_btn = QPushButton("姝ょ數鑴?)
        computer_btn.setToolTip("杞埌姝ょ數鑴?)
        computer_btn.clicked.connect(self._go_to_computer)
        quick_access_layout.addWidget(computer_btn)
        
        layout.addLayout(quick_access_layout)
        
        # 鏂囦欢绯荤粺鏍戣鍥?
        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True) # 闅愯棌琛ㄥご
        
        # 鍒涘缓鏂囦欢绯荤粺妯″瀷
        self.model = QFileSystemModel()
        self.model.setRootPath("")
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        
        # 璁剧疆妯″瀷
        self.tree_view.setModel(self.model)
        
        # 璁剧疆鏍圭储寮曪紙鏄剧ず鎵€鏈夐┍鍔ㄥ櫒锛?
        self.tree_view.setRootIndex(self.model.index(""))
        
        # 闅愯棌涓嶉渶瑕佺殑鍒楋紙鍙樉绀哄悕绉帮級
        for i in range(1, self.model.columnCount()):
            self.tree_view.hideColumn(i)
        
        # 杩炴帴淇″彿
        self.tree_view.clicked.connect(self._on_folder_clicked)
        
        layout.addWidget(self.tree_view)
    
    def _go_to_desktop(self):
        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        self.expand_path(path)
        self.folder_selected.emit(path)

    def _go_to_computer(self):
        # Windows涓嬬┖瀛楃涓茶〃绀?姝ょ數鑴?瑙嗗浘锛堥┍鍔ㄥ櫒鍒楄〃锛?
        # 浣?QFileSystemModel 鐨?rootPath 涓?"" 鏃跺凡缁忔樉绀洪┍鍔ㄥ櫒
        # 鎴戜滑鍙渶瑕佹竻闄ら€変腑椤规垨婊氬姩鍒伴《閮?
        self.tree_view.clearSelection()
        self.tree_view.scrollToTop()
        # 杩欓噷涓嶅彂灏?folder_selected锛屽洜涓?姝ょ數鑴?涓嶆槸涓€涓枃浠跺す璺緞
        # 鎴栬€呮垜浠彲浠ュ彂灏?""锛岃 main.py 澶勭悊?
        # main.py 鐨?load_files_from_folder 闇€瑕佺湡瀹炶矾寰勩€?
        # 鎵€浠ヨ繖閲屼粎鐢ㄤ簬娴忚銆?
        pass

    def _on_folder_clicked(self, index):
        """鏂囦欢澶硅鐐瑰嚮"""
        path = self.model.filePath(index)
        self.folder_selected.emit(path)
    
    def expand_path(self, path):
        """灞曞紑鍒版寚瀹氳矾寰?""
        if not path: return
        index = self.model.index(path)
        if index.isValid():
            self.tree_view.expand(index)
            self.tree_view.setCurrentIndex(index)
            self.tree_view.scrollTo(index)


# ===================|===================
# 文件名: logger.py
import logging
import sys
import os
import traceback
from datetime import datetime

# 鏃ュ織鏂囦欢璺緞
LOG_FILE = "debug.log"

def setup_logging():
    """閰嶇疆鏃ュ織绯荤粺"""
    # 鍒涘缓鏃ュ織鏍煎紡
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 鏂囦欢澶勭悊鍣?(鍐欏叆 debug.log)
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # 鎺у埗鍙板鐞嗗櫒 (杈撳嚭鍒扮粓绔?
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 鑾峰彇鏍规棩蹇楄褰曞櫒
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 鎹曡幏鏈鐞嗙殑寮傚父
    sys.excepthook = handle_exception

    logging.info("=== 鏃ュ織绯荤粺宸插惎鍔?===")
    return root_logger

def handle_exception(exc_type, exc_value, exc_traceback):
    """鍏ㄥ眬寮傚父鎹曡幏"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logging.critical("鏈崟鑾风殑寮傚父:", exc_info=(exc_type, exc_value, exc_traceback))

def get_logger(name):
    """鑾峰彇鎸囧畾鍚嶇О鐨勬棩蹇楄褰曞櫒"""
    return logging.getLogger(name)


# ===================|===================
# 文件名: main.py
import sys
import os
import time
import logging
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QSplitter, QLabel, QFileDialog, QInputDialog,
                             QToolBar, QMessageBox, QTabWidget, QStyleFactory, QListWidget,
                             QLineEdit, QPushButton, QMenu, QListWidgetItem, QComboBox)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QDir, QSettings
from PyQt6.QtGui import QIcon, QPixmap, QAction, QKeySequence, QPalette, QColor

from db_manager import DatabaseManager
from data_source_manager import DataSourceManager
from cache_manager import ThumbnailCache, MetadataCache
from enhanced_file_list import EnhancedFileListWidget, FileItemWidget
from folder_browser import FolderBrowserWidget
from search_bar import SearchBar
from properties_panel import PropertiesPanel
from draggable_favorites import DraggableFavoritesPanel
from logger import setup_logging, get_logger

# 鍒濆鍖栨棩蹇?
setup_logging()
logger = get_logger(__name__)

def apply_dark_theme(app):
    """搴旂敤娣辫壊涓婚"""
    logger.debug("搴旂敤娣辫壊涓婚")
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
    """鍚庡彴鍔犺浇鏂囦欢鍒楄〃绾跨▼"""
    batch_ready = pyqtSignal(list, list) # files, folders
    finished = pyqtSignal()

    def __init__(self, folder_path, sort_mode='name_asc', recursive=False, show_hidden=False, use_db_source=False):
        super().__init__()
        self.folder_path = folder_path
        self.sort_mode = sort_mode
        self.recursive = recursive
        self.show_hidden = show_hidden
        self.use_db_source = use_db_source
        self.is_running = True
        logger.info(f"FileLoaderThread 鍒濆鍖? path={folder_path}, sort={sort_mode}, recursive={recursive}, hidden={show_hidden}, db_source={use_db_source}")

    def run(self):
        start_time = time.time()
        db = DatabaseManager()
        files_batch = []
        folders_batch = []
        
        try:
            logger.info(f"寮€濮嬪姞杞? {self.folder_path}")
            
            if self.use_db_source:
                # === 鏁版嵁搴撴ā寮?===
                logger.info("浣跨敤鏁版嵁搴撴ā寮忓姞杞?)
                all_files = db.get_files_recursive(self.folder_path)
                all_folders = db.get_folders_recursive(self.folder_path)
                
                if not self.show_hidden:
                    all_files = [f for f in all_files if not os.path.basename(f['path']).startswith('.')]
                    all_folders = [f for f in all_folders if not os.path.basename(f['path']).startswith('.')]
                
                logger.info(f"鏁版嵁鑾峰彇鑰楁椂: {time.time() - start_time:.4f}s")
                
                # 鎺掑簭
                self._sort_batch(all_files, all_folders)
                
                logger.info(f"澶勭悊瀹屾垚: {len(all_files)} 鏂囦欢, {len(all_folders)} 鏂囦欢澶?)
                
                # 鍒嗘壒鍙戝皠鏁版嵁锛岄伩鍏嶇晫闈㈠崱椤?
                # 鍏堝彂閫佹墍鏈夋枃浠跺す
                if all_folders:
                    self.batch_ready.emit([], all_folders)
                    QThread.msleep(20)
                
                # 鍒嗘壒鍙戦€佹枃浠?
                chunk_size = 100 # 姣忔鍙戦€?00涓枃浠?
                total_files = len(all_files)
                for i in range(0, total_files, chunk_size):
                    if not self.is_running: break
                    chunk = all_files[i : i + chunk_size]
                    self.batch_ready.emit(chunk, [])
                    # 缁欎富绾跨▼涓€鐐规椂闂村鐞哢I
                    QThread.msleep(30)
                    
            else:
                # === 纾佺洏鎵弿妯″紡 ===
                logger.info("浣跨敤纾佺洏鎵弿妯″紡鍔犺浇")
                if not os.path.exists(self.folder_path):
                    logger.warning(f"璺緞涓嶅瓨鍦? {self.folder_path}")
                    return

                def iterate_items():
                    if self.recursive:
                        for root, dirs, files in os.walk(self.folder_path):
                            for d in dirs:
                                yield os.path.join(root, d), True
                            for f in files:
                                yield os.path.join(root, f), False
                    else:
                        for item_name in os.listdir(self.folder_path):
                            yield os.path.join(self.folder_path, item_name), os.path.isdir(os.path.join(self.folder_path, item_name))

                count = 0
                for item_path, is_dir in iterate_items():
                    if not self.is_running: 
                        logger.info("鍔犺浇琚腑鏂?)
                        break
                    
                    item_name = os.path.basename(item_path)
                    
                    if not self.show_hidden and item_name.startswith('.'):
                        continue
                    
                    try:
                        if is_dir:
                            folder_id = db.upsert_folder(item_path, recursive=False)
                            if folder_id:
                                folder_data = db.get_folder_by_path(item_path)
                                if folder_data:
                                    folders_batch.append(folder_data)
                        else:
                            file_id = db.upsert_file(item_path)
                            if file_id:
                                file_data = db.get_file_by_id(file_id)
                                if file_data:
                                    files_batch.append(file_data)
                        
                        count += 1
                        # 纾佺洏妯″紡涓嬶紝姣?00涓彂閫佷竴娆★紝鎴栬€呮瘡闅斾竴娈垫椂闂村彂閫佷竴娆?
                        # 杩欓噷澶嶇敤涔嬪墠鐨勯€昏緫锛氭敹闆嗗埌 batch 鍚庡彂閫?
                        # 浣嗕箣鍓嶇殑閫昏緫鏄叏閮ㄦ敹闆嗗畬鎵嶅彂閫侊紵涓嶏紝涔嬪墠鐨勯€昏緫鏄渶鍚庢墠鍙戦€併€?
                        # 搴旇鏀逛负姣忔敹闆嗕竴瀹氭暟閲忓氨鍙戦€併€?
                        
                        if len(files_batch) + len(folders_batch) >= 100:
                            self._sort_batch(files_batch, folders_batch)
                            self.batch_ready.emit(files_batch, folders_batch)
                            files_batch = []
                            folders_batch = []
                            QThread.msleep(20)
                                    
                    except Exception as e:
                        logger.error(f"澶勭悊椤圭洰澶辫触 {item_name}: {e}")
                
                # 鍙戦€佸墿浣欑殑
                if files_batch or folders_batch:
                    self._sort_batch(files_batch, folders_batch)
                    self.batch_ready.emit(files_batch, folders_batch)
            
            logger.info(f"鏂囦欢澶瑰姞杞藉畬鎴? {self.folder_path}")
                
        except Exception as e:
            logger.error(f"鍔犺浇鍑洪敊: {e}", exc_info=True)
        finally:
            db.close()
            self.finished.emit()

    def _sort_batch(self, files, folders):
        """鎺掑簭鍒楄〃"""
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
        logger.info("鍋滄鏂囦欢鍔犺浇绾跨▼")
        self.is_running = False
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("鍒濆鍖栦富绐楀彛")
        self.setWindowTitle("Python Bridge - 璧勬簮绠＄悊")
        self.resize(1600, 900)

        # 鏁版嵁涓庣姸鎬?
        self.db = DatabaseManager()
        self.db.init_db() # 鍒濆鍖栨暟鎹簱骞惰嚜鍔ㄨ縼绉绘灦鏋?
        
        # 鏁版嵁婧愮鐞嗗櫒锛堢粺涓€绠＄悊 SQLite 鍜?JSON锛?
        self.data_source = DataSourceManager(self.db)
        
        self.thumb_cache = ThumbnailCache()
        self.meta_cache = MetadataCache(self.db)
        
        self.current_tag_id = -1
        self.current_folder_path = None
        self.current_view_mode = 'grid'
        self.current_sort_mode = 'name_asc'
        
        # 瑙嗗浘閫夐」
        self.show_hidden_files = False
        self.show_folders = True
        self.show_subfolders_content = False  # 閫掑綊鏄剧ず瀛愭枃浠跺す鍐呭
        
        # 瀵艰埅鍘嗗彶
        self.history = []
        self.history_index = -1
        self.is_navigating_history = False
        
        # 鍔犺浇绾跨▼
        self.loader_thread = None

        # 涓ぎ甯冨眬
        self._setup_central_widget()

        # 鑿滃崟銆佸伐鍏锋爮涓庡揩鎹烽敭
        self.setup_menu_bar()
        self.setup_toolbar()
        self.setup_shortcuts()

        # 鍒濆鍔犺浇
        self.restore_settings()
        self._check_and_fix_db_schema()
        
        # 鑷姩鍔犺浇绗竴涓敹钘忓す
        QThread.currentThread().setObjectName("MainThread")
        self.load_initial_path()
        
        self.statusBar().showMessage("鍑嗗灏辩华")
        logger.info("涓荤獥鍙ｅ垵濮嬪寲瀹屾垚")

    def restore_settings(self):
        """鎭㈠鐣岄潰璁剧疆"""
        settings = QSettings("PythonBridge", "FileManager")
        
        # 鎭㈠绐楀彛澶у皬鍜屼綅缃?
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            
        # 鎭㈠鍒嗗壊鍣ㄧ姸鎬?
        splitter_state = settings.value("splitterState")
        if splitter_state:
            # 鎵惧埌 splitter
            splitter = self.findChild(QSplitter)
            if splitter:
                splitter.restoreState(splitter_state)
    
    def closeEvent(self, event):
        """鍏抽棴绐楀彛鏃朵繚瀛樿缃?""
        settings = QSettings("PythonBridge", "FileManager")
        
        settings.setValue("geometry", self.saveGeometry())
        
        splitter = self.findChild(QSplitter)
        if splitter:
            settings.setValue("splitterState", splitter.saveState())
            
        super().closeEvent(event)

    def load_initial_path(self):
        """鍔犺浇鍒濆璺緞锛堢涓€涓敹钘忓す锛?""
        favorites = self.db.get_all_favorites()
        if favorites:
            first_fav = favorites[0]
            path = first_fav['path']
            if os.path.exists(path):
                logger.info(f"鍚姩鑷姩鍔犺浇鏀惰棌澶? {path}")
                self.load_path(path)
            else:
                logger.warning(f"鍒濆鏀惰棌澶硅矾寰勪笉瀛樺湪: {path}")
        else:
            logger.info("娌℃湁鏀惰棌澶癸紝涓嶈嚜鍔ㄥ姞杞借矾寰?)

    def _check_and_fix_db_schema(self):
        """妫€鏌ュ苟淇鏁版嵁搴撶粨鏋?""
        try:
            self.db.connect()
            cursor = self.db.conn.cursor()
            
            # 妫€鏌?files 琛ㄦ槸鍚︽湁 extension 鍒?
            cursor.execute("PRAGMA table_info(files)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'extension' not in columns:
                logger.warning("files 琛ㄧ己灏?extension 鍒楋紝灏濊瘯娣诲姞...")
                try:
                    cursor.execute("ALTER TABLE files ADD COLUMN extension TEXT")
                    self.db.conn.commit()
                    logger.info("鎴愬姛娣诲姞 extension 鍒?)
                except Exception as e:
                    logger.error(f"娣诲姞 extension 鍒楀け璐? {e}")
            
        except Exception as e:
            logger.error(f"妫€鏌ユ暟鎹簱缁撴瀯澶辫触: {e}")
        finally:
            self.db.close()

    def _setup_central_widget(self):
        """鏋勫缓涓荤晫闈㈠竷灞€"""
        logger.debug("璁剧疆涓ぎ缁勪欢")
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        main_layout.addWidget(splitter)

        # === 宸︿晶闈㈡澘 (鏂囦欢澶?鏀惰棌) ===
        left_panel = QTabWidget()
        left_panel.setTabPosition(QTabWidget.TabPosition.North)
        
        # 鏂囦欢澶规爣绛鹃〉
        folder_tab = QWidget()
        folder_layout = QVBoxLayout(folder_tab)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        
        # 娣诲姞"娣诲姞褰撳墠鏂囦欢澶?鎸夐挳
        add_fav_btn = QPushButton("娣诲姞褰撳墠鏂囦欢澶?)
        add_fav_btn.clicked.connect(self.add_current_to_favorites)
        folder_layout.addWidget(add_fav_btn)
        
        self.folder_browser = FolderBrowserWidget()
        self.folder_browser.folder_selected.connect(self.on_folder_selected)
        folder_layout.addWidget(self.folder_browser)
        left_panel.addTab(folder_tab, "鏂囦欢澶?)
        
        # 鏀惰棌澶规爣绛鹃〉
        fav_tab = QWidget()
        fav_layout = QVBoxLayout(fav_tab)
        fav_layout.setContentsMargins(0, 0, 0, 0)
        
        self.favorites_panel = DraggableFavoritesPanel(self.db)
        self.favorites_panel.favorite_clicked.connect(self.load_path)
        
        fav_layout.addWidget(self.favorites_panel)
        left_panel.addTab(fav_tab, "鏀惰棌澶?)

        splitter.addWidget(left_panel)

        # === 涓棿闈㈡澘 (鏂囦欢鍒楄〃) ===
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        self.file_list = EnhancedFileListWidget(self.thumb_cache)
        self.file_list.item_clicked.connect(self.on_file_clicked)
        self.file_list.selection_changed.connect(self.on_selection_changed_list)
        self.file_list.go_up_requested.connect(self._handle_go_up)
        self.file_list.rename_file_requested.connect(self._handle_inline_rename)
        
        center_layout.addWidget(self.file_list)
        splitter.addWidget(center_panel)

        # === 鍙充晶闈㈡澘 (灞炴€?鍏冩暟鎹? ===
        self.properties_panel = PropertiesPanel(self.db)
        self.properties_panel.rating_changed.connect(self.on_rating_changed)
        self.properties_panel.tag_added.connect(self.on_tag_added)
        self.properties_panel.tag_removed.connect(self.on_tag_removed)
        self.properties_panel.tag_created.connect(self.on_tag_created)
        self.properties_panel.filter_changed.connect(self.on_filter_changed)
        self.properties_panel.quick_tag_requested.connect(self.on_quick_tag_requested)
        splitter.addWidget(self.properties_panel)

        # 璁剧疆鍒濆姣斾緥
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 1000, 300])

        self.setCentralWidget(central)

    def setup_toolbar(self):
        """璁剧疆宸ュ叿鏍?""
        logger.debug("璁剧疆宸ュ叿鏍?)
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 瀵艰埅鎸夐挳
        self.back_action = QAction("鈫?, self)
        self.back_action.setToolTip("鍚庨€€")
        self.back_action.triggered.connect(self.go_back)
        self.back_action.setEnabled(False)
        toolbar.addAction(self.back_action)
        
        self.forward_action = QAction("鈫?, self)
        self.forward_action.setToolTip("鍓嶈繘")
        self.forward_action.triggered.connect(self.go_forward)
        self.forward_action.setEnabled(False)
        toolbar.addAction(self.forward_action)
        
        self.up_action = QAction("鈫?, self)
        self.up_action.setToolTip("涓婄骇鐩綍")
        self.up_action.triggered.connect(self.go_up)
        toolbar.addAction(self.up_action)
        
        toolbar.addSeparator()
        
        # 鍦板潃鏍?
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("杈撳叆璺緞...")
        self.path_edit.returnPressed.connect(lambda: self.load_path(self.path_edit.text()))
        toolbar.addWidget(self.path_edit)
        
        toolbar.addSeparator()
        
        # 鎼滅储鏍?
        self.search_bar = SearchBar()
        self.search_bar.setMaximumWidth(250)
        self.search_bar.search_triggered.connect(self.search_files)
        toolbar.addWidget(self.search_bar)
        
        toolbar.addSeparator()

        # 鎺掑簭閫夐」
        sort_label = QLabel("鎺掑簭:")
        toolbar.addWidget(sort_label)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "鍚嶇О鈫?, "鍚嶇О鈫?, 
            "淇敼鏃堕棿鈫?, "淇敼鏃堕棿鈫?,
            "澶у皬鈫?, "澶у皬鈫?
        ])
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        toolbar.addWidget(self.sort_combo)
        
        toolbar.addSeparator()

        # 瑙嗗浘鍒囨崲
        grid_view_action = QAction("馃搮", self)
        grid_view_action.setToolTip("缃戞牸瑙嗗浘")
        grid_view_action.triggered.connect(lambda: self.switch_view_mode('grid'))
        toolbar.addAction(grid_view_action)
        
        list_view_action = QAction("鈽?, self)
        list_view_action.setToolTip("鍒楄〃瑙嗗浘")
        list_view_action.triggered.connect(lambda: self.switch_view_mode('list'))
        toolbar.addAction(list_view_action)
        
        refresh_action = QAction("鈫?, self)
        refresh_action.setToolTip("鍒锋柊")
        refresh_action.triggered.connect(self.refresh_current_view)
        toolbar.addAction(refresh_action)

    def setup_menu_bar(self):
        """鍒濆鍖栬彍鍗曟爮"""
        logger.debug("璁剧疆鑿滃崟鏍?)
        menubar = self.menuBar()

        # 瑙嗗浘鑿滃崟
        view_menu = menubar.addMenu("瑙嗗浘")
        
        # 鏄剧ず闅愯棌鏂囦欢
        self.show_hidden_action = QAction("鏄剧ず闅愯棌鏂囦欢", self, checkable=True)
        self.show_hidden_action.setChecked(self.show_hidden_files)
        self.show_hidden_action.triggered.connect(self.toggle_show_hidden_files)
        view_menu.addAction(self.show_hidden_action)
        
        # 鏄剧ず鏂囦欢澶?
        self.show_folders_action = QAction("鏄剧ず鏂囦欢澶?, self, checkable=True)
        self.show_folders_action.setChecked(self.show_folders)
        self.show_folders_action.triggered.connect(self.toggle_show_folders)
        view_menu.addAction(self.show_folders_action)
        
        # 鏄剧ず瀛愭枃浠跺す涓殑椤圭洰锛堥€掑綊锛?
        self.show_sub_content_action = QAction("鏄剧ず瀛愭枃浠跺す涓殑椤圭洰(鍏ㄥ眬鑼冨洿)", self, checkable=True)
        self.show_sub_content_action.setChecked(self.show_subfolders_content)
        self.show_sub_content_action.triggered.connect(self.toggle_show_subfolders_content)
        view_menu.addAction(self.show_sub_content_action)

    def setup_shortcuts(self):
        """璁剧疆閿洏蹇嵎閿?""
        logger.debug("璁剧疆蹇嵎閿?)
        # 璇勭骇 (Ctrl+0-5)
        for i in range(6):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{i}"))
            action.triggered.connect(lambda checked, r=i: self.set_selected_rating(r))
            self.addAction(action)
        
        # 棰滆壊 (Ctrl+6-9)
        color_map = {6: 'red', 7: 'yellow', 8: 'green', 9: 'blue'}
        for key, color in color_map.items():
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{key}"))
            action.triggered.connect(lambda checked, c=color: self.set_selected_color(c))
            self.addAction(action)
        
        # 缃《 (Ctrl+P)
        pin_action = QAction(self)
        pin_action.setShortcut(QKeySequence("Ctrl+P"))
        pin_action.triggered.connect(self.toggle_selected_pin)
        self.addAction(pin_action)
        
        # 鎼滅储 (Ctrl+F)
        search_action = QAction(self)
        search_action.setShortcut(QKeySequence("Ctrl+F"))
        search_action.triggered.connect(lambda: self.search_bar.setFocus())
        self.addAction(search_action)

    def toggle_show_hidden_files(self, checked):
        """鍒囨崲鏄剧ず闅愯棌鏂囦欢"""
        self.show_hidden_files = checked
        logger.info(f"鏄剧ず闅愯棌鏂囦欢: {checked}")
        self.refresh_current_view()

    def toggle_show_folders(self, checked):
        """鍒囨崲鏄剧ず鏂囦欢澶?""
        self.show_folders = checked
        logger.info(f"鏄剧ず鏂囦欢澶? {checked}")
        self.refresh_current_view()

    def toggle_show_subfolders_content(self, checked):
        """鍒囨崲鏄剧ず瀛愭枃浠跺す鍐呭锛堥€掑綊锛?""
        self.show_subfolders_content = checked
        logger.info(f"鏄剧ず瀛愭枃浠跺す鍐呭: {checked}")
        self.refresh_current_view()

    # ================= 瀵艰埅閫昏緫 =================
    
    def load_path(self, path):
        """鍔犺浇鎸囧畾璺緞"""
        logger.info(f"鍔犺浇璺緞: {path}")
        path = os.path.normpath(path)
        if not os.path.exists(path) or not os.path.isdir(path):
            logger.warning(f"璺緞涓嶅瓨鍦ㄦ垨涓嶆槸鐩綍: {path}")
            self.statusBar().showMessage(f"璺緞涓嶅瓨鍦? {path}")
            return

        # 鏇存柊鍘嗗彶璁板綍
        if not self.is_navigating_history:
            if self.history_index < len(self.history) - 1:
                self.history = self.history[:self.history_index+1]
            self.history.append(path)
            self.history_index += 1
            self.update_nav_buttons()
        
        self.current_folder_path = path
        self.current_tag_id = -1
        self.path_edit.setText(path)
        self.setWindowTitle(f"Python Bridge - {os.path.basename(path)}")
        
        # 鏍规嵁瑙嗗浘妯″紡璁剧疆鏁版嵁婧愯寖鍥?
        use_db_source = False
        if self.show_subfolders_content:
            # 閫掑綊鏄剧ず瀛愭枃浠跺す鍐呭鏃讹紝浣跨敤鍏ㄥ眬鑼冨洿锛圫QLite锛?
            # 骞朵笖浣跨敤鏁版嵁搴撲綔涓烘暟鎹簮锛岃€屼笉鏄壂鎻忕鐩?
            self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
            use_db_source = True
            logger.info(f"鏁版嵁婧愬垏鎹㈠埌鍏ㄥ眬鑼冨洿锛堥€掑綊瑙嗗浘 - 鏁版嵁搴撴ā寮忥級: {path}")
        else:
            # 鏅€氭枃浠跺す瑙嗗浘锛屼娇鐢ㄥ眬閮ㄨ寖鍥达紙JSON + DB锛?
            self.data_source.set_scope(DataSourceManager.SCOPE_LOCAL, path)
            logger.info(f"鏁版嵁婧愬垏鎹㈠埌灞€閮ㄨ寖鍥? {path}")
        
        # 鍚屾宸︿晶鏍?
        self.folder_browser.expand_path(path)
        
        # 寮€濮嬪紓姝ュ姞杞?
        self.start_async_loading(path, use_db_source=use_db_source)

    def start_async_loading(self, path, use_db_source=False):
        """鍚姩寮傛鍔犺浇绾跨▼"""
        logger.info(f"鍚姩寮傛鍔犺浇: {path}, recursive={self.show_subfolders_content}, hidden={self.show_hidden_files}, db_source={use_db_source}")
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.stop()
        
        self.file_list.clear()
        self.statusBar().showMessage(f"姝ｅ湪鍔犺浇: {path}...")
        
        self.loader_thread = FileLoaderThread(
            path, 
            self.current_sort_mode, 
            recursive=self.show_subfolders_content,
            show_hidden=self.show_hidden_files,
            use_db_source=use_db_source
        )
        self.loader_thread.batch_ready.connect(self.on_files_batch_ready)
        self.loader_thread.finished.connect(lambda: self.statusBar().showMessage(f"鍔犺浇瀹屾垚: {path}"))
        self.loader_thread.start()

    def on_files_batch_ready(self, files, folders):
        """鎺ユ敹鍚庡彴绾跨▼鍔犺浇鐨勪竴鎵规枃浠?""
        t0 = time.time()
        logger.debug(f"鏀跺埌鏂囦欢鎵规: {len(files)} 鏂囦欢, {len(folders)} 鏂囦欢澶?)
        
        # === 鍏抽敭淇锛氬悎骞?JSON 鍏冩暟鎹?===
        # 浠?DataSourceManager 璇诲彇鍏冩暟鎹紙浼樺厛 JSON锛夛紝鏇存柊 file_data
        for file_data in files:
            path = file_data.get('path')
            if path:
                metadata = self.data_source.get_item_metadata(path)
                # 鏇存柊鍏冩暟鎹瓧娈?
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
        
        # 濡傛灉涓嶆樉绀烘枃浠跺す锛屾竻绌烘枃浠跺す鍒楄〃
        if not self.show_folders:
            folders = []
            
        # 浣跨敤 EnhancedFileListWidget 鐨?append_files 鏂规硶
        self.file_list.append_files(files, folders)
        logger.info(f"UI娓叉煋鑰楁椂: {time.time() - t0:.4f}s")
        
        all_files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not item.data(Qt.ItemDataRole.UserRole + 1): # Not folder
                all_files.append(data)
        
        self.properties_panel.update_filter_stats(all_files)
        
        self._apply_active_filters()
    
    def _on_item_rating_changed(self, file_data, rating):
        """鏂囦欢椤圭殑璇勫垎鏀瑰彉"""
        logger.info(f"璇勫垎鏀瑰彉: {file_data.get('path')} -> {rating}")
        item_id = file_data.get('id')
        if item_id:
            if file_data.get('is_folder'):
                self.db.set_folder_rating(item_id, rating)
            else:
                self.db.set_file_rating(item_id, rating)

    def add_current_to_favorites(self):
        """灏嗗綋鍓嶆枃浠跺す娣诲姞鍒版敹钘忓す"""
        if self.current_folder_path and os.path.exists(self.current_folder_path):
            self.favorites_panel.add_favorite(self.current_folder_path)
        else:
            QMessageBox.warning(self, "鎻愮ず", "褰撳墠娌℃湁鎵撳紑鐨勬枃浠跺す")

    def go_back(self):
        """鍚庨€€"""
        logger.info("鍚庨€€瀵艰埅")
        if self.history_index > 0:
            self.is_navigating_history = True
            self.history_index -= 1
            self.load_path(self.history[self.history_index])
            self.is_navigating_history = False
            self.update_nav_buttons()

    def go_forward(self):
        """鍓嶈繘"""
        logger.info("鍓嶈繘瀵艰埅")
        if self.history_index < len(self.history) - 1:
            self.is_navigating_history = True
            self.history_index += 1
            self.load_path(self.history[self.history_index])
            self.is_navigating_history = False
            self.update_nav_buttons()

    def go_up(self):
        """涓婄骇鐩綍"""
        logger.info("涓婄骇鐩綍")
        if self.current_folder_path:
            parent = os.path.dirname(self.current_folder_path)
            if parent and os.path.exists(parent):
                self.load_path(parent)

    def update_nav_buttons(self):
        """鏇存柊瀵艰埅鎸夐挳鐘舵€?""
        self.back_action.setEnabled(self.history_index > 0)
        self.forward_action.setEnabled(self.history_index < len(self.history) - 1)

    def on_folder_selected(self, folder_path):
        """宸︿晶鏍戦€変腑鏂囦欢澶?""
        logger.info(f"鏂囦欢澶规爲閫夋嫨: {folder_path}")
        self.load_path(folder_path)

    def on_sort_changed(self, index):
        """鎺掑簭鏂瑰紡鏀瑰彉"""
        sort_modes = ['name_asc', 'name_desc', 'date_asc', 'date_desc', 'size_asc', 'size_desc']
        self.current_sort_mode = sort_modes[index]
        logger.info(f"鎺掑簭鏂瑰紡鏀瑰彉: {self.current_sort_mode}")
        self.refresh_current_view()

    # ================= 涓氬姟閫昏緫 =================

    def on_file_clicked(self, path):
        """鏂囦欢琚偣鍑?""
        logger.info(f"鏂囦欢琚偣鍑? {path}")
        if os.path.isdir(path):
            # 鐐瑰嚮鏂囦欢澶?瀵艰埅杩涘叆
            self.load_path(path)
        else:
            # 鐐瑰嚮鏂囦欢,鏇存柊灞炴€ч潰鏉?
            file_id = self.db.upsert_file(path)
            if file_id:
                file_data = self.db.get_file_by_id(file_id)
                if file_data:
                    thumb_path = self.thumb_cache.get_thumbnail(path)
                    self.properties_panel.set_file(file_data, thumb_path)
                    self.properties_panel.set_tag_input_enabled(True)

    def on_selection_changed_list(self, paths):
        """閫夋嫨鏀瑰彉(鏉ヨ嚜鏂囦欢鍒楄〃)"""
        logger.debug(f"閫夋嫨鏀瑰彉: {len(paths)} 涓」鐩?)
        if not paths:
            self.properties_panel.clear()
            return
        
        # 缁熻鏂囦欢鍜屾枃浠跺す鏁伴噺
        file_count = sum(1 for p in paths if os.path.isfile(p))
        total_count = len(paths)
        
        if total_count == 1 and file_count == 1:
            # 鍗曚釜鏂囦欢琚€変腑
            path = paths[0]
            file_id = self.db.upsert_file(path)
            if file_id:
                file_data = self.db.get_file_by_id(file_id)
                if file_data:
                    thumb_path = self.thumb_cache.get_thumbnail(path)
                    self.properties_panel.set_file(file_data, thumb_path)
                    self.properties_panel.set_tag_input_enabled(True)
        else:
            # 澶氫釜椤圭洰琚€変腑
            self.properties_panel.clear(keep_tag_input=True)
            self.properties_panel.show_selection_summary(total_count, file_count)

    def on_selection_changed(self):
        """閫夋嫨鏀瑰彉鏃舵洿鏂板睘鎬ч潰鏉?""
        logger.debug("閫夋嫨鏀瑰彉")
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
            self.properties_panel.set_file(file_data, thumb_path)
            self.properties_panel.set_tag_input_enabled(True)
        else:
            self.properties_panel.clear(keep_tag_input=True)
            self.properties_panel.show_selection_summary(total, len(file_items))

    def load_files_by_tag(self, tag_id):
        """鍔犺浇鏍囩鏂囦欢"""
        logger.info(f"鍔犺浇鏍囩鏂囦欢: tag_id={tag_id}")
        self.current_tag_id = tag_id
        self.current_folder_path = None
        self.path_edit.clear()
        
        # 璁剧疆鏁版嵁婧愪负鍏ㄥ眬鑼冨洿
        self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
        logger.info("鏁版嵁婧愬垏鎹㈠埌鍏ㄥ眬鑼冨洿锛堟爣绛剧瓫閫夛級")
        
        if tag_id == -1:
            files = self.db.get_all_files()
            self.setWindowTitle("Python Bridge - 鎵€鏈夋枃浠?)
        else:
            files = self.db.get_files_by_tag(tag_id)
            self.setWindowTitle(f"Python Bridge - 鏍囩绛涢€?)
        
        self.file_list.load_files(files)
        self._apply_active_filters()

    def search_files(self, keyword):
        """鎼滅储鏂囦欢"""
        logger.info(f"鎼滅储鏂囦欢: {keyword}")
        if not keyword:
            return

        # 璁剧疆鏁版嵁婧愪负鍏ㄥ眬鑼冨洿
        self.data_source.set_scope(DataSourceManager.SCOPE_GLOBAL)
        logger.info("鏁版嵁婧愬垏鎹㈠埌鍏ㄥ眬鑼冨洿锛堟悳绱級")
        
        # 娉ㄦ剰锛氫笉鏇存柊鍦板潃鏍忥紝淇濇寔鐙珛鎬?
        self.statusBar().showMessage(f"姝ｅ湪鎼滅储: {keyword}...")
        self.setWindowTitle(f"Python Bridge - 鎼滅储: {keyword}")
        
        # 1. 鎸夋枃浠跺悕鎼滅储
        files = self.db.search_files_by_name(keyword)
        
        # 2. 鎸夋爣绛惧悕鎼滅储 (鍚堝苟缁撴灉)
        tag_files = self.db.search_files_by_tag_name(keyword)
        
        # 鍚堝苟鍘婚噸
        seen_ids = {f['id'] for f in files}
        for f in tag_files:
            if f['id'] not in seen_ids:
                files.append(f)
                seen_ids.add(f['id'])
        
        self.file_list.load_files(files)
        self.setWindowTitle(f"鎼滅储: {keyword} ({len(files)} 涓粨鏋?")
        
        # 鏇存柊绛涢€夌粺璁?
        self.properties_panel.update_filter_stats(files)
        self._apply_active_filters()

    def assign_tag_to_selection(self):
        """涓洪€変腑鏂囦欢娣诲姞鏍囩"""
        logger.info("涓洪€変腑鏂囦欢娣诲姞鏍囩")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return

        tags = self.db.get_all_tags()
        if not tags:
            QMessageBox.warning(self, "鎻愮ず", "璇峰厛鍒涘缓鏍囩")
            return
        
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "閫夋嫨鏍囩", "灏嗛€変腑鏂囦欢娣诲姞鍒?", tag_names, 0, False)
        
        if ok and tag_name:
            tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.link_file_tag(file_data['id'], tag_id)
                self.db.link_file_tag(file_data['id'], tag_id)
            self.statusBar().showMessage(f"宸叉坊鍔犳爣绛?'{tag_name}' 鍒?{len(selected_items)} 涓枃浠?)

    def batch_add_tags(self):
        """鎵归噺娣诲姞鏍囩"""
        logger.info("鎵归噺娣诲姞鏍囩")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return
        
        tags = self.db.get_all_tags()
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "鎵归噺娣诲姞鏍囩", "閫夋嫨鏍囩:", tag_names, 0, False)
        
        if ok and tag_name:
            tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.link_file_tag(file_data['id'], tag_id)
            self.refresh_current_view()

    def batch_remove_tags(self):
        """鎵归噺绉婚櫎鏍囩"""
        logger.info("鎵归噺绉婚櫎鏍囩")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return
        
        tags = self.db.get_all_tags()
        tag_names = [t['name'] for t in tags]
        tag_name, ok = QInputDialog.getItem(self, "鎵归噺绉婚櫎鏍囩", "閫夋嫨鏍囩:", tag_names, 0, False)
        
        if ok and tag_name:
            tag_id = next(t['id'] for t in tags if t['name'] == tag_name)
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.remove_file_tag(file_data['id'], tag_id)
            self.refresh_current_view()

    def batch_delete_files(self):
        """鎵归噺鍒犻櫎鏂囦欢璁板綍"""
        logger.info("鎵归噺鍒犻櫎鏂囦欢璁板綍")
        selected_items = self.file_list.selectedItems()
        if not selected_items: return
        
        reply = QMessageBox.question(self, "纭鍒犻櫎", f"纭畾瑕佸垹闄?{len(selected_items)} 涓枃浠惰褰曞悧锛?,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                self.db.delete_file(file_data['id'])
            self.refresh_current_view()

    def _handle_go_up(self):
        """澶勭悊閫€鏍奸敭杩斿洖涓婁竴绾?""
        if self.current_folder_path:
            parent = os.path.dirname(self.current_folder_path)
            if parent and os.path.exists(parent):
                self.load_path(parent)
    
    def _handle_inline_rename(self, old_path, new_name):
        """澶勭悊鍐呭祵閲嶅懡鍚?""
        try:
            directory = os.path.dirname(old_path)
            new_path = os.path.join(directory, new_name)
            
            if os.path.exists(new_path):
                QMessageBox.warning(self, "閿欒", "鏂囦欢鍚嶅凡瀛樺湪")
                self.refresh_current_view()
                return
                
            # 閲嶅懡鍚嶆枃浠?
            os.rename(old_path, new_path)
            
            # 鏇存柊鏁版嵁搴?
            self.db.rename_file(old_path, new_path, new_name)
            
            # 鍒锋柊鍒楄〃
            self.refresh_current_view()
            
        except Exception as e:
            QMessageBox.warning(self, "閿欒", f"閲嶅懡鍚嶅け璐? {e}")
            self.refresh_current_view()

    def on_rating_changed(self, file_id, rating):
        """璇勭骇鏀瑰彉"""
        logger.info(f"璇勭骇鏀瑰彉: file_id={file_id}, rating={rating}")
        if file_id == -1:
            self.set_selected_rating(rating)
        else:
            self.db.set_file_rating(file_id, rating)
            self.refresh_current_view()

    def on_color_changed(self, file_id, color):
        """棰滆壊鏀瑰彉"""
        logger.info(f"棰滆壊鏀瑰彉: file_id={file_id}, color={color}")
        self.db.set_file_label_color(file_id, color)
        self.refresh_current_view()

    def on_pin_toggled(self, file_id, is_pinned):
        """缃《鍒囨崲"""
        logger.info(f"缃《鍒囨崲: file_id={file_id}, is_pinned={is_pinned}")
        if is_pinned:
            self.db.pin_file(file_id)
        else:
            self.db.unpin_file(file_id)
        self.refresh_current_view()

    def on_tag_added(self, file_id, tag_id):
        """鏍囩娣诲姞"""
        logger.info(f"鏍囩娣诲姞: file_id={file_id}, tag_id={tag_id}")
        self.db.link_file_tag(file_id, tag_id)
        self.refresh_current_view()

    def on_tag_removed(self, file_id, tag_id):
        """鏍囩绉婚櫎"""
        logger.info(f"鏍囩绉婚櫎: file_id={file_id}, tag_id={tag_id}")
        self.db.remove_file_tag(file_id, tag_id)
        self.refresh_current_view()
    
    def on_tag_created(self, tag_name):
        """鏍囩鍒涘缓"""
        logger.info(f"鏍囩鍒涘缓: {tag_name}")
        tag_id = self.db.create_tag(tag_name)
        if tag_id:
            self.properties_panel.refresh_tag_filters(self.current_tag_id)
            self.properties_panel.refresh_tag_suggestions()
            selected_items = self.file_list.selectedItems()
            if selected_items:
                for item in selected_items:
                    file_data = item.data(Qt.ItemDataRole.UserRole)
                    self.db.link_file_tag(file_data['id'], tag_id)
                self.refresh_current_view()
                self.on_selection_changed()

    def on_quick_tag_requested(self, tag_name):
        """蹇€熸爣绛捐姹?""
        logger.info(f"蹇€熸爣绛捐姹? {tag_name}")
        tag_name = tag_name.strip()
        if not tag_name: return

        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "鎻愮ず", "璇峰厛閫夋嫨鑷冲皯涓€涓枃浠?)
            return

        if len(selected_items) > 10:
            reply = QMessageBox.question(self, "鎻愮ず", "鎵归噺娣诲姞鏍囩, 鏄惁缁х画", 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        file_items = [item for item in selected_items if not item.data(Qt.ItemDataRole.UserRole + 1)]
        tag_id = self.db.create_tag(tag_name)
        
        updated = 0
        for item in file_items:
            file_data = item.data(Qt.ItemDataRole.UserRole)
            self.db.link_file_tag(file_data['id'], tag_id)
            updated += 1

        QMessageBox.information(self, "瀹屾垚", f"宸蹭负 {updated} 涓枃浠舵坊鍔犳爣绛?'{tag_name}'")
        self.properties_panel.refresh_tag_suggestions()
        self.properties_panel.refresh_tag_filters(self.current_tag_id)
        self.on_selection_changed()

    def on_filter_changed(self, filters):
        """绛涢€夊櫒鏀瑰彉"""
        logger.debug(f"绛涢€夊櫒鏀瑰彉: {filters}")
        self.file_list.apply_filters(filters)

    def set_selected_color(self, color):
        """璁剧疆閫変腑鏂囦欢/鏂囦欢澶归鑹?""
        logger.info(f"========== 璁剧疆閫変腑椤归鑹? {color} ==========")
        selected_items = self.file_list.selectedItems()
        logger.info(f"閫変腑椤规暟閲? {len(selected_items)}")
        if selected_items:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if file_data and 'path' in file_data:
                    logger.info(f"姝ｅ湪璁剧疆棰滆壊: {file_data['path']}")
                    # 浣跨敤鏁版嵁婧愮鐞嗗櫒锛堟敮鎸佹枃浠跺拰鏂囦欢澶癸級
                    result = self.data_source.set_color(file_data['path'], color)
                    logger.info(f"璁剧疆棰滆壊缁撴灉: {result}")
            logger.info("寮€濮嬪埛鏂拌鍥?..")
            self.refresh_current_view()
            logger.info("瑙嗗浘鍒锋柊瀹屾垚")

    def set_selected_rating(self, rating):
        """璁剧疆閫変腑鏂囦欢/鏂囦欢澶硅瘎绾?""
        logger.info(f"========== 璁剧疆閫変腑椤硅瘎绾? {rating} ==========")
        selected_items = self.file_list.selectedItems()
        logger.info(f"閫変腑椤规暟閲? {len(selected_items)}")
        if selected_items:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if file_data and 'path' in file_data:
                    logger.info(f"姝ｅ湪璁剧疆璇勭骇: {file_data['path']}")
                    # 浣跨敤鏁版嵁婧愮鐞嗗櫒锛堟敮鎸佹枃浠跺拰鏂囦欢澶癸級
                    result = self.data_source.set_rating(file_data['path'], rating)
                    logger.info(f"璁剧疆璇勭骇缁撴灉: {result}")
            logger.info("寮€濮嬪埛鏂拌鍥?..")
            self.refresh_current_view()
            logger.info("瑙嗗浘鍒锋柊瀹屾垚")

    def toggle_selected_pin(self):
        """鍒囨崲閫変腑鏂囦欢/鏂囦欢澶圭疆椤剁姸鎬?""
        logger.info("========== 鍒囨崲閫変腑椤圭疆椤剁姸鎬?==========")
        selected_items = self.file_list.selectedItems()
        logger.info(f"閫変腑椤规暟閲? {len(selected_items)}")
        if selected_items:
            for item in selected_items:
                file_data = item.data(Qt.ItemDataRole.UserRole)
                if file_data and 'path' in file_data:
                    is_pinned = file_data.get('is_pinned', 0)
                    logger.info(f"姝ｅ湪鍒囨崲缃《: {file_data['path']}, 褰撳墠鐘舵€? {is_pinned}")
                    # 浣跨敤鏁版嵁婧愮鐞嗗櫒锛堟敮鎸佹枃浠跺拰鏂囦欢澶癸級
                    result = self.data_source.set_pin(file_data['path'], not is_pinned)
                    logger.info(f"鍒囨崲缃《缁撴灉: {result}")
            logger.info("寮€濮嬪埛鏂拌鍥?..")
            self.refresh_current_view()
            logger.info("瑙嗗浘鍒锋柊瀹屾垚")
        else:
            logger.warning("娌℃湁閫変腑浠讳綍椤圭洰锛?)

    def _apply_active_filters(self):
        """搴旂敤褰撳墠婵€娲荤殑绛涢€夊櫒"""
        filters = self.properties_panel.get_filters()
        self.file_list.apply_filters(filters)

    def switch_view_mode(self, mode):
        """鍒囨崲瑙嗗浘妯″紡"""
        logger.info(f"鍒囨崲瑙嗗浘妯″紡: {mode}")
        self.current_view_mode = mode
        self.file_list.set_view_mode(mode)

    def refresh_current_view(self):
        """鍒锋柊褰撳墠瑙嗗浘"""
        logger.info("鍒锋柊褰撳墠瑙嗗浘")
        if self.current_folder_path:
            self.load_path(self.current_folder_path)
        elif self.current_tag_id != -1:
            self.load_files_by_tag(self.current_tag_id)
        else:
            self.load_files_by_tag(-1)

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("鍚姩 Python Bridge 搴旂敤绋嬪簭")
    logger.info("=" * 60)
    
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    
    logger.info("涓荤獥鍙ｅ凡鏄剧ず")
    sys.exit(app.exec())


# ===================|===================
# 文件名: properties_panel.py
import os
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QScrollArea, QFrame, QPushButton, QLineEdit,
                             QCheckBox, QGroupBox, QTabWidget, QFormLayout, QMenu,
                             QRadioButton, QTreeWidget, QTreeWidgetItem, QHeaderView)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QColor, QBrush
from rating_widget import RatingWidget

class MetadataPanel(QWidget):
    """鍏冩暟鎹潰鏉?""
    tag_submitted = pyqtSignal(str)
    rating_changed = pyqtSignal(int, int)  # file_id, rating

    def __init__(self):
        super().__init__()
        self.current_file_id = None
        self.tag_buttons = []
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 棰勮鍥?        self.preview_label = QLabel()
        self.preview_label.setFixedSize(200, 200)
        self.preview_label.setScaledContents(True)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #444; background-color: #222;")
        layout.addWidget(self.preview_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # 鏂囦欢鍚?        self.filename_label = QLabel("鏈€夋嫨鏂囦欢")
        self.filename_label.setWordWrap(True)
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filename_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout.addWidget(self.filename_label)
        
        # 璇︾粏淇℃伅琛ㄥ崟
        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        # 璇勭骇
        self.rating_widget = RatingWidget(rating=0, editable=True, star_size=14)
        self.rating_widget.setFixedHeight(20)
        self.rating_widget.setEnabled(False)
        self.rating_widget.rating_changed.connect(self._on_rating_changed)
        rating_row = QWidget()
        rating_layout = QHBoxLayout(rating_row)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.addWidget(self.rating_widget)
        rating_layout.addStretch()
        form_layout.addRow("璇勭骇:", rating_row)

        # 鏍囩
        self.tags_label = QLabel("鏃犳爣绛?)
        self.tags_label.setWordWrap(True)
        form_layout.addRow("鏍囩:", self.tags_label)
        
        self.size_label = QLabel("-")
        self.created_label = QLabel("-")
        self.modified_label = QLabel("-")
        self.type_label = QLabel("-")
        self.path_label = QLabel("-")
        self.path_label.setWordWrap(True)
        
        form_layout.addRow("澶у皬:", self.size_label)
        form_layout.addRow("绫诲瀷:", self.type_label)
        form_layout.addRow("鍒涘缓鏃堕棿:", self.created_label)
        form_layout.addRow("淇敼鏃堕棿:", self.modified_label)
        form_layout.addRow("璺緞:", self.path_label)
        
        layout.addLayout(form_layout)

        # 蹇€熸爣绛捐緭鍏?        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("杈撳叆鏍囩锛屾寜鍥炶溅蹇€熸坊鍔犫€?)
        self.tag_input.returnPressed.connect(self._on_tag_input_return)
        self.tag_input.setEnabled(False)
        layout.addWidget(self.tag_input)

        history_label = QLabel("鍘嗗彶鏍囩锛?)
        history_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(history_label)

        self.tag_scroll = QScrollArea()
        self.tag_scroll.setWidgetResizable(True)
        self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tag_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tag_scroll.setFixedHeight(70)

        self.tag_container = QWidget()
        self.tag_layout = QHBoxLayout(self.tag_container)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(6)
        self.tag_layout.addStretch()

        self.tag_scroll.setWidget(self.tag_container)
        layout.addWidget(self.tag_scroll)

        layout.addStretch()
        
    def update_info(self, file_data, thumb_path, tags=None):
        if not file_data:
            self.clear(disable_tag_input=False)
            return
        
        self.current_file_id = file_data['id']
        self.set_tag_input_enabled(True)
        self.rating_widget.setEnabled(True)
            
        # 鏇存柊棰勮
        if thumb_path:
            self.preview_label.setPixmap(QPixmap(thumb_path))
        else:
            self.preview_label.setText("馃搫")
            
        # 鏇存柊鍩烘湰淇℃伅
        filename = file_data.get('filename') or os.path.basename(file_data['path'])
        self.filename_label.setText(filename)
        self.path_label.setText(file_data['path'])
        self.rating_widget.set_rating(file_data.get('rating', 0))

        if tags:
            tag_names = [t['name'] for t in tags]
            self.tags_label.setText(", ".join(tag_names))
        else:
            self.tags_label.setText("鏃犳爣绛?)
        
        # 鑾峰彇鏂囦欢绯荤粺淇℃伅
        try:
            stats = os.stat(file_data['path'])
            self.size_label.setText(self._format_size(stats.st_size))
            self.created_label.setText(self._format_time(stats.st_ctime))
            self.modified_label.setText(self._format_time(stats.st_mtime))
            self.type_label.setText(os.path.splitext(file_data['filename'])[1].upper() or "鏂囦欢")
        except:
            self.size_label.setText("-")
            
    def clear(self, disable_tag_input=True):
        self.current_file_id = None
        self.preview_label.clear()
        self.filename_label.setText("鏈€夋嫨鏂囦欢")
        self.rating_widget.setEnabled(False)
        self.rating_widget.set_rating(0)
        self.tags_label.setText("鏃犳爣绛?)
        self.size_label.setText("-")
        self.created_label.setText("-")
        self.modified_label.setText("-")
        self.path_label.setText("-")
        if disable_tag_input:
            self.set_tag_input_enabled(False)

    def set_tag_input_enabled(self, enabled):
        self.tag_input.setEnabled(enabled)
        for btn in self.tag_buttons:
            btn.setEnabled(enabled)
        if not enabled:
            self.tag_input.clear()

    def show_selection_summary(self, total_count, file_count):
        if total_count == 0:
            self.filename_label.setText("鏈€夋嫨鏂囦欢")
            self.rating_widget.setEnabled(False)
        else:
            summary = f"宸查€夋嫨 {total_count} 涓」鐩?
            if file_count == 0:
                summary += "锛堝潎涓烘枃浠跺す锛屾棤娉曟坊鍔犳爣绛撅級"
                self.rating_widget.setEnabled(False)
            elif file_count < total_count:
                summary += f"锛堝寘鍚?{file_count} 涓枃浠讹級"
                self.rating_widget.setEnabled(True)
            else:
                self.rating_widget.setEnabled(True)
            self.filename_label.setText(summary)
            self.rating_widget.set_rating(0)

    def set_tag_suggestions(self, tags):
        self._clear_layout(self.tag_layout)
        self.tag_buttons = []
        for tag in tags:
            btn = QPushButton(tag['name'])
            btn.setProperty('tag_name', tag['name'])
            btn.clicked.connect(lambda _, name=tag['name']: self.tag_submitted.emit(name))
            self.tag_layout.addWidget(btn)
            self.tag_buttons.append(btn)
        self.tag_layout.addStretch()

    def _on_tag_input_return(self):
        text = self.tag_input.text().strip()
        if text:
            self.tag_submitted.emit(text)
            self.tag_input.clear()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _on_rating_changed(self, rating):
        if self.current_file_id is not None:
            self.rating_changed.emit(self.current_file_id, rating)
        else:
            self.rating_changed.emit(-1, rating)

    def _format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _format_time(self, timestamp):
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')


class KeywordsPanel(QWidget):
    """鍏抽敭瀛楋紙鏍囩锛夐潰鏉?""
    tag_added = pyqtSignal(int, int)
    tag_removed = pyqtSignal(int, int)
    tag_created = pyqtSignal(str)
    
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.current_file_id = None
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        input_layout = QHBoxLayout()
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("杈撳叆鏍囩鍚嶇О锛屾寜鍥炶溅娣诲姞...")
        self.tag_input.returnPressed.connect(self._on_input_return)
        input_layout.addWidget(self.tag_input)
        layout.addLayout(input_layout)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.tags_container = QWidget()
        self.tags_layout = QVBoxLayout(self.tags_container)
        self.tags_layout.setSpacing(5)
        self.tags_layout.addStretch()
        
        scroll.setWidget(self.tags_container)
        layout.addWidget(scroll)
        
    def update_tags(self, file_id):
        self.current_file_id = file_id
        self.tag_input.setEnabled(file_id is not None)
        
        while self.tags_layout.count() > 1:
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        if not file_id:
            return
            
        all_tags = self.db.get_all_tags()
        file_tags = self.db.get_file_tags(file_id)
        file_tag_ids = [t['id'] for t in file_tags]
        
        for tag in all_tags:
            checkbox = QCheckBox(tag['name'])
            checkbox.setProperty('tag_id', tag['id'])
            checkbox.setChecked(tag['id'] in file_tag_ids)
            checkbox.stateChanged.connect(self._on_tag_checked)
            self.tags_layout.insertWidget(self.tags_layout.count()-1, checkbox)
            
    def _on_input_return(self):
        text = self.tag_input.text().strip()
        if text and self.current_file_id:
            self.tag_created.emit(text)
            self.tag_input.clear()
            
    def _on_tag_checked(self, state):
        if not self.current_file_id:
            return
        checkbox = self.sender()
        tag_id = checkbox.property('tag_id')
        
        if state == Qt.CheckState.Checked.value:
            self.tag_added.emit(self.current_file_id, tag_id)
        else:
            self.tag_removed.emit(self.current_file_id, tag_id)


class FilterPanel(QWidget):
    """绛涢€夊櫒闈㈡澘锛圓dobe Bridge椋庢牸鐨勫垎闈㈢瓫閫夛級"""
    filter_changed = pyqtSignal(dict)
    
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.filters = {
            'extensions': set(),
            'tags': set(),
            'rating': set(),
            'color': set(),
            'date': set()
        }
        self.all_files = []
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 浣跨敤TreeWidget瀹炵幇鍒嗛潰绛涢€?        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(15)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        
        # 鍒濆鍖栧悇涓垎绫昏妭鐐?        self.sections = {}
        self._create_section("extensions", "鏂囦欢绫诲瀷")
        self._create_section("tags", "鍏抽敭瀛?)
        self._create_section("date", "鍒涘缓鏃ユ湡")
        self._create_section("rating", "璇勭骇")
        self._create_section("color", "棰滆壊鏍囩")
        
        # 搴曢儴鎸夐挳
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("閲嶇疆绛涢€?)
        reset_btn.clicked.connect(self.reset_filters)
        btn_layout.addWidget(reset_btn)
        layout.addLayout(btn_layout)

    def _create_section(self, key, title):
        item = QTreeWidgetItem(self.tree)
        item.setText(0, title)
        item.setExpanded(True)
        self.sections[key] = item
        return item

    def update_facets(self, files):
        """鏇存柊绛涢€夐潰鏉跨殑缁熻鏁版嵁"""
        self.all_files = files
        self.tree.blockSignals(True)
        
        # 缁熻鏁版嵁
        counts = {
            'extensions': {},
            'tags': {},
            'rating': {},
            'color': {},
            'date': {}
        }
        
        # 棰勫畾涔夋槧灏?        rating_map = {5: "鈽呪槄鈽呪槄鈽?, 4: "鈽呪槄鈽呪槄", 3: "鈽呪槄鈽?, 2: "鈽呪槄", 1: "鈽?, 0: "鏃犺瘎绾?}
        color_map = {'red': "馃敶 绾㈣壊", 'yellow': "馃煛 榛勮壊", 'green': "馃煝 缁胯壊", 
                     'blue': "馃數 钃濊壊", 'purple': "馃煟 绱壊", 'none': "鈿?鏃犻鑹?}
        
        # 鑾峰彇鎵€鏈夋爣绛?        all_tags = {t['id']: t['name'] for t in self.db.get_all_tags()}
        
        for f in files:
            # 鎵╁睍鍚?            ext = f.get('extension', '').upper() or "鏃犳墿灞曞悕"
            counts['extensions'][ext] = counts['extensions'].get(ext, 0) + 1
            
            # 璇勭骇
            r = f.get('rating', 0)
            counts['rating'][r] = counts['rating'].get(r, 0) + 1
            
            # 棰滆壊
            c = f.get('label_color', 'none') or 'none'
            counts['color'][c] = counts['color'].get(c, 0) + 1
            
            # 鏃ユ湡
            ts = f.get('created_time') or f.get('ctime') 
            if ts:
                date_str = datetime.fromtimestamp(ts).strftime('%Y/%m/%d')
                counts['date'][date_str] = counts['date'].get(date_str, 0) + 1
        
        # 鏇存柊UI
        self._update_section_items('extensions', counts['extensions'])
        self._update_section_items('rating', counts['rating'], label_map=rating_map)
        self._update_section_items('color', counts['color'], label_map=color_map)
        self._update_section_items('date', counts['date'])
        
        # 鏍囩缁熻
        if files:
            file_ids = [f['id'] for f in files]
            tag_counts = self._get_tag_counts(file_ids)
            tag_counts_named = {all_tags.get(tid, str(tid)): count for tid, count in tag_counts.items() if tid in all_tags}
            self._update_section_items('tags', tag_counts_named)
        else:
            self._update_section_items('tags', {})

        self.tree.blockSignals(False)

    def _get_tag_counts(self, file_ids):
        """鑾峰彇涓€缁勬枃浠剁殑鏍囩缁熻"""
        if not file_ids:
            return {}
        try:
            self.db.connect()
            cursor = self.db.conn.cursor()
            placeholders = ','.join(['?'] * len(file_ids))
            cursor.execute(f'''
                SELECT tag_id, COUNT(*) 
                FROM file_tags 
                WHERE file_id IN ({placeholders})
                GROUP BY tag_id
            ''', file_ids)
            return dict(cursor.fetchall())
        except Exception as e:
            print(f"Error counting tags: {e}")
            return {}
        finally:
            self.db.close()

    def _update_section_items(self, key, counts, label_map=None):
        parent = self.sections[key]
        
        # 鑾峰彇鐜版湁items鍙婂叾鐘舵€?        existing_items = {}
        for i in range(parent.childCount()):
            item = parent.child(i)
            val = item.data(0, Qt.ItemDataRole.UserRole)
            existing_items[val] = item
            
        # 鏇存柊鎴栨坊鍔?        seen_values = set()
        
        # 鎺掑簭
        sorted_keys = sorted(counts.keys(), reverse=(key=='date'))
        
        for val in sorted_keys:
            count = counts[val]
            seen_values.add(val)
            
            label = label_map.get(val, str(val)) if label_map else str(val)
            text = f"{label} ({count})"
            
            if val in existing_items:
                item = existing_items[val]
                item.setText(0, text)
            else:
                item = QTreeWidgetItem(parent)
                item.setText(0, text)
                item.setData(0, Qt.ItemDataRole.UserRole, val)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
        
        # 绉婚櫎涓嶅啀瀛樺湪鐨勯」
        for val, item in existing_items.items():
            if val not in seen_values:
                parent.removeChild(item)

    def _on_item_changed(self, item, column):
        """褰撳嬀閫夌姸鎬佹敼鍙樻椂"""
        parent = item.parent()
        if not parent:
            return
        
        # 鎵惧埌瀵瑰簲鐨剆ection key
        section_key = None
        for k, v in self.sections.items():
            if v == parent:
                section_key = k
                break
        
        if section_key:
            val = item.data(0, Qt.ItemDataRole.UserRole)
            if item.checkState(0) == Qt.CheckState.Checked:
                self.filters[section_key].add(val)
            else:
                self.filters[section_key].discard(val)
            
            self.filter_changed.emit(self.get_filters())

    def reset_filters(self):
        self.tree.blockSignals(True)
        for key, parent in self.sections.items():
            self.filters[key].clear()
            for i in range(parent.childCount()):
                parent.child(i).setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.filter_changed.emit(self.get_filters())

    def get_filters(self):
        return {k: set(v) for k, v in self.filters.items()}

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()


class PropertiesPanel(QTabWidget):
    """涓诲彸渚ч潰鏉匡紙Tab缁撴瀯锛?""
    rating_changed = pyqtSignal(int, int)
    color_changed = pyqtSignal(int, str)
    pin_toggled = pyqtSignal(int, bool)
    tag_added = pyqtSignal(int, int)
    tag_removed = pyqtSignal(int, int)
    tag_created = pyqtSignal(str)
    filter_changed = pyqtSignal(dict)
    quick_tag_requested = pyqtSignal(str)
    
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.current_file = None
        
        self.meta_panel = MetadataPanel()
        self.keywords_panel = KeywordsPanel(db)
        self.filter_panel = FilterPanel(db)
        
        self.addTab(self.meta_panel, "鍏冩暟鎹?)
        self.addTab(self.keywords_panel, "鍏抽敭瀛?)
        self.addTab(self.filter_panel, "绛涢€夊櫒")
        
        self.keywords_panel.tag_added.connect(self.tag_added)
        self.keywords_panel.tag_removed.connect(self.tag_removed)
        self.keywords_panel.tag_created.connect(self.tag_created)
        self.filter_panel.filter_changed.connect(self.filter_changed)
        self.meta_panel.tag_submitted.connect(self.quick_tag_requested)
        self.meta_panel.rating_changed.connect(lambda fid, rating: self.rating_changed.emit(fid, rating))
        self.refresh_tag_suggestions()
        
    def set_file(self, file_data, thumb_path=None):
        self.current_file = file_data
        tags = self.db.get_file_tags(file_data['id']) if file_data else None
        self.meta_panel.update_info(file_data, thumb_path, tags)
        
        if file_data:
            self.keywords_panel.update_tags(file_data['id'])
        else:
            self.keywords_panel.update_tags(None)
            
    def clear(self, keep_tag_input=False):
        self.current_file = None
        self.meta_panel.clear(disable_tag_input=not keep_tag_input)
        self.keywords_panel.update_tags(None)

    def update_filter_stats(self, files):
        """鏇存柊绛涢€夊櫒缁熻淇℃伅"""
        self.filter_panel.update_facets(files)

    def get_filters(self):
        return self.filter_panel.get_filters()

    def refresh_tag_suggestions(self):
        tags = self.db.get_all_tags()
        self.meta_panel.set_tag_suggestions(tags)

    def set_tag_input_enabled(self, enabled):
        self.meta_panel.set_tag_input_enabled(enabled)

    def show_selection_summary(self, total_count, file_count):
        self.meta_panel.show_selection_summary(total_count, file_count)


# ===================|===================
# 文件名: rating_widget.py
"""
璇勭骇缁勪欢 - 鏄熺骇鏄剧ず鍜岀紪杈?

鏀寔锛?
- 鏄剧ず 0-5 鏄熻瘎绾?
- 鐐瑰嚮璁剧疆璇勭骇
- 鎮仠棰勮
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPointF
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QPen, QPolygonF

class RatingWidget(QWidget):
    """鏄熺骇璇勫垎缁勪欢"""
    rating_changed = pyqtSignal(int)  # 璇勭骇鏀瑰彉淇″彿
    
    def __init__(self, rating=0, max_rating=5, editable=True, star_size=16, color=None):
        super().__init__()
        self.rating = rating
        self.max_rating = max_rating
        self.editable = editable
        self.star_size = star_size
        self.hover_rating = 0
        self.clear_icon_size = star_size
        self.spacing = 5
        self.color = color  # 棰滆壊鏍囩
        
        # 璁＄畻鎬诲搴? 娓呴櫎鍥炬爣 + 闂磋窛 + 鏄熸槦鎬诲
        total_width = self.clear_icon_size + self.spacing + (star_size * max_rating + 5 * (max_rating - 1))
        self.setFixedSize(total_width, star_size)
        self.setMouseTracking(True)
    
    def set_rating(self, rating):
        """璁剧疆璇勭骇"""
        if 0 <= rating <= self.max_rating:
            self.rating = rating
            self.update()
    
    def set_color(self, color):
        """璁剧疆棰滆壊鏍囩"""
        self.color = color
        self.update()
    
    def get_rating(self):
        """鑾峰彇褰撳墠璇勭骇"""
        return self.rating
    
    def paintEvent(self, event):
        """缁樺埗鏄熸槦鍜屾竻闄ゆ寜閽?""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 缁樺埗娓呴櫎鎸夐挳 (馃毇)
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        painter.setBrush(Qt.GlobalColor.transparent)
        
        # 绠€鍗曠殑绂佹绗﹀彿
        cx = self.clear_icon_size / 2
        cy = self.star_size / 2
        r = self.clear_icon_size / 2 - 2
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawLine(QPointF(cx - r/1.5, cy + r/1.5), QPointF(cx + r/1.5, cy - r/1.5))
        
        # 缁樺埗鏄熸槦
        start_x = self.clear_icon_size + self.spacing
        
        # 浣跨敤鎮仠璇勭骇鎴栧疄闄呰瘎绾?
        display_rating = self.hover_rating if self.hover_rating > 0 else self.rating
        
        for i in range(self.max_rating):
            x = start_x + i * (self.star_size + 5)
            
            if i < display_rating:
                # 濉厖鏄熸槦 - 浣跨敤棰滆壊鏍囩棰滆壊鎴栭粯璁ら噾鑹?
                if self.color:
                    painter.setBrush(QColor(self.color))
                    painter.setPen(QPen(QColor(self.color).darker(120), 1))
                else:
                    painter.setBrush(QColor(255, 200, 0))  # 閲戣壊
                    painter.setPen(QPen(QColor(200, 150, 0), 1))
            else:
                # 绌哄績鏄熸槦
                painter.setBrush(Qt.GlobalColor.transparent)
                painter.setPen(QPen(QColor(180, 180, 180), 1))
            
            self._draw_star(painter, x, 0, self.star_size)
    
    def _draw_star(self, painter, x, y, size):
        """缁樺埗浜旇鏄?""
        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF
        import math
        
        points = []
        center_x = x + size / 2
        center_y = y + size / 2
        outer_radius = size / 2
        inner_radius = size / 5
        
        for i in range(10):
            angle = math.pi / 2 - (2 * math.pi * i / 10)
            radius = outer_radius if i % 2 == 0 else inner_radius
            px = center_x + radius * math.cos(angle)
            py = center_y - radius * math.sin(angle)
            points.append(QPointF(px, py))
        
        painter.drawPolygon(QPolygonF(points))
    
    def mousePressEvent(self, event: QMouseEvent):
        """榧犳爣鐐瑰嚮璁剧疆璇勭骇"""
        if self.editable and event.button() == Qt.MouseButton.LeftButton:
            x = event.pos().x()
            
            # 妫€鏌ユ槸鍚︾偣鍑讳簡娓呴櫎鎸夐挳
            if x < self.clear_icon_size + self.spacing / 2:
                rating = 0
            else:
                rating = self._get_rating_from_pos(x)
                
            if rating != self.rating:
                self.rating = rating
                self.rating_changed.emit(rating)
                self.update()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """榧犳爣鎮仠棰勮"""
        if self.editable:
            x = event.pos().x()
            if x < self.clear_icon_size + self.spacing / 2:
                self.hover_rating = 0 # 鎮仠鍦ㄦ竻闄ゆ寜閽笂
            else:
                self.hover_rating = self._get_rating_from_pos(x)
            self.update()
    
    def leaveEvent(self, event):
        """榧犳爣绂诲紑"""
        self.hover_rating = 0
        self.update()
    
    def _get_rating_from_pos(self, x):
        """鏍规嵁榧犳爣浣嶇疆璁＄畻璇勭骇"""
        start_x = self.clear_icon_size + self.spacing
        if x < start_x: return 0
        
        rel_x = x - start_x
        star_width = self.star_size + 5
        rating = min(int(rel_x / star_width) + 1, self.max_rating)
        return max(0, rating)


class StarRatingDelegate:
    """鐢ㄤ簬鍦ㄥ垪琛ㄤ腑鏄剧ず鏄熺骇鐨勮緟鍔╃被"""
    
    @staticmethod
    def create_rating_widget(rating, editable=False, star_size=12):
        """鍒涘缓璇勭骇缁勪欢"""
        return RatingWidget(rating, editable=editable, star_size=star_size)
    
    @staticmethod
    def get_rating_text(rating):
        """鑾峰彇璇勭骇鏂囨湰琛ㄧず"""
        if rating == 0:
            return "鏈瘎绾?
        return "鈽? * rating + "鈽? * (5 - rating)


# ===================|===================
# 文件名: search_bar.py
"""
鎼滅储鏍忕粍浠?

鏀寔鏂囦欢鍚嶅拰鏍囩鎼滅储
"""

from PyQt6.QtWidgets import QLineEdit, QCompleter
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence


class SearchBar(QLineEdit):
    """鎼滅储鏍忕粍浠?""
    search_triggered = pyqtSignal(str)  # 鎼滅储鍏抽敭璇?
    
    def __init__(self):
        super().__init__()
        self.setPlaceholderText("鎼滅储鏂囦欢鍚嶆垨鏍囩... (鎸?Enter 鎼滅储)")
        self.setClearButtonEnabled(True)
        
        # 杩炴帴鍥炶溅閿?
        self.returnPressed.connect(self._on_search)
    
    def _on_search(self):
        """鎵ц鎼滅储"""
        keyword = self.text().strip()
        if keyword:
            self.search_triggered.emit(keyword)
    
    def set_completer_items(self, items):
        """璁剧疆鑷姩琛ュ叏椤?""
        completer = QCompleter(items, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(completer)


# ===================|===================
# 文件名: verify_backend.py
import os
import time
from PIL import Image, ImageDraw
from db_manager import DatabaseManager
from cache_manager import ThumbnailCache, MetadataCache
import psycopg2

def test_backend():
    print("Testing Backend...")
    
    # 1. Setup
    # Note: This requires a running PostgreSQL server.
    print("Attempting to connect to PostgreSQL...")
    try:
        db = DatabaseManager()
        db.connect()
        print("Successfully connected to PostgreSQL.")
    except Exception as e:
        print(f"Skipping DB tests: Could not connect to PostgreSQL ({e})")
        db = None

    # 2. Create Dummy Image
    img_path = os.path.abspath("test_image_verify.jpg")
    # Create an image with some metadata if possible (Pillow doesn't easily write EXIF without extra libs, but we can test basic)
    img = Image.new('RGB', (500, 500), color = 'red')
    img.save(img_path)
    print(f"Created dummy image at {img_path}")

    if db:
        try:
            # 3. Test DB - Add File
            file_id = db.upsert_file(img_path)
            if file_id:
                print(f"Added file, ID: {file_id}")

                # 4. Test DB - Add Tag
                tag_id = db.create_tag("Test Tag")
                print(f"Created tag, ID: {tag_id}")

                # 5. Test DB - Link
                db.link_file_tag(file_id, tag_id)
                print("Linked file to tag")

                # 6. Test DB - Query
                files = db.get_files_by_tag(tag_id)
                assert len(files) >= 1, "Query failed"
                print("Query successful")
                
                # 8. Test Metadata Cache
                meta = MetadataCache(db)
                meta.update_metadata(file_id, img_path)
                metadata = db.get_file_metadata(file_id)
                if metadata:
                    assert metadata['width'] == 500, "Metadata width mismatch"
                    print("Metadata extraction successful")
            else:
                print("Failed to upsert file (maybe permission or DB issue)")

        except Exception as e:
            print(f"DB Test failed: {e}")
        finally:
            db.close()

    # 7. Test Thumbnail Cache
    print("Testing Thumbnail Cache...")
    cache_dir = "test_thumbs_verify"
    cache = ThumbnailCache(cache_dir)
    
    # Image Thumbnail
    thumb_path = cache.get_thumbnail(img_path)
    assert os.path.exists(thumb_path), "Image thumbnail not generated"
    print(f"Image thumbnail generated at {thumb_path}")

    # Video Thumbnail (Mock test)
    # We create a dummy file with .mp4 extension. ffmpeg will fail, but we check if it handles the error gracefully.
    video_path = os.path.abspath("test_video_verify.mp4")
    with open(video_path, 'w') as f:
        f.write("dummy video content")
    
    print("Testing Video Thumbnail (Expect FFmpeg failure/warning)...")
    thumb_path_video = cache.get_thumbnail(video_path)
    if thumb_path_video:
        print(f"Video thumbnail generated: {thumb_path_video}")
    else:
        print("Video thumbnail generation failed (expected if ffmpeg missing or invalid file)")

    # Cleanup
    try:
        if os.path.exists(img_path):
            os.remove(img_path)
        if os.path.exists(video_path):
            os.remove(video_path)
        # Don't remove cache dir to allow inspection if needed, or remove it:
        # import shutil
        # if os.path.exists(cache_dir):
        #     shutil.rmtree(cache_dir)
    except Exception as e:
        print(f"Cleanup warning: {e}")
        
    print("Verification finished.")

if __name__ == "__main__":
    test_backend()


# ===================|===================
# 文件名: verify_fix.py
from db_manager import DatabaseManager
import sys

def verify_fix():
    print("Verifying get_all_tags fix...")
    try:
        db = DatabaseManager()
        tags = db.get_all_tags()
        print(f"Success! get_all_tags returned: {type(tags)}")
        print(f"Tags found: {len(tags)}")
        if isinstance(tags, list):
            print("Verification PASSED: Returned a list.")
        else:
            print("Verification FAILED: Did not return a list.")
    except Exception as e:
        print(f"Verification FAILED with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_fix()


