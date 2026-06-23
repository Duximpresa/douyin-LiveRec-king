"""Page widget implementations and compatibility signal bridges."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
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
    QProgressDialog,
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
from ..platforms.registry import platform_metadata
from ..recording.ffmpeg import FFmpegTool, node_status
from ..services.application import ApplicationServices
from ..services.recording_history import RecordingHistoryService
from ..services.task_manager import TaskManager
from ..utils.paths import resolve_app_path
from .dialogs import TaskDialog
from .log_bridge import LogEmitter, QtLogHandler
from .statistics_page import StatisticsPage


class TaskSignalBridge(QObject):
    changed = Signal(object)


class ShutdownSignalBridge(QObject):
    progress = Signal(str, int, int)
    completed = Signal(bool, object)


class HistorySignalBridge(QObject):
    changed = Signal()


class TaskCard(QFrame):
    def __init__(self, page: "TasksPage", task: LiveTask) -> None:
        super().__init__()
        self.page = page
        self.task_id = task.id
        self.setObjectName("taskCard")
        layout = QGridLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-size:16px;font-weight:600")
        self.url = QLabel()
        self.checked = QLabel()
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#b91c1c")
        layout.addWidget(self.title, 0, 0, 1, 4)
        layout.addWidget(self.url, 1, 0, 1, 4)
        layout.addWidget(self.checked, 2, 0, 1, 2)
        layout.addWidget(self.error, 2, 2, 1, 2)
        self.edit_button = QPushButton("编辑")
        self.stop_button = QPushButton("停止录制")
        self.folder_button = QPushButton("打开文件夹")
        self.delete_button = QPushButton("删除")
        self.edit_button.clicked.connect(
            lambda: page.edit_task(self.task_id)
        )
        self.stop_button.clicked.connect(
            lambda: page.manager.stop_recording(self.task_id)
        )
        self.folder_button.clicked.connect(self._open_folder)
        self.delete_button.clicked.connect(
            lambda: page.delete_task(self.task_id)
        )
        for column, button in enumerate(
            (
                self.edit_button,
                self.stop_button,
                self.folder_button,
                self.delete_button,
            )
        ):
            layout.addWidget(button, 3, column)
        self.update_task(task)

    def _open_folder(self) -> None:
        task = self.page.manager.get(self.task_id)
        if task:
            self.page.open_task_folder(task)

    def update_task(self, task: LiveTask) -> None:
        self.title.setText(f"{task.display_name} · {task.status.value}")
        self.title.setToolTip(task.last_error or "")
        self.url.setText(task.url)
        self.checked.setText(f"最后检查：{task.last_checked_at or '尚未检查'}")
        self.error.setText(f"错误：{task.last_error}" if task.last_error else "")
        self.error.setToolTip(task.last_error or "")
        busy = task.status in {
            TaskStatus.STARTING_RECORD,
            TaskStatus.RECORDING,
            TaskStatus.STOPPING,
        }
        self.edit_button.setEnabled(not busy)
        self.stop_button.setEnabled(
            task.status in {TaskStatus.STARTING_RECORD, TaskStatus.RECORDING}
        )
        self.delete_button.setEnabled(task.status is not TaskStatus.STOPPING)


class TasksPage(QWidget):
    HEADERS = ["启用", "平台", "显示昵称", "原始地址", "规范地址", "状态", "录制文件", "最后检查"]

    def __init__(self, manager: TaskManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._table_rows: dict[str, int] = {}
        self._task_cards: dict[str, TaskCard] = {}
        self.summary_labels = {
            key: QLabel() for key in ("monitoring", "recording", "errors", "retry")
        }
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
        summary = QHBoxLayout()
        for key in ("monitoring", "recording", "errors", "retry"):
            label = self.summary_labels[key]
            label.setStyleSheet(
                "padding:8px 12px;background:#eef2ff;border-radius:6px;"
            )
            summary.addWidget(label)
        summary.addStretch()
        layout.addLayout(summary)
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
        all_tasks = self.manager.tasks()
        self.summary_labels["monitoring"].setText(
            f"监控 {sum(task.enabled for task in all_tasks)}"
        )
        self.summary_labels["recording"].setText(
            f"录制 {sum(task.status is TaskStatus.RECORDING for task in all_tasks)}"
        )
        self.summary_labels["errors"].setText(
            f"错误 {sum(task.status is TaskStatus.ERROR for task in all_tasks)}"
        )
        self.summary_labels["retry"].setText(
            f"待重试 {sum(bool(task.next_retry_at) for task in all_tasks)}"
        )
        self.table.setRowCount(0)
        self._table_rows.clear()
        for task in tasks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._table_rows[task.id] = row
            self._fill_task_row(row, task)
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._task_cards.clear()
        for task in tasks:
            card = self._card(task)
            self._task_cards[task.id] = card
            self.cards_layout.addWidget(card)

    def _fill_task_row(self, row: int, task: LiveTask) -> None:
        values = [
            "是" if task.enabled else "否",
            platform_metadata(task.platform).display_name,
            task.display_name,
            task.url,
            task.canonical_url or "",
            task.status.value,
            task.recording_file or "",
            task.last_checked_at or "",
        ]
        for column, value in enumerate(values):
            item = self.table.item(row, column) or QTableWidgetItem()
            item.setText(value)
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setToolTip(task.last_error or "")
            self.table.setItem(row, column, item)

    def update_task_row(self, task_id: str) -> None:
        task = self.manager.get(task_id)
        filtered_ids = {item.id for item in self._filtered_tasks()}
        if not task or task_id not in filtered_ids:
            self.remove_task_widget(task_id)
            return
        row = self._table_rows.get(task_id)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._table_rows[task_id] = row
        self._fill_task_row(row, task)

    def update_task_card(self, task_id: str) -> None:
        task = self.manager.get(task_id)
        filtered_ids = {item.id for item in self._filtered_tasks()}
        if not task or task_id not in filtered_ids:
            self.remove_task_widget(task_id)
            return
        current = self._task_cards.get(task_id)
        if current is None:
            card = self._card(task)
            self._task_cards[task_id] = card
            self.cards_layout.addWidget(card)
            return
        current.update_task(task)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        all_tasks = self.manager.tasks()
        self.summary_labels["monitoring"].setText(
            f"监控 {sum(task.enabled for task in all_tasks)}"
        )
        self.summary_labels["recording"].setText(
            f"录制 {sum(task.status is TaskStatus.RECORDING for task in all_tasks)}"
        )
        self.summary_labels["errors"].setText(
            f"错误 {sum(task.status is TaskStatus.ERROR for task in all_tasks)}"
        )
        self.summary_labels["retry"].setText(
            f"待重试 {sum(bool(task.next_retry_at) for task in all_tasks)}"
        )

    def remove_task_widget(self, task_id: str) -> None:
        row = self._table_rows.pop(task_id, None)
        if row is not None and 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
            self._table_rows = {
                self.table.item(index, 0).data(Qt.ItemDataRole.UserRole): index
                for index in range(self.table.rowCount())
                if self.table.item(index, 0)
            }
        card = self._task_cards.pop(task_id, None)
        if card:
            self.cards_layout.removeWidget(card)
            card.deleteLater()

    def _card(self, task: LiveTask) -> TaskCard:
        return TaskCard(self, task)

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
            if self.manager.delete_task(task.id):
                self.remove_task_widget(task.id)

    def stop_recording(self) -> None:
        task = self.selected_task()
        if not task or not self.manager.stop_recording(task.id):
            QMessageBox.information(self, "停止录制", "所选任务当前没有录制进程。")

    def open_task_folder(self, task: LiveTask) -> None:
        path = Path(task.recording_file).parent if task.recording_file else resolve_app_path(self.manager.settings.output_directory)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class RecordingsPage(QWidget):
    HEADERS = [
        "状态",
        "平台",
        "主播",
        "标题",
        "开始时间",
        "时长",
        "大小",
        "文件数",
        "错误",
    ]

    def __init__(
        self,
        manager: TaskManager,
        history_service: RecordingHistoryService | None = None,
        recovery_files: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.history_service = history_service
        self.recovery_files = recovery_files or []
        self.history_bridge = HistorySignalBridge(self)
        self.history_bridge.changed.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索主播、标题或房间地址")
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        for label, value in [
            ("全部", "all"),
            ("成功", "success"),
            ("失败", "failed"),
            ("中断", "interrupted"),
            ("转换失败", "conversion_failed"),
            ("录制中", "recording"),
        ]:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.recovery_label = QLabel()
        self.recovery_label.setStyleSheet("color:#b45309")
        self.recovery_label.setWordWrap(True)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        self.table.itemSelectionChanged.connect(self.show_details)

        buttons = QHBoxLayout()
        buttons.addWidget(self.search, 1)
        buttons.addWidget(self.status_filter)
        for text, callback in [
            ("刷新", self.refresh),
            ("打开文件", self.open_file),
            ("打开目录", self.open_directory),
            ("复制错误", self.copy_error),
            ("立即重试", self.retry_now),
            ("重新扫描", self.rescan),
            ("中断 TS 转 MP4", self.remux),
            ("删除历史", self.delete_history),
            ("批量删除历史", self.delete_selected_history),
            ("删除视频文件", self.delete_files),
            ("恢复文件", self.show_recovery_files),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        title = QLabel("录制历史")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(self.recovery_label)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        layout.addWidget(self.detail)
        if self.history_service:
            self.history_service.add_listener(self.history_bridge.changed.emit)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def _selected_entry(self):
        if not self.history_service:
            return None
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return (
            self.history_service.get(item.data(Qt.ItemDataRole.UserRole))
            if item
            else None
        )

    def _selected_entries(self):
        if not self.history_service:
            return []
        ids = {
            self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in self.table.selectionModel().selectedRows()
            if self.table.item(index.row(), 0)
        }
        return [
            entry for session_id in ids
            if (entry := self.history_service.get(session_id))
        ]

    def show_details(self) -> None:
        entry = self._selected_entry()
        if not entry:
            self.detail.clear()
            return
        media = entry.media_info or {}
        self.detail.setPlainText(
            "\n".join(
                [
                    f"会话：{entry.session_id}",
                    f"房间：{entry.room_url}",
                    f"退出原因：{entry.exit_reason.value if entry.exit_reason else ''}",
                    f"返回码：{entry.return_code}",
                    f"格式：{media.get('format_name') or '未知'}",
                    f"媒体时长：{media.get('duration_seconds') or entry.duration_seconds:.1f} 秒",
                    f"文件：{'; '.join([*entry.files, *entry.converted_files])}",
                    f"警告：{'; '.join(entry.warnings)}",
                    f"错误：{entry.error or ''}",
                ]
            )
        )

    def refresh(self, *_args) -> None:
        selected = self._selected_entry()
        selected_id = selected.session_id if selected else None
        if self.recovery_files:
            self.recovery_label.setText(
                f"发现 {len(self.recovery_files)} 条未完成历史或临时文件，请人工检查；程序不会自动删除。"
            )
        else:
            self.recovery_label.clear()
        self.table.setRowCount(0)
        if not self.history_service:
            return
        entries = self.history_service.list_entries(
            self.status_filter.currentData(), self.search.text()
        )
        now = datetime.now().astimezone()
        for entry in entries:
            duration = entry.duration_seconds
            size = entry.total_size_bytes
            file_count = len(entry.files) + len(entry.converted_files)
            if entry.status in {"starting", "recording"}:
                try:
                    if entry.started_at:
                        started = datetime.fromisoformat(entry.started_at)
                        duration = max(0.0, (now - started).total_seconds())
                    running_files: list[Path] = []
                    for value in entry.files:
                        running_files.extend(
                            self.history_service.integrity_guard.resolve_files(value)
                        )
                    size = sum(path.stat().st_size for path in running_files)
                    file_count = len(running_files)
                except OSError:
                    pass
            row = self.table.rowCount()
            self.table.insertRow(row)
            status_label = {
                "starting": "启动中",
                "recording": "录制中",
                "success": "成功",
                "failed": "失败",
                "interrupted": "中断",
                "conversion_failed": "转换失败",
            }.get(entry.status, entry.status)
            values = [
                status_label,
                entry.platform.value,
                entry.anchor_name,
                entry.title,
                entry.started_at or "",
                self._format_duration(duration),
                f"{size / 1024 / 1024:.1f} MB",
                str(file_count),
                entry.error or ("；".join(entry.warnings)),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, entry.session_id)
                item.setToolTip(entry.error or "；".join(entry.warnings))
                self.table.setItem(row, column, item)
            if selected_id == entry.session_id:
                self.table.selectRow(row)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"

    def open_file(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        candidates = [*entry.converted_files, *entry.files]
        path = next((Path(value) for value in candidates if Path(value).exists()), None)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_directory(self) -> None:
        entry = self._selected_entry()
        candidates = [*entry.converted_files, *entry.files] if entry else []
        path = next((Path(value) for value in candidates if Path(value).exists()), None)
        root = path.parent if path else resolve_app_path(self.manager.settings.output_directory)
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def copy_error(self) -> None:
        entry = self._selected_entry()
        if entry and entry.error:
            QApplication.clipboard().setText(entry.error)

    def retry_now(self) -> None:
        entry = self._selected_entry()
        if entry and not self.manager.retry_now(entry.task_id):
            QMessageBox.information(self, "立即重试", "对应任务不存在、已禁用或应用正在关闭。")

    def delete_history(self) -> None:
        entry = self._selected_entry()
        if entry and self.history_service:
            self.history_service.delete_entry(entry.session_id)

    def delete_selected_history(self) -> None:
        entries = self._selected_entries()
        if not entries or not self.history_service:
            return
        if QMessageBox.question(
            self,
            "批量删除历史",
            f"确定删除选中的 {len(entries)} 条历史吗？视频文件不会被删除。",
        ) == QMessageBox.StandardButton.Yes:
            self.history_service.delete_entries(
                [entry.session_id for entry in entries]
            )

    def rescan(self) -> None:
        if not self.history_service:
            return
        entry = self._selected_entry()
        count = self.history_service.rescan(entry.session_id if entry else None)
        QMessageBox.information(self, "重新扫描", f"已更新 {count} 条记录。")

    def remux(self) -> None:
        entry = self._selected_entry()
        if not entry or not self.history_service:
            return
        try:
            target = self.history_service.remux_interrupted(entry.session_id)
            QMessageBox.information(self, "转封装完成", str(target))
        except Exception as exc:
            QMessageBox.warning(self, "转封装失败", str(exc))

    def show_recovery_files(self) -> None:
        if not self.recovery_files:
            QMessageBox.information(self, "恢复文件", "没有待处理的恢复文件。")
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("恢复文件")
        dialog.setText(
            "以下文件或历史需要人工检查：\n\n"
            + "\n".join(self.recovery_files[:100])
        )
        open_button = dialog.addButton("打开首个文件位置", QMessageBox.ButtonRole.ActionRole)
        clean_button = dialog.addButton("清理临时文件", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            first = next(
                (Path(item) for item in self.recovery_files if not item.startswith("history:")),
                None,
            )
            if first:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(first.parent)))
        elif dialog.clickedButton() is clean_button and self.history_service:
            if QMessageBox.question(
                self,
                "确认清理",
                "只会删除列表中的 .tmp 和 .part 文件，是否继续？",
            ) == QMessageBox.StandardButton.Yes:
                deleted, errors = self.history_service.cleanup_temporary(
                    self.recovery_files
                )
                if not errors:
                    self.recovery_files = [
                        item
                        for item in self.recovery_files
                        if Path(item).suffix.lower() not in {".tmp", ".part"}
                    ]
                QMessageBox.information(
                    self,
                    "清理结果",
                    f"已删除 {deleted} 个文件。"
                    + (f"\n失败：{chr(10).join(errors)}" if errors else ""),
                )

    def delete_files(self) -> None:
        entry = self._selected_entry()
        if not entry or not self.history_service:
            return
        if QMessageBox.question(
            self,
            "删除视频文件",
            "确定删除该历史关联的视频文件吗？此操作不可撤销，历史记录会保留。",
        ) != QMessageBox.StandardButton.Yes:
            return
        deleted, errors = self.history_service.delete_files(entry.session_id)
        if errors:
            QMessageBox.warning(self, "删除视频文件", "\n".join(errors))
        else:
            QMessageBox.information(self, "删除视频文件", f"已删除 {deleted} 个文件。")


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
        retry_attempts = QSpinBox(); retry_attempts.setRange(0, 20)
        retry_delays = QLineEdit(); retry_delays.setPlaceholderText("5,15,45")
        retry_concurrency = QSpinBox(); retry_concurrency.setRange(1, 32)
        self.controls.update(
            check_interval_seconds=interval,
            max_concurrent_checks=workers,
            proxy_enabled=proxy_enabled,
            proxy_address=proxy,
            retry_max_attempts=retry_attempts,
            retry_delays_seconds=retry_delays,
            max_concurrent_retries=retry_concurrency,
        )
        form.addRow("检测间隔：", interval); form.addRow("并发检测数：", workers)
        form.addRow("", proxy_enabled); form.addRow("代理地址：", proxy)
        form.addRow("最大自动重试次数：", retry_attempts)
        form.addRow("重试间隔（秒，逗号分隔）：", retry_delays)
        form.addRow("同时重试任务数：", retry_concurrency)
        return page

    def _cookie_tab(self) -> QWidget:
        page, form = self._form_page()
        cookie = QLineEdit(); cookie.setEchoMode(QLineEdit.EchoMode.Password)
        bilibili_cookie = QLineEdit()
        bilibili_cookie.setEchoMode(QLineEdit.EchoMode.Password)
        toggle = QCheckBox("显示 Cookie")
        toggle.toggled.connect(
            lambda checked: [
                item.setEchoMode(
                    QLineEdit.EchoMode.Normal
                    if checked
                    else QLineEdit.EchoMode.Password
                )
                for item in (cookie, bilibili_cookie)
            ]
        )
        clear = QPushButton("清空 Cookie")
        clear.clicked.connect(cookie.clear)
        clear.clicked.connect(bilibili_cookie.clear)
        test = QPushButton("测试解析"); test.clicked.connect(self._test_parser)
        buttons = QWidget(); row = QHBoxLayout(buttons); row.setContentsMargins(0,0,0,0); row.addWidget(toggle); row.addWidget(clear); row.addWidget(test); row.addStretch()
        self.controls["douyin_cookie"] = cookie
        self.controls["bilibili_cookie"] = bilibili_cookie
        form.addRow("抖音 Cookie：", cookie)
        form.addRow("Bilibili Cookie：", bilibili_cookie)
        form.addRow("", buttons)
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
            bilibili_cookie=get["bilibili_cookie"].text().strip(),
            ffmpeg_path=get["ffmpeg_path"].text().strip(),
            log_level=get["log_level"].currentText(),
            task_view=get["task_view"].currentData(),
            retry_max_attempts=get["retry_max_attempts"].value(),
            retry_delays_seconds=get["retry_delays_seconds"].text().strip()
            or "5,15,45",
            max_concurrent_retries=get["max_concurrent_retries"].value(),
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
    def __init__(
        self,
        services_or_manager: ApplicationServices | TaskManager,
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self.services = (
            services_or_manager
            if isinstance(services_or_manager, ApplicationServices)
            else None
        )
        self.manager = (
            services_or_manager.task_manager
            if self.services is not None
            else services_or_manager
        )
        self.logger = logger
        self._shutdown_approved = False
        self._shutdown_dialog: QProgressDialog | None = None
        self.shutdown_bridge = ShutdownSignalBridge(self)
        self.shutdown_bridge.progress.connect(self._shutdown_progress)
        self.shutdown_bridge.completed.connect(self._shutdown_completed)
        self.setWindowTitle("douyin-LiveRec-king")
        self.resize(1280, 800)
        self.task_bridge = TaskSignalBridge(self)
        self.task_bridge.changed.connect(self._task_changed)
        self.manager.add_listener(self.task_bridge.changed.emit)

        self.log_emitter = LogEmitter(self)
        self.log_handler = QtLogHandler(self.log_emitter)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
        self.log_emitter.message.connect(self._append_log)
        logger.addHandler(self.log_handler)

        self.navigation = QListWidget()
        self.navigation.setFixedWidth(170)
        self.navigation.addItems(
            ["监控任务", "录制历史", "统计", "设置", "日志", "关于"]
        )
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.pages = QStackedWidget()
        self.tasks_page = TasksPage(self.manager)
        self.recordings_page = RecordingsPage(
            self.manager,
            self.services.recording_history_service if self.services else None,
            self.services.recovery_files if self.services else None,
        )
        self.settings_page = SettingsPage(self.manager)
        self.statistics_page = (
            StatisticsPage(self.services.statistics_service)
            if self.services
            else QWidget()
        )
        self.settings_page.saved.connect(self._settings_saved)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumBlockCount(5000)
        self.pages.addWidget(self.tasks_page)
        self.pages.addWidget(self.recordings_page)
        self.pages.addWidget(self.statistics_page)
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
        elif index == 2 and self.services:
            self.statistics_page.refresh()
        elif index == 3:
            self.settings_page.load_values()

    @Slot(object)
    def _task_changed(self, task: LiveTask) -> None:
        self.tasks_page.update_task_row(task.id)
        self.tasks_page.update_task_card(task.id)
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
        if self._shutdown_approved:
            self.logger.removeHandler(self.log_handler)
            event.accept()
            return
        if self.services is None:
            self.manager.shutdown()
            self.logger.removeHandler(self.log_handler)
            event.accept()
            return
        event.ignore()
        if self.services.shutting_down:
            return
        self._shutdown_dialog = QProgressDialog(
            "正在准备关闭…", "", 0, 0, self
        )
        self._shutdown_dialog.setWindowTitle("正在安全停止录制")
        self._shutdown_dialog.setCancelButton(None)
        self._shutdown_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._shutdown_dialog.setMinimumDuration(0)
        self._shutdown_dialog.show()
        self.services.shutdown_async(
            self.shutdown_bridge.progress.emit,
            self.shutdown_bridge.completed.emit,
        )

    @Slot(str, int, int)
    def _shutdown_progress(self, stage: str, current: int, total: int) -> None:
        if not self._shutdown_dialog:
            return
        suffix = f"（{current}/{total}）" if total else ""
        self._shutdown_dialog.setLabelText(f"{stage}{suffix}")

    @Slot(bool, object)
    def _shutdown_completed(self, ok: bool, error: object) -> None:
        if self._shutdown_dialog:
            self._shutdown_dialog.close()
            self._shutdown_dialog = None
        if not ok and error:
            self.logger.warning("应用关闭时存在未完全清理的问题: %s", error)
        self._shutdown_approved = True
        self.close()
