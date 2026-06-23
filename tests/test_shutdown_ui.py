import logging
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from douyin_live_rec_king.config import SettingsStore, TaskStore
from douyin_live_rec_king.gui.main_window import MainWindow
from douyin_live_rec_king.models import AppSettings, LiveTask
from douyin_live_rec_king.services.application import ApplicationServices


def test_close_event_uses_non_blocking_shutdown_progress(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    logger = logging.getLogger("shutdown-ui")
    services = ApplicationServices.bootstrap(
        settings_store=SettingsStore(tmp_path / "config.ini"),
        task_store=TaskStore(tmp_path / "tasks.json"),
        settings=AppSettings(output_directory=str(tmp_path / "recordings")),
        tasks=[LiveTask(url="mock://offline")],
        logger=logger,
        migrate=False,
    )
    callbacks = {}

    def shutdown_async(progress_callback=None, completion_callback=None):
        services._shutdown_started = True
        callbacks["progress"] = progress_callback
        callbacks["complete"] = completion_callback
        return True

    services.shutdown_async = shutdown_async
    window = MainWindow(services, logger)
    window.show()
    app.processEvents()
    window.close()
    app.processEvents()
    assert window._shutdown_dialog is not None
    assert window.isVisible()

    callbacks["progress"]("正在停止录制", 1, 2)
    app.processEvents()
    assert "1/2" in window._shutdown_dialog.labelText()

    callbacks["complete"](True, None)
    app.processEvents()
    assert not window.isVisible()
    services.persistence.close()
