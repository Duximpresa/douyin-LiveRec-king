"""Task CRUD, state transitions, persistence, and service coordination."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..config import SettingsStore, TaskStore
from ..models import (
    AppSettings,
    LiveStatus,
    LiveTask,
    RecordingExitReason,
    TaskStatus,
)
from ..platforms.registry import create_extractor
from ..recording.events import RecordingEvent
from .monitor import Monitor
from .persistence import TaskPersistenceCoordinator
from .recording_service import RecordingService
from .recording_history import RecordingHistoryService
from .retry import RetryCoordinator
from .task_runtime_coordinator import TaskRuntimeCoordinator

TaskListener = Callable[[LiveTask], None]


class TaskManager:
    def __init__(
        self,
        task_store: TaskStore,
        settings_store: SettingsStore,
        tasks: list[LiveTask],
        settings: AppSettings,
        logger: logging.Logger,
        persistence: TaskPersistenceCoordinator | None = None,
        history_service: RecordingHistoryService | None = None,
    ) -> None:
        self.task_store = task_store
        self.settings_store = settings_store
        self._tasks = tasks
        self.settings = settings
        self.logger = logger
        self._lock = threading.RLock()
        self._listeners: list[TaskListener] = []
        self._closing = False
        self.persistence = persistence or TaskPersistenceCoordinator(
            task_store, logger
        )
        self.recording_service = RecordingService(
            lambda: self.settings,
            logger,
            self._recording_event,
            history_service=history_service,
        )
        self.retry_coordinator = RetryCoordinator(
            self._retry_task,
            delays_provider=lambda: self.settings.retry_delays,
            max_attempts_provider=lambda: self.settings.retry_max_attempts,
            concurrency_provider=lambda: self.settings.max_concurrent_retries,
        )
        self.runtime_coordinator = TaskRuntimeCoordinator(self)
        # Compatibility aliases for existing tests and extensions.
        self._pending_deletions = self.runtime_coordinator.pending_deletions
        self._retry_blocked = self.runtime_coordinator.retry_blocked
        self.recorder = self.recording_service.recorder
        self.monitor = Monitor(
            self.tasks,
            self._poll_task,
            lambda: self.settings.check_interval_seconds,
            lambda: self.settings.max_concurrent_checks,
            logger,
        )
        for task in self._tasks:
            if not task.enabled:
                task.status = TaskStatus.DISABLED

    def add_listener(self, listener: TaskListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self, task: LiveTask) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(task)
            except Exception:
                self.logger.exception("任务状态监听器执行失败")

    def _set_state(
        self,
        task: LiveTask,
        status: TaskStatus,
        *,
        error: str | None = None,
        recording_file: str | None = None,
        persist: bool = False,
    ) -> None:
        with self._lock:
            task.status = status
            task.last_error = error
            if recording_file is not None:
                task.recording_file = recording_file
            if persist:
                self._save_tasks()
        self._notify(task)

    def _resting_status(self, task: LiveTask) -> TaskStatus:
        if not task.enabled:
            self.retry_coordinator.cancel(task.id)
            task.retry_count = 0
            task.next_retry_at = None
            return TaskStatus.DISABLED
        return TaskStatus.MONITORING if self.monitor.running else TaskStatus.IDLE

    def _retry_exhausted(self, task: LiveTask) -> bool:
        return (
            task.status is TaskStatus.ERROR
            and task.retry_count >= self.retry_coordinator.max_attempts
            and task.next_retry_at is None
        )

    def tasks(self) -> list[LiveTask]:
        with self._lock:
            return list(self._tasks)

    def get(self, task_id: str) -> LiveTask | None:
        with self._lock:
            return next((task for task in self._tasks if task.id == task_id), None)

    def add_task(self, task: LiveTask) -> None:
        if self._closing:
            raise RuntimeError("应用正在关闭，不能添加任务")
        with self._lock:
            task.status = self._resting_status(task)
            self._tasks.append(task)
            self._save_tasks(immediate=True)
        self.logger.info("已添加任务: %s", task.display_name)
        self._notify(task)
        self.monitor.poll_now([task])

    def update_task(self, task_id: str, **changes: object) -> None:
        if self._closing:
            raise RuntimeError("应用正在关闭，不能修改任务")
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        self.retry_coordinator.cancel(task_id)
        self._retry_blocked.discard(task_id)
        task.retry_count = 0
        task.next_retry_at = None
        with self._lock:
            if "anchor_name" in changes:
                task.set_manual_name(str(changes.pop("anchor_name") or ""))
            for key, value in changes.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            self._save_tasks(immediate=True)
        if not task.enabled:
            if self.recording_service.is_active(task.id):
                self.stop_recording(task.id)
            else:
                self._set_state(task, TaskStatus.DISABLED, persist=True)
            return
        if task.status is TaskStatus.DISABLED:
            self._set_state(task, self._resting_status(task), persist=True)
        else:
            self._notify(task)
        self.monitor.poll_now([task])

    def delete_task(self, task_id: str) -> bool:
        if self._closing:
            return False
        self.retry_coordinator.cancel(task_id)
        self._retry_blocked.discard(task_id)
        if self.recording_service.is_active(task_id):
            with self._lock:
                self._pending_deletions.add(task_id)
            self.stop_recording(task_id)
            return False
        with self._lock:
            self._tasks = [item for item in self._tasks if item.id != task_id]
            self._save_tasks(immediate=True)
        return True

    def update_settings(self, settings: AppSettings) -> None:
        with self._lock:
            self.settings = settings
            self.recording_service.update_ffmpeg_path(settings.ffmpeg_path)
            self.settings_store.save(settings)
        self.monitor.wake()

    def _save_tasks(self, *, immediate: bool = False) -> None:
        tasks = list(self._tasks)
        if immediate:
            self.persistence.save_now(tasks)
        else:
            self.persistence.request_save(tasks)

    def start_monitoring(self) -> None:
        if self._closing:
            return
        self.monitor.start()
        for task in self.tasks():
            if (
                task.enabled
                and not self.recording_service.is_active(task.id)
                and not self.retry_coordinator.pending(task.id)
                and not self._retry_exhausted(task)
                and task.id not in self._retry_blocked
            ):
                self._set_state(task, TaskStatus.MONITORING)

    def stop_monitoring(self) -> None:
        self.monitor.stop()
        for task in self.tasks():
            if (
                task.enabled
                and not self.recording_service.is_active(task.id)
                and not self.retry_coordinator.pending(task.id)
                and not self._retry_exhausted(task)
                and task.id not in self._retry_blocked
            ):
                self._set_state(task, TaskStatus.IDLE)

    def refresh_now(self) -> None:
        if self._closing:
            return
        self.monitor.poll_now()

    def _poll_task(self, task: LiveTask) -> None:
        if (
            self._closing
            or not task.enabled
            or self.recording_service.is_active(task.id)
            or self.retry_coordinator.pending(task.id)
            or self._retry_exhausted(task)
            or task.id in self._retry_blocked
        ):
            return
        self._set_state(task, TaskStatus.CHECKING)
        task.mark_checked()
        try:
            live_status = create_extractor(task.platform, self.settings).check_live_status(task.url)
            task.mark_checked()
            if self._closing:
                self._set_state(task, self._resting_status(task), persist=True)
                return
            task.apply_platform_name(live_status.anchor_name)
            if live_status.canonical_url:
                task.canonical_url = live_status.canonical_url
            if live_status.error:
                task.next_retry_at = None
                reason = RecordingService.classify_diagnostic(
                    live_status.parser_error or live_status.error
                )
                if reason in {
                    RecordingExitReason.AUTH_ERROR,
                    RecordingExitReason.PARSER_ERROR,
                }:
                    self._retry_blocked.add(task.id)
                self.logger.warning("%s: %s", task.display_name, live_status.error)
                self._set_state(
                    task, TaskStatus.ERROR, error=live_status.error, persist=True
                )
            elif live_status.is_live:
                self._set_state(task, TaskStatus.LIVE_DETECTED)
                if live_status.stream_url:
                    self.recording_service.start(task, live_status)
                else:
                    self._set_state(
                        task,
                        TaskStatus.ERROR,
                        error="已开播但没有可用的直播流地址",
                        persist=True,
                    )
            else:
                task.retry_count = 0
                task.next_retry_at = None
                self._set_state(task, self._resting_status(task), persist=True)
        except Exception as exc:
            self.logger.exception("检测任务失败: %s", task.display_name)
            self._set_state(task, TaskStatus.ERROR, error=str(exc), persist=True)

    def _recording_event(self, event: RecordingEvent) -> None:
        self.runtime_coordinator.handle_recording_event(event)

    def stop_recording(self, task_id: str) -> bool:
        self.retry_coordinator.cancel(task_id)
        task = self.get(task_id)
        if not task or not self.recording_service.is_active(task_id):
            return False
        self._set_state(task, TaskStatus.STOPPING)

        def stop_in_background() -> None:
            stopped = self.recording_service.stop(task_id)
            if not stopped and not self.recording_service.is_active(task_id):
                current = self.get(task_id)
                if current:
                    with self._lock:
                        pending_delete = task_id in self._pending_deletions
                        if pending_delete:
                            self._pending_deletions.discard(task_id)
                            self._tasks = [
                                item for item in self._tasks if item.id != task_id
                            ]
                            self._save_tasks(immediate=True)
                    if pending_delete:
                        self._notify(current)
                    else:
                        self._set_state(
                            current, self._resting_status(current), persist=True
                        )

        threading.Thread(
            target=stop_in_background,
            name=f"stop-recording-{task_id[:8]}",
            daemon=True,
        ).start()
        return True

    def prepare_shutdown_recordings(self) -> int:
        count = 0
        for task in self.tasks():
            if self.recording_service.is_active(task.id):
                self._set_state(task, TaskStatus.STOPPING)
                count += 1
        return count

    def stop_all_recordings(self, timeout: float = 20.0):
        self.prepare_shutdown_recordings()
        return self.recording_service.stop_all(timeout)

    def shutdown(self) -> None:
        self.begin_shutdown()
        self.stop_all_recordings()
        self.flush()
        self.persistence.close()

    def begin_shutdown(self) -> None:
        self._closing = True
        self.retry_coordinator.cancel_all()
        self.monitor.stop()

    def finalize_shutdown_states(self) -> None:
        for task in self.tasks():
            if task.status in {
                TaskStatus.MONITORING,
                TaskStatus.CHECKING,
                TaskStatus.LIVE_DETECTED,
                TaskStatus.STARTING_RECORD,
                TaskStatus.RECORDING,
                TaskStatus.STOPPING,
            }:
                self._set_state(task, self._resting_status(task))

    def flush(self, timeout: float = 5.0) -> bool:
        with self._lock:
            self._save_tasks(immediate=True)
            self.settings_store.save(self.settings)
        return self.persistence.flush(timeout)

    def _retry_task(self, task_id: str) -> None:
        task = self.get(task_id)
        if not task or not task.enabled or self._closing:
            return
        task.next_retry_at = None
        self._set_state(task, self._resting_status(task))
        self.monitor.poll_now([task])

    def retry_now(self, task_id: str) -> bool:
        task = self.get(task_id)
        if not task or not task.enabled or self._closing:
            return False
        self._retry_blocked.discard(task_id)
        if not self.retry_coordinator.pending(task_id):
            task.retry_count = 0
            task.next_retry_at = None
        self.retry_coordinator.trigger_now(task_id)
        return True
