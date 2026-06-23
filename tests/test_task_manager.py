import logging
import threading
from pathlib import Path

from douyin_live_rec_king.config import SettingsStore, TaskStore
from douyin_live_rec_king.models import (
    AppSettings,
    LiveTask,
    RecordingExitReason,
    TaskStatus,
)
from douyin_live_rec_king.recording.events import RecordingEvent, RecordingEventType
from douyin_live_rec_king.services.task_manager import TaskManager


def create_manager(tmp_path: Path) -> TaskManager:
    return TaskManager(
        TaskStore(tmp_path / "tasks.json"),
        SettingsStore(tmp_path / "config.ini"),
        [],
        AppSettings(),
        logging.getLogger("test-manager"),
    )


def test_add_update_delete_task(tmp_path: Path) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline")
    manager.add_task(task)
    manager.update_task(task.id, anchor_name="自定义昵称", enabled=False)
    assert manager.get(task.id).display_name == "自定义昵称"
    assert manager.get(task.id).status is TaskStatus.DISABLED
    manager.delete_task(task.id)
    assert manager.get(task.id) is None


def test_auto_name_is_persisted(tmp_path: Path) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline")
    manager.add_task(task)
    manager._poll_task(task)
    assert task.display_name == "Mock Anchor"
    assert manager.persistence.flush()
    assert TaskStore(tmp_path / "tasks.json").load()[0].display_name == "Mock Anchor"


def test_stop_recording_sets_stopping_before_process_finishes(tmp_path: Path) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline")
    manager._tasks.append(task)
    entered = threading.Event()
    release = threading.Event()

    manager.recording_service.is_active = lambda _task_id: True

    def stop(_task_id: str) -> bool:
        entered.set()
        release.wait(2)
        return True

    manager.recording_service.stop = stop
    assert manager.stop_recording(task.id)
    assert task.status is TaskStatus.STOPPING
    assert entered.wait(1)
    release.set()


def test_network_exit_schedules_retry_and_retry_now(tmp_path: Path) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline")
    manager._tasks.append(task)
    manager._recording_event(
        RecordingEvent(
            task.id,
            RecordingEventType.EXITED,
            error="Connection reset",
            exit_reason=RecordingExitReason.NETWORK_ERROR,
            duration_seconds=10,
        )
    )
    assert task.retry_count == 1
    assert task.next_retry_at
    assert manager.retry_coordinator.pending(task.id)
    manager._poll_task(task)
    assert task.status is TaskStatus.ERROR
    assert manager.retry_now(task.id)
    assert not manager.retry_coordinator.pending(task.id)
    manager.retry_coordinator.cancel_all()


def test_stable_recording_resets_retry_series(tmp_path: Path) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline", retry_count=3)
    manager._tasks.append(task)
    manager._recording_event(
        RecordingEvent(
            task.id,
            RecordingEventType.EXITED,
            error="Connection reset",
            exit_reason=RecordingExitReason.NETWORK_ERROR,
            duration_seconds=301,
        )
    )
    assert task.retry_count == 1
    manager.retry_coordinator.cancel_all()


def test_retry_exhaustion_blocks_periodic_poll_until_manual_retry(
    tmp_path: Path,
) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline", retry_count=3)
    manager._tasks.append(task)
    manager._recording_event(
        RecordingEvent(
            task.id,
            RecordingEventType.EXITED,
            error="Connection reset",
            exit_reason=RecordingExitReason.NETWORK_ERROR,
            duration_seconds=10,
        )
    )
    assert task.status is TaskStatus.ERROR
    assert "重试上限" in (task.last_error or "")
    manager._poll_task(task)
    assert task.status is TaskStatus.ERROR
    assert manager.retry_now(task.id)
    assert task.retry_count == 0
    manager.retry_coordinator.cancel_all()


def test_non_retryable_recording_error_requires_manual_retry(
    tmp_path: Path,
) -> None:
    manager = create_manager(tmp_path)
    task = LiveTask(url="mock://offline")
    manager._tasks.append(task)
    manager._recording_event(
        RecordingEvent(
            task.id,
            RecordingEventType.EXITED,
            error="Invalid data found",
            exit_reason=RecordingExitReason.PARSER_ERROR,
            duration_seconds=1,
        )
    )
    manager._poll_task(task)
    assert task.status is TaskStatus.ERROR
    assert manager.retry_now(task.id)
    manager.retry_coordinator.cancel_all()
