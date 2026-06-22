"""Coordinates persistence, concurrent extraction, task state, and recording."""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable

from ..config import SettingsStore, TaskStore
from ..models import AppSettings, LiveTask, NicknameSource, TaskStatus
from ..platforms.registry import create_extractor
from ..recording.recorder import Recorder
from ..utils.filenames import recording_path
from ..utils.paths import resolve_app_path
from .monitor import Monitor

TaskListener = Callable[[LiveTask], None]


class TaskManager:
    def __init__(
        self,
        task_store: TaskStore,
        settings_store: SettingsStore,
        tasks: list[LiveTask],
        settings: AppSettings,
        logger: logging.Logger,
    ) -> None:
        self.task_store = task_store
        self.settings_store = settings_store
        self._tasks = tasks
        self.settings = settings
        self.logger = logger
        self._lock = threading.RLock()
        self._listeners: list[TaskListener] = []
        self.recorder = Recorder(settings.ffmpeg_path, logger)
        self.monitor = Monitor(
            self.tasks,
            self._poll_task,
            lambda: self.settings.check_interval_seconds,
            lambda: self.settings.max_concurrent_checks,
            logger,
        )
        for task in self._tasks:
            task.status = TaskStatus.IDLE if task.enabled else TaskStatus.DISABLED

    def add_listener(self, listener: TaskListener) -> None:
        self._listeners.append(listener)

    def _notify(self, task: LiveTask) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(task)
            except Exception:
                self.logger.exception("任务状态监听器执行失败")

    def tasks(self) -> list[LiveTask]:
        with self._lock:
            return list(self._tasks)

    def get(self, task_id: str) -> LiveTask | None:
        return next((task for task in self.tasks() if task.id == task_id), None)

    def add_task(self, task: LiveTask) -> None:
        with self._lock:
            self._tasks.append(task)
            self._save_tasks()
        self.logger.info("已添加任务: %s", task.display_name)
        self._notify(task)
        self.monitor.wake()

    def update_task(self, task_id: str, **changes: object) -> None:
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        with self._lock:
            if "anchor_name" in changes:
                task.set_manual_name(str(changes.pop("anchor_name") or ""))
            for key, value in changes.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            if not task.enabled:
                self.stop_recording(task.id)
                task.status = TaskStatus.DISABLED
            elif task.status is TaskStatus.DISABLED:
                task.status = TaskStatus.IDLE
            self._save_tasks()
        self._notify(task)
        self.monitor.wake()

    def delete_task(self, task_id: str) -> None:
        self.stop_recording(task_id)
        with self._lock:
            self._tasks = [item for item in self._tasks if item.id != task_id]
            self._save_tasks()

    def update_settings(self, settings: AppSettings) -> None:
        with self._lock:
            self.settings = settings
            self.recorder.ffmpeg.custom_path = settings.ffmpeg_path
            self.settings_store.save(settings)
        self.monitor.wake()

    def _save_tasks(self) -> None:
        self.task_store.save(self._tasks)

    def start_monitoring(self) -> None:
        self.monitor.start()

    def stop_monitoring(self) -> None:
        self.monitor.stop()

    def refresh_now(self) -> None:
        if not self.monitor.running:
            threading.Thread(target=self._refresh_once, name="manual-refresh", daemon=True).start()
        else:
            self.monitor.wake()

    def _refresh_once(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        enabled = [task for task in self.tasks() if task.enabled]
        with ThreadPoolExecutor(max_workers=self.settings.max_concurrent_checks) as executor:
            list(executor.map(self._poll_task, enabled))

    def _poll_task(self, task: LiveTask) -> None:
        if self.recorder.is_recording(task.id):
            return
        task.status = TaskStatus.CHECKING
        task.mark_checked()
        self._notify(task)
        try:
            status = create_extractor(task.platform, self.settings).check_live_status(task.url)
            task.mark_checked()
            task.apply_platform_name(status.anchor_name)
            if status.canonical_url:
                task.canonical_url = status.canonical_url
            if status.error:
                task.status = TaskStatus.ERROR
                task.last_error = status.error
                self.logger.warning("%s: %s", task.display_name, status.error)
            elif status.is_live and status.stream_url:
                self._start_recording(task, status.stream_url, status.title or "")
            else:
                task.status = TaskStatus.IDLE
                task.last_error = None
        except Exception as exc:
            task.status = TaskStatus.ERROR
            task.last_error = str(exc)
            self.logger.exception("检测任务失败: %s", task.display_name)
        finally:
            with self._lock:
                self._save_tasks()
            self._notify(task)

    def _start_recording(self, task: LiveTask, stream_url: str, title: str) -> None:
        output_root = resolve_app_path(self.settings.output_directory)
        output_root.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(output_root).free / (1024 ** 3)
        if free_gb < self.settings.disk_threshold_gb:
            raise RuntimeError(
                f"磁盘剩余 {free_gb:.2f} GB，低于阈值 {self.settings.disk_threshold_gb:.2f} GB"
            )
        output = recording_path(
            output_root,
            task.platform.value,
            task.display_name,
            self.settings.default_format,
            self.settings.filename_template,
            title,
            self.settings.folder_by_platform,
            self.settings.folder_by_anchor,
            self.settings.segmented_recording,
        )
        self.recorder.start(
            task.id,
            stream_url,
            output,
            self._recording_exited,
            proxy=self.settings.proxy,
            segmented=self.settings.segmented_recording,
            segment_seconds=self.settings.segment_seconds,
            convert_mp4=self.settings.auto_convert_mp4,
            delete_original=self.settings.delete_original,
        )
        task.recording_file = str(output)
        task.status = TaskStatus.RECORDING
        task.last_error = None
        self.logger.info("检测到开播，开始录制: %s", task.display_name)

    def _recording_exited(
        self, task_id: str, return_code: int, final_path: str | None
    ) -> None:
        task = self.get(task_id)
        if not task:
            return
        task.status = TaskStatus.IDLE if return_code == 0 else TaskStatus.ERROR
        task.last_error = None if return_code == 0 else f"FFmpeg 返回码 {return_code}"
        if final_path:
            task.recording_file = final_path
        with self._lock:
            self._save_tasks()
        self._notify(task)

    def stop_recording(self, task_id: str) -> bool:
        stopped = self.recorder.stop(task_id)
        task = self.get(task_id)
        if task and stopped:
            task.status = TaskStatus.IDLE if task.enabled else TaskStatus.DISABLED
            self._notify(task)
        return stopped

    def stop_all_recordings(self) -> None:
        self.recorder.stop_all()

    def shutdown(self) -> None:
        self.monitor.stop()
        self.recorder.stop_all()
        self._save_tasks()
        self.settings_store.save(self.settings)
