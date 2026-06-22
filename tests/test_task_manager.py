import logging
from pathlib import Path

from douyin_live_rec_king.config import SettingsStore, TaskStore
from douyin_live_rec_king.models import AppSettings, LiveTask, TaskStatus
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
    assert TaskStore(tmp_path / "tasks.json").load()[0].display_name == "Mock Anchor"

