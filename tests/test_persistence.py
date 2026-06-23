import logging
import threading
import time
from pathlib import Path

from douyin_live_rec_king.config import TaskStore
from douyin_live_rec_king.models import LiveTask
from douyin_live_rec_king.services.persistence import TaskPersistenceCoordinator


class CountingTaskStore(TaskStore):
    def __init__(self, path: Path):
        super().__init__(path)
        self.snapshots = []
        self.saved = threading.Event()

    def save_snapshot(self, tasks):
        self.snapshots.append(tasks)
        super().save_snapshot(tasks)
        self.saved.set()


def test_debounced_save_keeps_latest_snapshot(tmp_path: Path) -> None:
    store = CountingTaskStore(tmp_path / "tasks.json")
    coordinator = TaskPersistenceCoordinator(
        store, logging.getLogger("persistence"), debounce_seconds=0.05
    )
    task = LiveTask(url="mock://offline", anchor_name="first")
    coordinator.request_save([task])
    task.anchor_name = "latest"
    coordinator.request_save([task])
    assert coordinator.flush(2)
    assert len(store.snapshots) == 1
    assert store.snapshots[0][0]["anchor_name"] == "latest"
    assert coordinator.close()


def test_save_now_is_immediate_and_atomic(tmp_path: Path) -> None:
    store = CountingTaskStore(tmp_path / "tasks.json")
    coordinator = TaskPersistenceCoordinator(
        store, logging.getLogger("persistence"), debounce_seconds=10
    )
    task = LiveTask(url="mock://offline", anchor_name="now")
    coordinator.save_now([task])
    assert store.load()[0].anchor_name == "now"
    assert coordinator.close()


def test_flush_times_out_while_write_is_blocked(tmp_path: Path) -> None:
    store = CountingTaskStore(tmp_path / "tasks.json")
    release = threading.Event()
    original = store.save_snapshot

    def blocked(tasks):
        release.wait(2)
        original(tasks)

    store.save_snapshot = blocked
    coordinator = TaskPersistenceCoordinator(
        store, logging.getLogger("persistence"), debounce_seconds=0
    )
    coordinator.request_save([LiveTask(url="mock://offline")])
    time.sleep(0.05)
    assert not coordinator.flush(0.01)
    release.set()
    assert coordinator.flush(2)
    assert coordinator.close()


def test_background_write_failure_is_reported_by_flush(tmp_path: Path) -> None:
    store = CountingTaskStore(tmp_path / "tasks.json")

    def fail(_tasks):
        raise OSError("disk failure")

    store.save_snapshot = fail
    coordinator = TaskPersistenceCoordinator(
        store, logging.getLogger("persistence"), debounce_seconds=0
    )
    coordinator.request_save([LiveTask(url="mock://offline")])
    assert not coordinator.flush(2)
    coordinator.close()
