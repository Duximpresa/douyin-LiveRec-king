"""Recording history lifecycle, querying, recovery, and safe deletion."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..history import RecordingHistoryEntry, RecordingHistoryStore
from ..models import LiveStatus, LiveTask, RecordingExitReason
from .file_integrity import FileIntegrityGuard
from .media_probe import MediaProbeService

HistoryListener = Callable[[], None]


class RecordingHistoryService:
    def __init__(
        self,
        store: RecordingHistoryStore,
        integrity_guard: FileIntegrityGuard,
        media_probe: MediaProbeService | None = None,
    ) -> None:
        self.store = store
        self.integrity_guard = integrity_guard
        self.media_probe = media_probe or MediaProbeService()
        self._lock = threading.RLock()
        self._entries = store.load()
        self._listeners: list[HistoryListener] = []

    def add_listener(self, listener: HistoryListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                continue

    def _save_locked(self) -> None:
        self._entries = self.store.save(self._entries)

    def list_entries(
        self, status: str | None = None, query: str = ""
    ) -> list[RecordingHistoryEntry]:
        with self._lock:
            entries = list(self._entries)
        if status and status != "all":
            if status == "recording":
                entries = [
                    entry
                    for entry in entries
                    if entry.status in {"starting", "recording"}
                ]
            else:
                entries = [entry for entry in entries if entry.status == status]
        text = query.strip().lower()
        if text:
            entries = [
                entry
                for entry in entries
                if text in entry.anchor_name.lower()
                or text in entry.title.lower()
                or text in entry.room_url.lower()
            ]
        return sorted(
            entries,
            key=lambda item: item.ended_at or item.started_at or "",
            reverse=True,
        )

    def get(self, session_id: str) -> RecordingHistoryEntry | None:
        with self._lock:
            return next(
                (entry for entry in self._entries if entry.session_id == session_id),
                None,
            )

    def create(
        self,
        task: LiveTask,
        status: LiveStatus,
        output_file: str,
        output_mode: str,
    ) -> RecordingHistoryEntry:
        entry = RecordingHistoryEntry(
            task_id=task.id,
            platform=task.platform,
            anchor_name=task.display_name,
            room_url=task.canonical_url or task.url,
            title=status.title or "",
            started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            output_mode=output_mode,
            files=[output_file],
            retry_number=task.retry_count,
        )
        with self._lock:
            self._entries.append(entry)
            self._save_locked()
        self._notify()
        return entry

    def mark_recording(self, session_id: str) -> None:
        entry = self.get(session_id)
        if not entry:
            return
        with self._lock:
            entry.status = "recording"
            self._save_locked()
        self._notify()

    def finish(
        self,
        session_id: str,
        *,
        output_file: str | None,
        duration_seconds: float,
        return_code: int | None,
        reason: RecordingExitReason,
        error: str | None,
        source_files: tuple[str, ...] = (),
        converted_files: tuple[str, ...] = (),
    ) -> RecordingHistoryEntry | None:
        entry = self.get(session_id)
        if not entry:
            return None
        integrity = self.integrity_guard.inspect(
            output_file or (entry.files[0] if entry.files else None)
        )
        existing_sources = [
            value for value in source_files if Path(value).exists()
        ]
        existing_converted = [
            value for value in converted_files if Path(value).exists()
        ]
        all_existing = list(dict.fromkeys([*existing_sources, *existing_converted]))
        total_size = 0
        for value in all_existing:
            try:
                total_size += Path(value).stat().st_size
            except OSError:
                pass
        with self._lock:
            entry.ended_at = datetime.now().astimezone().isoformat(timespec="seconds")
            entry.duration_seconds = max(0.0, duration_seconds)
            entry.return_code = return_code
            entry.exit_reason = reason
            entry.error = error or integrity.error
            entry.files = existing_sources or (
                [] if existing_converted else list(integrity.files)
            )
            entry.total_size_bytes = total_size or integrity.total_size_bytes
            entry.warnings = list(integrity.warnings)
            entry.converted_files = existing_converted
            probe_target = (
                existing_converted[0]
                if existing_converted
                else existing_sources[0]
                if existing_sources
                else output_file
            )
            if probe_target:
                probe = self.media_probe.probe(probe_target)
                entry.media_info = probe.to_dict()
                if probe.error and probe.error not in entry.warnings:
                    entry.warnings.append(probe.error)
            if reason is RecordingExitReason.CONVERSION_ERROR:
                entry.status = "conversion_failed"
                entry.conversion_status = "failed"
            elif converted_files:
                entry.status = "success" if integrity.ok else "failed"
                entry.conversion_status = "completed"
            elif reason is RecordingExitReason.INTERRUPTED:
                entry.status = "interrupted"
            elif reason in {
                RecordingExitReason.COMPLETED,
                RecordingExitReason.MANUAL_STOP,
                RecordingExitReason.LIVE_ENDED,
            } and integrity.ok:
                entry.status = "success"
            else:
                entry.status = "failed"
            self._save_locked()
        self._notify()
        return entry

    def delete_entry(self, session_id: str) -> bool:
        with self._lock:
            original = len(self._entries)
            self._entries = [
                entry for entry in self._entries if entry.session_id != session_id
            ]
            if len(self._entries) == original:
                return False
            self._save_locked()
        self._notify()
        return True

    def delete_entries(self, session_ids: list[str]) -> int:
        targets = set(session_ids)
        with self._lock:
            original = len(self._entries)
            self._entries = [
                entry for entry in self._entries if entry.session_id not in targets
            ]
            deleted = original - len(self._entries)
            if deleted:
                self._save_locked()
        if deleted:
            self._notify()
        return deleted

    def delete_files(self, session_id: str) -> tuple[int, list[str]]:
        entry = self.get(session_id)
        if not entry:
            return 0, ["历史记录不存在"]
        deleted = 0
        errors: list[str] = []
        for value in dict.fromkeys([*entry.files, *entry.converted_files]):
            try:
                path = Path(value)
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted += 1
            except OSError as exc:
                errors.append(f"{value}: {exc}")
        if not errors:
            with self._lock:
                entry.files = []
                entry.converted_files = []
                entry.total_size_bytes = 0
                self._save_locked()
            self._notify()
        return deleted, errors

    def scan_interrupted(self, output_root: Path) -> list[str]:
        recovery_items: list[str] = []
        with self._lock:
            interrupted = [
                entry
                for entry in self._entries
                if entry.status in {"starting", "recording"}
            ]
        for entry in interrupted:
            recovery_items.extend(entry.files or [f"history:{entry.session_id}"])
            self.finish(
                entry.session_id,
                output_file=entry.files[0] if entry.files else None,
                duration_seconds=entry.duration_seconds,
                return_code=entry.return_code,
                reason=RecordingExitReason.INTERRUPTED,
                error="上次运行未正常结束",
            )
        recovery_items.extend(self.integrity_guard.scan_temporary(output_root))
        return sorted(dict.fromkeys(recovery_items))

    def rescan(self, session_id: str | None = None) -> int:
        entries = [self.get(session_id)] if session_id else self.list_entries()
        changed = 0
        for entry in entries:
            if not entry:
                continue
            target = next(
                (
                    value
                    for value in [*entry.converted_files, *entry.files]
                    if Path(value).exists()
                ),
                None,
            )
            integrity = self.integrity_guard.inspect(target)
            probe = self.media_probe.probe(target) if target else None
            with self._lock:
                entry.total_size_bytes = integrity.total_size_bytes
                entry.warnings = list(integrity.warnings)
                if integrity.error:
                    entry.error = integrity.error
                if probe:
                    entry.media_info = probe.to_dict()
                    if probe.duration_seconds is not None:
                        entry.duration_seconds = probe.duration_seconds
                self._save_locked()
            changed += 1
        if changed:
            self._notify()
        return changed

    def remux_interrupted(self, session_id: str) -> Path:
        entry = self.get(session_id)
        if not entry:
            raise KeyError(session_id)
        source = next(
            (
                Path(value)
                for value in entry.files
                if Path(value).suffix.lower() == ".ts" and Path(value).exists()
            ),
            None,
        )
        if not source:
            raise FileNotFoundError("没有可转封装的 TS 文件")
        target = self.media_probe.remux(source, delete_original=False)
        with self._lock:
            if str(target) not in entry.converted_files:
                entry.converted_files.append(str(target))
            entry.conversion_status = "completed"
            entry.media_info = self.media_probe.probe(target).to_dict()
            self._save_locked()
        self._notify()
        return target

    def cleanup_temporary(self, paths: list[str]) -> tuple[int, list[str]]:
        deleted = 0
        errors: list[str] = []
        for value in paths:
            path = Path(value)
            if path.suffix.lower() not in {".tmp", ".part"}:
                errors.append(f"拒绝清理非临时文件: {path}")
                continue
            try:
                if path.exists():
                    path.unlink()
                    deleted += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        return deleted, errors
