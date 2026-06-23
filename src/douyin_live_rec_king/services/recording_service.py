"""Recording orchestration without UI dependencies."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from ..models import AppSettings, LiveStatus, LiveTask, RecordingExitReason
from ..recording.events import RecordingEvent, RecordingEventType
from ..recording.recorder import Recorder, RecorderExitResult, StopAllResult
from ..utils.filenames import recording_path
from ..utils.paths import resolve_app_path
from .storage_guard import StorageGuard
from .recording_history import RecordingHistoryService

RecordingEventHandler = Callable[[RecordingEvent], None]


class RecordingService:
    def __init__(
        self,
        settings_provider: Callable[[], AppSettings],
        logger: logging.Logger,
        on_event: RecordingEventHandler,
        recorder: Recorder | None = None,
        storage_guard: StorageGuard | None = None,
        history_service: RecordingHistoryService | None = None,
    ) -> None:
        self.settings_provider = settings_provider
        self.logger = logger
        self.on_event = on_event
        settings = settings_provider()
        self.recorder = recorder or Recorder(settings.ffmpeg_path, logger)
        self.storage_guard = storage_guard or StorageGuard()
        self.history_service = history_service
        self._stop_requested: set[str] = set()
        self._sessions: dict[str, str] = {}
        self._lock = threading.RLock()

    def update_ffmpeg_path(self, path: str) -> None:
        self.recorder.ffmpeg.custom_path = path

    def is_recording(self, task_id: str) -> bool:
        return self.recorder.is_recording(task_id)

    def is_active(self, task_id: str) -> bool:
        return self.recorder.is_active(task_id)

    def start(self, task: LiveTask, status: LiveStatus) -> str | None:
        if not status.stream_url:
            self.on_event(
                RecordingEvent(
                    task.id,
                    RecordingEventType.ERROR,
                    error="已开播但没有可用的直播流地址",
                    exit_reason=RecordingExitReason.PARSER_ERROR,
                )
            )
            return None
        settings = self.settings_provider()
        output_root = resolve_app_path(settings.output_directory)
        storage = self.storage_guard.check(output_root, settings.disk_threshold_gb)
        if not storage.ok:
            self.on_event(
                RecordingEvent(
                    task.id,
                    RecordingEventType.ERROR,
                    error=storage.error,
                    exit_reason=RecordingExitReason.STORAGE_ERROR,
                )
            )
            return None
        output = recording_path(
            storage.output_directory,
            task.platform.value,
            task.display_name,
            settings.default_format,
            settings.filename_template,
            status.title or "",
            settings.folder_by_platform,
            settings.folder_by_anchor,
            settings.segmented_recording,
        )
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if self.history_service:
            entry = self.history_service.create(
                task, status, str(output), settings.default_format
            )
            started_at = entry.started_at or started_at
            with self._lock:
                self._sessions[task.id] = entry.session_id
        self.on_event(
            RecordingEvent(
                task.id,
                RecordingEventType.STARTING,
                output_file=str(output),
                started_at=started_at,
            )
        )
        start_error_reported = False

        def on_state(task_id: str, state: str, error: str | None) -> None:
            nonlocal start_error_reported
            if state == "error":
                start_error_reported = True
            self._on_state(task_id, state, error)

        try:
            fallback_cookie = (
                settings.douyin_cookie
                if task.platform.value == "douyin"
                else settings.bilibili_cookie
                if task.platform.value == "bilibili"
                else ""
            )
            self.recorder.start(
                task.id,
                status.stream_url,
                output,
                self._on_exit,
                on_state,
                proxy=settings.proxy,
                segmented=settings.segmented_recording,
                segment_seconds=settings.segment_seconds,
                convert_mp4=settings.auto_convert_mp4,
                delete_original=settings.delete_original,
                headers=status.headers,
                user_agent=status.user_agent,
                referer=status.referer,
                cookie=status.cookie or fallback_cookie or None,
            )
        except Exception as exc:
            with self._lock:
                session_id = self._sessions.pop(task.id, None)
            if self.history_service and session_id:
                self.history_service.finish(
                    session_id,
                    output_file=str(output),
                    duration_seconds=0.0,
                    return_code=None,
                    reason=RecordingExitReason.FFMPEG_ERROR,
                    error=str(exc),
                )
            if not start_error_reported:
                self.on_event(
                    RecordingEvent(
                        task.id,
                        RecordingEventType.ERROR,
                        output_file=str(output),
                        error=str(exc),
                        exit_reason=RecordingExitReason.FFMPEG_ERROR,
                    )
                )
            return None
        return str(output)

    def stop(self, task_id: str) -> bool:
        with self._lock:
            self._stop_requested.add(task_id)
        stopped = self.recorder.stop(task_id)
        if not stopped:
            with self._lock:
                self._stop_requested.discard(task_id)
        return stopped

    def stop_all(self, timeout: float = 20.0) -> StopAllResult:
        with self._lock:
            self._stop_requested.update(self.recorder.active_ids())
        return self.recorder.stop_all(timeout)

    def force_stop_all(self) -> int:
        return self.recorder.force_stop_all()

    def _on_state(self, task_id: str, state: str, error: str | None) -> None:
        event_type = (
            RecordingEventType.RECORDING
            if state == "recording"
            else RecordingEventType.ERROR
        )
        with self._lock:
            session_id = self._sessions.get(task_id)
        if (
            state == "recording"
            and session_id
            and self.history_service is not None
        ):
            self.history_service.mark_recording(session_id)
        self.on_event(RecordingEvent(task_id, event_type, error=error))

    @staticmethod
    def classify_diagnostic(diagnostic: str | None) -> RecordingExitReason:
        text = (diagnostic or "").lower()
        if any(
            token in text
            for token in (
                "cookie",
                "unauthorized",
                "forbidden",
                "http error 401",
                "http error 403",
                "风控",
            )
        ):
            return RecordingExitReason.AUTH_ERROR
        if any(
            token in text
            for token in (
                "invalid data",
                "unsupported",
                "parser",
                "expecting value",
                "json decode",
                "execjs",
                "缺少 streamget",
                "需要 node.js",
                "地址已失效",
            )
        ):
            return RecordingExitReason.PARSER_ERROR
        if any(
            token in text
            for token in (
                "timed out",
                "timeout",
                "connection reset",
                "connection refused",
                "temporary failure in name resolution",
                "server returned 5",
                "http error 5",
                "end of file",
                " econnreset",
                "broken pipe",
                "input/output error",
            )
        ):
            return RecordingExitReason.NETWORK_ERROR
        return RecordingExitReason.FFMPEG_ERROR

    @classmethod
    def classify_exit(
        cls, result: RecorderExitResult, expected_stop: bool
    ) -> RecordingExitReason:
        if expected_stop:
            return RecordingExitReason.MANUAL_STOP
        if result.conversion_failed:
            return RecordingExitReason.CONVERSION_ERROR
        if result.return_code == 0:
            return RecordingExitReason.LIVE_ENDED
        return cls.classify_diagnostic(result.diagnostic)

    def _on_exit(self, task_id: str, result: RecorderExitResult) -> None:
        with self._lock:
            manually_stopped = task_id in self._stop_requested
            self._stop_requested.discard(task_id)
            session_id = self._sessions.pop(task_id, None)
        reason = self.classify_exit(result, manually_stopped)
        error = (
            None
            if result.return_code == 0 or manually_stopped
            else result.diagnostic or f"FFmpeg 返回码 {result.return_code}"
        )
        if self.history_service and session_id:
            self.history_service.finish(
                session_id,
                output_file=result.final_path,
                duration_seconds=result.duration_seconds,
                return_code=result.return_code,
                reason=reason,
                error=error,
                source_files=result.source_files,
                converted_files=result.converted_files,
            )
        self.on_event(
            RecordingEvent(
                task_id,
                RecordingEventType.EXITED,
                output_file=result.final_path,
                error=error,
                return_code=result.return_code,
                expected_stop=manually_stopped,
                started_at=result.started_at,
                ended_at=result.ended_at,
                duration_seconds=result.duration_seconds,
                diagnostic=result.diagnostic,
                exit_reason=reason,
                source_files=result.source_files,
                converted_files=result.converted_files,
            )
        )
