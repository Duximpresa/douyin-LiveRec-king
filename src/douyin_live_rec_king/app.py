"""Application composition root."""

from __future__ import annotations

import sys
import threading

from PySide6.QtWidgets import QApplication, QMessageBox

from .gui.main_window import MainWindow
from .services.application import ApplicationServices


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("douyin-LiveRec-king")
    app.setOrganizationName("douyin-LiveRec-king")
    try:
        services = ApplicationServices.bootstrap()
    except RuntimeError as exc:
        QMessageBox.critical(None, "配置错误", str(exc))
        return 1
    logger = services.logger
    logger.info("douyin-LiveRec-king 启动")
    if "--smoke-test" in sys.argv:
        completed = threading.Event()
        result: list[bool] = []
        services.shutdown_async(
            completion_callback=lambda ok, _error: (result.append(ok), completed.set())
        )
        if not completed.wait(25):
            services.recording_service.force_stop_all()
            return 2
        return 0 if result and result[0] else 3
    window = MainWindow(services, logger)
    window.show()
    return app.exec()
