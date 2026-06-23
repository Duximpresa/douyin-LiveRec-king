"""Recording-event and retry-state coordination for TaskManager."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from ..models import RecordingExitReason, TaskStatus
from ..recording.events import RecordingEvent, RecordingEventType

if TYPE_CHECKING:
    from .task_manager import TaskManager


class TaskRuntimeCoordinator:
    """Own transient recording/retry state without exposing it to the UI."""

    def __init__(self, manager: "TaskManager") -> None:
        self.manager = manager
        self.pending_deletions: set[str] = set()
        self.retry_blocked: set[str] = set()

    def handle_recording_event(self, event: RecordingEvent) -> None:
        manager = self.manager
        task_id = event.task_id
        task = manager.get(task_id)
        if not task:
            return
        if event.type is RecordingEventType.STARTING:
            manager._set_state(
                task,
                TaskStatus.STARTING_RECORD,
                recording_file=event.output_file,
            )
            return
        if event.type is RecordingEventType.RECORDING:
            if task.status is not TaskStatus.STOPPING:
                manager._set_state(
                    task,
                    TaskStatus.RECORDING,
                    recording_file=event.output_file,
                    persist=True,
                )
            return
        if event.type is RecordingEventType.ERROR:
            if event.exit_reason in {
                RecordingExitReason.PARSER_ERROR,
                RecordingExitReason.AUTH_ERROR,
                RecordingExitReason.STORAGE_ERROR,
                RecordingExitReason.FFMPEG_ERROR,
                RecordingExitReason.CONVERSION_ERROR,
            }:
                self.retry_blocked.add(task_id)
            if self._finish_pending_deletion(task_id):
                manager._notify(task)
                return
            manager._set_state(
                task,
                TaskStatus.ERROR,
                error=event.error or "录制启动失败",
                recording_file=event.output_file,
                persist=True,
            )
            return
        if event.type is not RecordingEventType.EXITED:
            return
        if self._finish_pending_deletion(task_id):
            manager._notify(task)
            return
        if (
            event.error is not None
            and event.exit_reason is not RecordingExitReason.NETWORK_ERROR
        ):
            self.retry_blocked.add(task_id)
        if (event.duration_seconds or 0) >= 300:
            task.retry_count = 0
        if self._schedule_network_retry(task, event):
            return
        manager.retry_coordinator.cancel(task.id)
        if event.error is None:
            self.retry_blocked.discard(task.id)
            task.retry_count = 0
        task.next_retry_at = None
        manager._set_state(
            task,
            manager._resting_status(task) if event.error is None else TaskStatus.ERROR,
            error=event.error,
            recording_file=event.output_file,
            persist=True,
        )

    def _finish_pending_deletion(self, task_id: str) -> bool:
        manager = self.manager
        with manager._lock:
            if task_id not in self.pending_deletions:
                return False
            self.pending_deletions.discard(task_id)
            manager._tasks = [
                item for item in manager._tasks if item.id != task_id
            ]
            manager._save_tasks(immediate=True)
            return True

    def _schedule_network_retry(self, task, event: RecordingEvent) -> bool:
        manager = self.manager
        maximum = manager.retry_coordinator.max_attempts
        if (
            event.exit_reason is RecordingExitReason.NETWORK_ERROR
            and task.enabled
            and not manager._closing
            and task.retry_count < maximum
        ):
            task.retry_count += 1
            delay = manager.retry_coordinator.schedule(task.id, task.retry_count)
            if delay is not None:
                next_retry = datetime.now().astimezone() + timedelta(seconds=delay)
                task.next_retry_at = next_retry.isoformat(timespec="seconds")
                manager._set_state(
                    task,
                    TaskStatus.ERROR,
                    error=(
                        f"{event.error or '网络错误'}；第 "
                        f"{task.retry_count}/{maximum} 次重试将在 "
                        f"{next_retry.strftime('%H:%M:%S')} 进行"
                    ),
                    recording_file=event.output_file,
                    persist=True,
                )
                return True
        if (
            event.exit_reason is RecordingExitReason.NETWORK_ERROR
            and task.retry_count >= maximum
        ):
            task.next_retry_at = None
            manager._set_state(
                task,
                TaskStatus.ERROR,
                error=(
                    f"{event.error or '网络错误'}；已达到 "
                    f"{maximum} 次自动重试上限"
                ),
                recording_file=event.output_file,
                persist=True,
            )
            return True
        return False
