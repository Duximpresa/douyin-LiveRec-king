import logging
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from douyin_live_rec_king.config import SettingsStore, TaskStore
from douyin_live_rec_king.gui.main_window import RecordingsPage
from douyin_live_rec_king.models import AppSettings, LiveStatus, LiveTask, RecordingExitReason
from douyin_live_rec_king.services.application import ApplicationServices


def test_recordings_page_filters_and_history_delete_keeps_file(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    services = ApplicationServices.bootstrap(
        settings_store=SettingsStore(tmp_path / "config.ini"),
        task_store=TaskStore(tmp_path / "tasks.json"),
        settings=AppSettings(output_directory=str(tmp_path / "recordings")),
        tasks=[],
        logger=logging.getLogger("recordings-page"),
        migrate=False,
    )
    task = LiveTask(url="mock://live", anchor_name="Search Anchor")
    output = tmp_path / "record.ts"
    output.write_bytes(b"x" * 300_000)
    entry = services.recording_history_service.create(
        task, LiveStatus(True, title="Search Title"), str(output), "ts"
    )
    services.recording_history_service.finish(
        entry.session_id,
        output_file=str(output),
        duration_seconds=2,
        return_code=1,
        reason=RecordingExitReason.FFMPEG_ERROR,
        error="test failure",
    )
    page = RecordingsPage(
        services.task_manager, services.recording_history_service
    )
    app.processEvents()
    assert page.table.rowCount() == 1
    page.search.setText("Search Title")
    app.processEvents()
    assert page.table.rowCount() == 1
    page.table.selectRow(0)
    page.copy_error()
    assert QApplication.clipboard().text() == "test failure"
    page.delete_history()
    assert output.exists()
    assert page.table.rowCount() == 0
    page.close()
    services.retry_coordinator.cancel_all()
    services.persistence.close()
