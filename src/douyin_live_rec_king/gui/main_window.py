"""StreamCap-inspired PySide6 shell with functional task and settings pages."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import AppSettings, LiveTask, PlatformType, StreamSource, TaskStatus, VideoQuality
from ..recording.ffmpeg import FFmpegTool, node_status
from ..services.task_manager import TaskManager
from ..utils.paths import resolve_app_path
from .dialogs import TaskDialog
from .log_bridge import LogEmitter, QtLogHandler


class TaskSignalBridge(QObject):
    changed = Signal(object)


class TasksPage(QWidget):
    HEADERS = ["启用", "平台", "显示昵称", "原始地址", "规范地址", "状态", "录制文件", "最后检查"]

    def __init__(self, manager: TaskManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索昵称或地址")
        self.search.textChanged.connect(self.refresh)
        self.view_stack = QStackedWidget()
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_task)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.cards_host)
        self.view_stack.addWidget(self.table)
        self.view_stack.addWidget(scroll)

        actions = QHBoxLayout()
        actions.addWidget(self.search, 1)
        for text, callback in [
            ("添加", self.add_task),
            ("编辑", self.edit_task),
            ("删除", self.delete_task),
            ("刷新", manager.refresh_now),
            ("启动监控", manager.start_monitoring),
            ("停止监控", manager.stop_monitoring),
            ("停止录制", self.stop_recording),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        self.view_button = QPushButton("切换卡片")
        self.view_button.clicked.connect(self.toggle_view)
        actions.addWidget(self.view_button)

        layout = QVBoxLayout(self)
        title = QLabel("监控任务")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addLayout(actions)
        layout.addWidget(self.view_stack)
        self.set_view(manager.settings.task_view)
        self.refresh()

    def set_view(self, mode: str) -> None:
        index = 1 if mode == "cards" else 0
        self.view_stack.setCurrentIndex(index)
        self.view_button.setText("切换表格" if index else "切换卡片")

    def toggle_view(self) -> None:
        mode = "cards" if self.view_stack.currentIndex() == 0 else "table"
        self.manager.settings.task_view = mode
        self.manager.update_settings(self.manager.settings)
        self.set_view(mode)
        self.refresh()

    def _filtered_tasks(self) -> list[LiveTask]:
        query = self.search.text().strip().lower()
        if not query:
            return self.manager.tasks()
        return [
            task for task in self.manager.tasks()
            if query in task.display_name.lower()
            or query in task.url.lower()
            or query in (task.canonical_url or "").lower()
        ]

    def refresh(self, *_args) -> None:
        tasks = self._filtered_tasks()
        self.table.setRowCount(0)
        for task in tasks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                "是" if task.enabled else "否", "抖音", task.display_name, task.url,
                task.canonical_url or "", task.status.value, task.recording_file or "",
                task.last_checked_at or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, task.id)
                if column == 5 and task.last_error:
                    item.setToolTip(task.last_error)
                self.table.setItem(row, column, item)
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for task in tasks:
            self.cards_layout.addWidget(self._card(task))

    def _card(self, task: LiveTask) -> QWidget:
        card = QFrame()
        card.setObjectName("taskCard")
        layout = QGridLayout(card)
        title = QLabel(f"{task.display_name} · {task.status.value}")
        title.setStyleSheet("font-size:16px;font-weight:600")
        layout.addWidget(title, 0, 0, 1, 4)
        layout.addWidget(QLabel(task.url), 1, 0, 1, 4)
        layout.addWidget(QLabel(f"最后检查：{task.last_checked_at or '尚未检查'}"), 2, 0, 1, 2)
        for column, (text, callback) in enumerate([
            ("编辑", lambda _=False, tid=task.id: self.edit_task(tid)),
            ("停止录制", lambda _=False, tid=task.id: self.manager.stop_recording(tid)),
            ("打开文件夹", lambda _=False, t=task: self.open_task_folder(t)),
            ("删除", lambda _=False, tid=task.id: self.delete_task(tid)),
        ]):
            button = QPushButton(text)
            button.clicked.connect(callback)
            layout.addWidget(button, 3, column)
        return card

    def selected_task(self) -> LiveTask | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return self.manager.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def add_task(self) -> None:
        dialog = TaskDialog(self)
        if dialog.exec():
            values = dialog.values()
            task = LiveTask(url=str(values.pop("url")))
            task.set_manual_name(str(values.pop("anchor_name")))
            for key, value in values.items():
                setattr(task, key, value)
            self.manager.add_task(task)
            self.refresh()

    def edit_task(self, task_id: str | None = None) -> None:
        task = self.manager.get(task_id) if isinstance(task_id, str) else self.selected_task()
        if not task:
            QMessageBox.information(self, "编辑任务", "请先选择任务。")
            return
        dialog = TaskDialog(self, task)
        if dialog.exec():
            self.manager.update_task(task.id, **dialog.values())
            self.refresh()

    def delete_task(self, task_id: str | None = None) -> None:
        task = self.manager.get(task_id) if isinstance(task_id, str) else self.selected_task()
        if not task:
            QMessageBox.information(self, "删除任务", "请先选择任务。")
            return
        if QMessageBox.question(self, "删除任务", f"确定删除“{task.display_name}”吗？") == QMessageBox.StandardButton.Yes:
            self.manager.delete_task(task.id)
            self.refresh()

    def stop_recording(self) -> None:
        task = self.selected_task()
        if not task or not self.manager.stop_recording(task.id):
            QMessageBox.information(self, "停止录制", "所选任务当前没有录制进程。")

    def open_task_folder(self, task: LiveTask) -> None:
        path = Path(task.recording_file).parent if task.recording_file else resolve_app_path(self.manager.settings.output_directory)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class RecordingsPage(QWidget):
    def __init__(self, manager: TaskManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.list = QListWidget()
        refresh = QPushButton("刷新文件列表")
        refresh.clicked.connect(self.refresh)
        open_dir = QPushButton("打开录制目录")
        open_dir.clicked.connect(self.open_directory)
        buttons = QHBoxLayout()
        buttons.addWidget(refresh)
        buttons.addWidget(open_dir)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        title = QLabel("录制文件")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addLayout(buttons)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        root = resolve_app_path(self.manager.settings.output_directory)
        if root.exists():
            for path in sorted(root.rglob("*"), key=lambda item: item.stat().st_mtime if item.is_file() else 0, reverse=True):
                if path.is_file():
                    item = QListWidgetItem(f"{path.name}    {path.stat().st_size / 1024 / 1024:.1f} MB")
                    item.setToolTip(str(path))
                    self.list.addItem(item)

    def open_directory(self) -> None:
        root = resolve_app_path(self.manager.settings.output_directory)
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))


class SettingsPage(QWidget):
    saved = Signal(object)

    def __init__(self, manager: TaskManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.tabs = QTabWidget()
        self.controls: dict[str, QWidget] = {}
        self.tabs.addTab(self._recording_tab(), "录制与命名")
        self.tabs.addTab(self._network_tab(), "网络与解析")
        self.tabs.addTab(self._cookie_tab(), "Cookie")
        self.tabs.addTab(self._environment_tab(), "FFmpeg 与环境")
        self.tabs.addTab(self._logging_tab(), "日志与界面")
        save = QPushButton("保存设置")
        save.clicked.connect(self.save)
        layout = QVBoxLayout(self)
        title = QLabel("设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(self.tabs)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        self.load_values()

    def _form_page(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        return page, form

    def _recording_tab(self) -> QWidget:
        page, form = self._form_page()
        output = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(lambda: self._browse_directory(output))
        row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0,0,0,0); row_layout.addWidget(output); row_layout.addWidget(browse)
        self.controls["output_directory"] = output
        format_box = QComboBox(); format_box.addItems(["ts", "mp4", "mkv", "flv"])
        quality = QComboBox()
        for key, label in [("OD","原画"),("UHD","超清"),("HD","高清"),("SD","标清"),("LD","流畅")]:
            quality.addItem(label, key)
        source = QComboBox(); source.addItems(["HLS", "FLV"])
        segmented = QCheckBox("启用分段录制")
        segment_seconds = QSpinBox(); segment_seconds.setRange(60, 86400)
        threshold = QDoubleSpinBox(); threshold.setRange(0, 9999); threshold.setSuffix(" GB")
        convert = QCheckBox("TS 录制完成后转为 MP4")
        delete = QCheckBox("转 MP4 成功后删除源文件")
        template = QLineEdit(); template.setPlaceholderText("{platform}_{anchor}_{title}_{time}")
        folder_platform = QCheckBox("按平台建立目录")
        folder_anchor = QCheckBox("按主播建立目录")
        for name, widget in [
            ("default_format", format_box), ("video_quality", quality), ("stream_source", source),
            ("segmented_recording", segmented), ("segment_seconds", segment_seconds),
            ("disk_threshold_gb", threshold), ("auto_convert_mp4", convert),
            ("delete_original", delete), ("filename_template", template),
            ("folder_by_platform", folder_platform), ("folder_by_anchor", folder_anchor),
        ]:
            self.controls[name] = widget
        form.addRow("保存目录：", row); form.addRow("录制格式：", format_box)
        form.addRow("默认画质：", quality); form.addRow("优先直播源：", source)
        form.addRow("", segmented); form.addRow("分段时长：", segment_seconds)
        form.addRow("磁盘剩余阈值：", threshold); form.addRow("", convert)
        form.addRow("", delete); form.addRow("文件名模板：", template)
        form.addRow("", folder_platform); form.addRow("", folder_anchor)
        return page

    def _network_tab(self) -> QWidget:
        page, form = self._form_page()
        interval = QSpinBox(); interval.setRange(2, 86400); interval.setSuffix(" 秒")
        workers = QSpinBox(); workers.setRange(1, 32)
        proxy_enabled = QCheckBox("启用代理")
        proxy = QLineEdit(); proxy.setPlaceholderText("http://127.0.0.1:7890")
        self.controls.update(check_interval_seconds=interval, max_concurrent_checks=workers, proxy_enabled=proxy_enabled, proxy_address=proxy)
        form.addRow("检测间隔：", interval); form.addRow("并发检测数：", workers)
        form.addRow("", proxy_enabled); form.addRow("代理地址：", proxy)
        return page

    def _cookie_tab(self) -> QWidget:
        page, form = self._form_page()
        cookie = QLineEdit(); cookie.setEchoMode(QLineEdit.EchoMode.Password)
        toggle = QCheckBox("显示 Cookie")
        toggle.toggled.connect(lambda checked: cookie.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        clear = QPushButton("清空 Cookie"); clear.clicked.connect(cookie.clear)
        test = QPushButton("测试解析"); test.clicked.connect(self._test_parser)
        buttons = QWidget(); row = QHBoxLayout(buttons); row.setContentsMargins(0,0,0,0); row.addWidget(toggle); row.addWidget(clear); row.addWidget(test); row.addStretch()
        self.controls["douyin_cookie"] = cookie
        form.addRow("抖音 Cookie：", cookie); form.addRow("", buttons)
        note = QLabel("Cookie 仅保存在本机 config/config.ini，请勿提交或分享。")
        note.setWordWrap(True); form.addRow("", note)
        return page

    def _environment_tab(self) -> QWidget:
        page, form = self._form_page()
        ffmpeg = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(lambda: self._browse_file(ffmpeg))
        row_widget = QWidget(); row = QHBoxLayout(row_widget); row.setContentsMargins(0,0,0,0); row.addWidget(ffmpeg); row.addWidget(browse)
        self.ffmpeg_status = QLabel()
        self.node_status_label = QLabel()
        detect = QPushButton("重新检测环境"); detect.clicked.connect(self.refresh_environment)
        self.controls["ffmpeg_path"] = ffmpeg
        form.addRow("自定义 FFmpeg：", row_widget); form.addRow("FFmpeg 状态：", self.ffmpeg_status)
        form.addRow("Node.js 状态：", self.node_status_label); form.addRow("", detect)
        return page

    def _logging_tab(self) -> QWidget:
        page, form = self._form_page()
        level = QComboBox(); level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        view = QComboBox(); view.addItem("表格", "table"); view.addItem("卡片", "cards")
        self.controls.update(log_level=level, task_view=view)
        form.addRow("日志级别：", level); form.addRow("默认任务视图：", view)
        return page

    def _browse_directory(self, target: QLineEdit) -> None:
        if path := QFileDialog.getExistingDirectory(self, "选择录制目录"):
            target.setText(path)

    def _browse_file(self, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 ffmpeg.exe", "", "ffmpeg.exe (*.exe);;All files (*)")
        if path:
            target.setText(path)

    def load_values(self) -> None:
        settings = self.manager.settings
        for name, widget in self.controls.items():
            value = getattr(settings, name)
            raw = value.value if hasattr(value, "value") else value
            if isinstance(widget, QLineEdit):
                widget.setText(str(raw))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(raw))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(raw)
            elif isinstance(widget, QComboBox):
                index = widget.findData(raw)
                widget.setCurrentIndex(index if index >= 0 else max(0, widget.findText(str(raw))))
        self.refresh_environment()

    def values(self) -> AppSettings:
        get = self.controls
        return AppSettings(
            output_directory=get["output_directory"].text().strip() or "recordings",
            default_format=get["default_format"].currentText(),
            video_quality=VideoQuality(get["video_quality"].currentData()),
            stream_source=StreamSource(get["stream_source"].currentText()),
            check_interval_seconds=get["check_interval_seconds"].value(),
            max_concurrent_checks=get["max_concurrent_checks"].value(),
            segmented_recording=get["segmented_recording"].isChecked(),
            segment_seconds=get["segment_seconds"].value(),
            disk_threshold_gb=get["disk_threshold_gb"].value(),
            auto_convert_mp4=get["auto_convert_mp4"].isChecked(),
            delete_original=get["delete_original"].isChecked(),
            filename_template=get["filename_template"].text().strip() or "{platform}_{anchor}_{time}",
            folder_by_platform=get["folder_by_platform"].isChecked(),
            folder_by_anchor=get["folder_by_anchor"].isChecked(),
            proxy_enabled=get["proxy_enabled"].isChecked(),
            proxy_address=get["proxy_address"].text().strip(),
            douyin_cookie=get["douyin_cookie"].text().strip(),
            ffmpeg_path=get["ffmpeg_path"].text().strip(),
            log_level=get["log_level"].currentText(),
            task_view=get["task_view"].currentData(),
        )

    def save(self) -> None:
        settings = self.values()
        self.manager.update_settings(settings)
        self.saved.emit(settings)
        self.refresh_environment()
        QMessageBox.information(self, "设置", "设置已保存并立即生效。")

    def refresh_environment(self) -> None:
        custom = self.controls["ffmpeg_path"].text().strip() if "ffmpeg_path" in self.controls else ""
        ff = FFmpegTool(custom).status()
        self.ffmpeg_status.setText(f"{ff.source} · {ff.version or ff.error}\n{ff.executable or ''}")
        node = node_status()
        self.node_status_label.setText(f"{node.source} · {node.version or node.error}\n{node.executable or ''}")

    def _test_parser(self) -> None:
        self.save()
        tasks = [task for task in self.manager.tasks() if task.enabled]
        if not tasks:
            QMessageBox.information(self, "测试解析", "请先添加并启用一个抖音任务。")
            return
        self.manager.refresh_now()
        QMessageBox.information(self, "测试解析", "已在后台测试所有启用任务，请查看任务状态和日志。")


class AboutPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("douyin-LiveRec-king")
        title.setObjectName("pageTitle")
        text = QLabel(
            "Windows 直播监控与自动录制工具\n\n"
            "真实直播解析由 streamget 4.0.10 提供，录制由 FFmpeg 完成。\n"
            "界面结构参考 StreamCap，但本项目使用 PySide6 独立实现。\n\n"
            "请仅录制您有权保存的内容，并遵守平台服务条款和版权规则。"
        )
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, manager: TaskManager, logger: logging.Logger) -> None:
        super().__init__()
        self.manager = manager
        self.logger = logger
        self.setWindowTitle("douyin-LiveRec-king")
        self.resize(1280, 800)
        self.task_bridge = TaskSignalBridge(self)
        self.task_bridge.changed.connect(self._task_changed)
        manager.add_listener(self.task_bridge.changed.emit)

        self.log_emitter = LogEmitter(self)
        self.log_handler = QtLogHandler(self.log_emitter)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
        self.log_emitter.message.connect(self._append_log)
        logger.addHandler(self.log_handler)

        self.navigation = QListWidget()
        self.navigation.setFixedWidth(170)
        self.navigation.addItems(["监控任务", "录制文件", "设置", "日志", "关于"])
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.pages = QStackedWidget()
        self.tasks_page = TasksPage(manager)
        self.recordings_page = RecordingsPage(manager)
        self.settings_page = SettingsPage(manager)
        self.settings_page.saved.connect(self._settings_saved)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumBlockCount(5000)
        self.pages.addWidget(self.tasks_page)
        self.pages.addWidget(self.recordings_page)
        self.pages.addWidget(self.settings_page)
        self.pages.addWidget(self.log_view)
        self.pages.addWidget(AboutPage())
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.navigation)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.setStyleSheet(
            """
            QListWidget { background:#f1f5f9; border:0; padding:16px 8px; font-size:15px; }
            QListWidget::item { padding:12px; border-radius:6px; }
            QListWidget::item:selected { background:#dbeafe; color:#1d4ed8; }
            #pageTitle { font-size:22px; font-weight:700; padding:6px 0; }
            #taskCard { background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:8px; }
            QPushButton { padding:6px 10px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height:26px; }
            """
        )
        self.statusBar().showMessage("就绪")

    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == 1:
            self.recordings_page.refresh()
        elif index == 2:
            self.settings_page.load_values()

    @Slot(object)
    def _task_changed(self, task: LiveTask) -> None:
        self.tasks_page.refresh()
        self.statusBar().showMessage(f"{task.display_name}: {task.status.value}", 5000)

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    @Slot(object)
    def _settings_saved(self, settings: AppSettings) -> None:
        self.logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
        self.tasks_page.set_view(settings.task_view)
        self.logger.info("设置已保存")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.manager.shutdown()
        self.logger.removeHandler(self.log_handler)
        event.accept()
