"""Application composition root."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import SettingsStore, TaskStore, migrate_legacy_config
from .gui.main_window import MainWindow
from .logging_setup import configure_logging
from .services.task_manager import TaskManager


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("douyin-LiveRec-king")
    app.setOrganizationName("douyin-LiveRec-king")
    settings_store = SettingsStore()
    task_store = TaskStore()
    try:
        migrate_legacy_config(settings_store=settings_store, task_store=task_store)
        settings = settings_store.load()
        tasks = task_store.load()
    except RuntimeError as exc:
        QMessageBox.critical(None, "配置错误", str(exc))
        return 1
    logger = configure_logging(settings.log_level)
    logger.info("douyin-LiveRec-king 启动")
    manager = TaskManager(task_store, settings_store, tasks, settings, logger)
    window = MainWindow(manager, logger)
    window.show()
    return app.exec()
