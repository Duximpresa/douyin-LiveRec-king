"""Lightweight application service container and lifecycle owner."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..config import SettingsStore, TaskStore, migrate_legacy_config
from ..history import RecordingHistoryStore
from ..logging_setup import configure_logging
from ..models import AppSettings, LiveTask, TaskStatus
from .persistence import TaskPersistenceCoordinator
from .file_integrity import FileIntegrityGuard
from .media_probe import MediaProbeService
from .recording_history import RecordingHistoryService
from .statistics import RecordingStatisticsService
from .task_manager import TaskManager
from ..utils.paths import resolve_app_path

ProgressCallback = Callable[[str, int, int], None]
CompletionCallback = Callable[[bool, str | None], None]


class ApplicationServices:
    def __init__(
        self,
        settings_store: SettingsStore,
        task_store: TaskStore,
        settings: AppSettings,
        tasks: list[LiveTask],
        logger: logging.Logger,
    ) -> None:
        self.settings_store = settings_store
        self.task_store = task_store
        self.settings = settings
        self.tasks = tasks
        self.logger = logger
        self.persistence = TaskPersistenceCoordinator(task_store, logger)
        self.file_integrity_guard = FileIntegrityGuard()
        self.media_probe_service = MediaProbeService(settings.ffmpeg_path)
        self.recording_history_store = RecordingHistoryStore(
            task_store.path.parent / "recording_history.json"
        )
        self.recording_history_service = RecordingHistoryService(
            self.recording_history_store,
            self.file_integrity_guard,
            self.media_probe_service,
        )
        self.statistics_service = RecordingStatisticsService(
            self.recording_history_service.list_entries
        )
        self.task_manager = TaskManager(
            task_store,
            settings_store,
            tasks,
            settings,
            logger,
            persistence=self.persistence,
            history_service=self.recording_history_service,
        )
        self.monitor = self.task_manager.monitor
        self.recording_service = self.task_manager.recording_service
        self.recorder = self.recording_service.recorder
        self.retry_coordinator = self.task_manager.retry_coordinator
        self.recovery_files = self.recording_history_service.scan_interrupted(
            resolve_app_path(settings.output_directory)
        )
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_thread: threading.Thread | None = None

    @classmethod
    def bootstrap(
        cls,
        *,
        settings_store: SettingsStore | None = None,
        task_store: TaskStore | None = None,
        settings: AppSettings | None = None,
        tasks: list[LiveTask] | None = None,
        logger: logging.Logger | None = None,
        migrate: bool = True,
    ) -> "ApplicationServices":
        settings_store = settings_store or SettingsStore()
        task_store = task_store or TaskStore()
        if migrate:
            migrate_legacy_config(
                settings_store=settings_store, task_store=task_store
            )
        settings = settings or settings_store.load()
        tasks = tasks if tasks is not None else task_store.load()
        logger = logger or configure_logging(settings.log_level)
        changed = cls.recover_runtime_state(tasks)
        services = cls(settings_store, task_store, settings, tasks, logger)
        if changed:
            services.persistence.save_now(tasks)
        return services

    @staticmethod
    def recover_runtime_state(tasks: list[LiveTask]) -> bool:
        changed = False
        interrupted = {
            TaskStatus.STARTING_RECORD,
            TaskStatus.RECORDING,
            TaskStatus.STOPPING,
        }
        transient = {
            TaskStatus.MONITORING,
            TaskStatus.CHECKING,
            TaskStatus.LIVE_DETECTED,
            *interrupted,
        }
        for task in tasks:
            if task.retry_count:
                task.retry_count = 0
                changed = True
            if task.next_retry_at is not None:
                task.next_retry_at = None
                changed = True
            if not task.enabled:
                if task.status is not TaskStatus.DISABLED:
                    task.status = TaskStatus.DISABLED
                    changed = True
                continue
            previous = task.status
            if previous in transient:
                task.status = TaskStatus.IDLE
                if previous in interrupted:
                    task.last_error = "上次运行未正常结束，录制状态已重置"
                changed = True
        return changed

    @property
    def shutting_down(self) -> bool:
        with self._shutdown_lock:
            return self._shutdown_started

    def shutdown_async(
        self,
        progress_callback: ProgressCallback | None = None,
        completion_callback: CompletionCallback | None = None,
    ) -> bool:
        with self._shutdown_lock:
            if self._shutdown_started:
                return False
            self._shutdown_started = True

        def progress(stage: str, current: int = 0, total: int = 0) -> None:
            if progress_callback:
                try:
                    progress_callback(stage, current, total)
                except Exception:
                    self.logger.exception("关闭进度回调失败")

        def complete(ok: bool, error: str | None) -> None:
            if completion_callback:
                try:
                    completion_callback(ok, error)
                except Exception:
                    self.logger.exception("关闭完成回调失败")

        def worker() -> None:
            error: str | None = None
            ok = True
            try:
                progress("正在停止直播检测")
                self.task_manager.begin_shutdown()
                total = self.task_manager.prepare_shutdown_recordings()
                progress("正在停止录制", 0, total)
                result = self.recording_service.stop_all(timeout=20.0)
                progress("正在停止录制", total, total)
                if result.timed_out or result.failed:
                    ok = False
                    error = (
                        f"部分录制未能正常停止：超时 {len(result.timed_out)}，"
                        f"失败 {len(result.failed)}"
                    )
                    self.logger.warning(error)
                progress("正在保存任务状态")
                self.task_manager.finalize_shutdown_states()
                if not self.flush(timeout=5.0):
                    ok = False
                    error = error or "任务状态保存超时或失败"
                self.persistence.close(timeout=5.0)
            except Exception as exc:
                ok = False
                error = str(exc)
                self.logger.exception("应用收尾失败")
                try:
                    self.recording_service.force_stop_all()
                except Exception:
                    self.logger.exception("强制清理录制进程失败")
            finally:
                complete(ok, error)

        thread = threading.Thread(
            target=worker, name="application-shutdown", daemon=True
        )
        self._shutdown_thread = thread
        thread.start()
        return True

    def flush(self, timeout: float = 5.0) -> bool:
        return self.task_manager.flush(timeout)
