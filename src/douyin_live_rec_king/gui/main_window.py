"""Main navigation shell, Qt signal wiring, and graceful shutdown."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QProgressDialog,
    QStackedWidget,
    QWidget,
)

from ..models import AppSettings, LiveTask
from ..services.application import ApplicationServices
from ..services.task_manager import TaskManager
from .about_page import AboutPage
from .log_bridge import LogEmitter, QtLogHandler
from .page_bundle import ShutdownSignalBridge, TaskSignalBridge
from .recordings_page import RecordingsPage
from .settings_page import SettingsPage
from .statistics_page import StatisticsPage
from .tasks_page import TaskCard, TasksPage

__all__ = [
    "AboutPage",
    "MainWindow",
    "RecordingsPage",
    "SettingsPage",
    "StatisticsPage",
    "TaskCard",
    "TasksPage",
]


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
        self.log_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"
            )
        )
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
        self.statistics_page = (
            StatisticsPage(self.services.statistics_service)
            if self.services
            else QWidget()
        )
        self.settings_page = SettingsPage(self.manager)
        self.settings_page.saved.connect(self._settings_saved)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        for page in (
            self.tasks_page,
            self.recordings_page,
            self.statistics_page,
            self.settings_page,
            self.log_view,
            AboutPage(),
        ):
            self.pages.addWidget(page)

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
        self.statusBar().showMessage(
            f"{task.display_name}: {task.status.value}", 5000
        )

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    @Slot(object)
    def _settings_saved(self, settings: AppSettings) -> None:
        self.logger.setLevel(
            getattr(logging, settings.log_level, logging.INFO)
        )
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
        self._shutdown_dialog.setWindowModality(
            Qt.WindowModality.ApplicationModal
        )
        self._shutdown_dialog.setMinimumDuration(0)
        self._shutdown_dialog.show()
        self.services.shutdown_async(
            self.shutdown_bridge.progress.emit,
            self.shutdown_bridge.completed.emit,
        )

    @Slot(str, int, int)
    def _shutdown_progress(
        self, stage: str, current: int, total: int
    ) -> None:
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
            self.logger.warning(
                "应用关闭时存在未完全清理的问题: %s", error
            )
        self._shutdown_approved = True
        self.close()
