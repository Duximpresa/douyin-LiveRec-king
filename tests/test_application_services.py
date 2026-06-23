import logging
import threading
from pathlib import Path

import pytest

from douyin_live_rec_king.config import SettingsStore, TaskStore
from douyin_live_rec_king.models import AppSettings, LiveTask, TaskStatus
from douyin_live_rec_king.recording.recorder import StopAllResult
from douyin_live_rec_king.services.application import ApplicationServices


def test_recover_runtime_state() -> None:
    recording = LiveTask(url="mock://offline", status=TaskStatus.RECORDING)
    checking = LiveTask(url="mock://offline", status=TaskStatus.CHECKING)
    error = LiveTask(
        url="mock://offline", status=TaskStatus.ERROR, last_error="keep me"
    )
    disabled = LiveTask(
        url="mock://offline", enabled=False, status=TaskStatus.RECORDING
    )
    assert ApplicationServices.recover_runtime_state(
        [recording, checking, error, disabled]
    )
    assert recording.status is TaskStatus.IDLE
    assert "上次运行未正常结束" in (recording.last_error or "")
    assert checking.status is TaskStatus.IDLE
    assert error.status is TaskStatus.ERROR
    assert error.last_error == "keep me"
    assert disabled.status is TaskStatus.DISABLED


def create_services(tmp_path: Path) -> ApplicationServices:
    return ApplicationServices.bootstrap(
        settings_store=SettingsStore(tmp_path / "config.ini"),
        task_store=TaskStore(tmp_path / "tasks.json"),
        settings=AppSettings(output_directory=str(tmp_path / "recordings")),
        tasks=[LiveTask(url="mock://offline")],
        logger=logging.getLogger("application-services"),
        migrate=False,
    )


def test_shutdown_async_is_idempotent(tmp_path: Path) -> None:
    services = create_services(tmp_path)
    completed = threading.Event()
    results = []
    services.recording_service.stop_all = (
        lambda timeout=20.0: StopAllResult(0, 0, 0, (), ())
    )
    assert services.shutdown_async(
        completion_callback=lambda ok, error: (
            results.append((ok, error)),
            completed.set(),
        )
    )
    assert not services.shutdown_async()
    assert completed.wait(3)
    assert results == [(True, None)]
    with pytest.raises(RuntimeError):
        services.task_manager.add_task(LiveTask(url="mock://offline"))


def test_bootstrap_persists_recovered_state(tmp_path: Path) -> None:
    task_store = TaskStore(tmp_path / "tasks.json")
    task_store.save(
        [LiveTask(url="mock://offline", status=TaskStatus.STOPPING)]
    )
    services = ApplicationServices.bootstrap(
        settings_store=SettingsStore(tmp_path / "config.ini"),
        task_store=task_store,
        settings=AppSettings(),
        logger=logging.getLogger("application-services"),
        migrate=False,
    )
    loaded = task_store.load()[0]
    assert loaded.status is TaskStatus.IDLE
    assert loaded.last_error
    services.persistence.close()
