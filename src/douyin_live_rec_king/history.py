"""Versioned recording history models and JSON storage."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import PlatformType, RecordingExitReason
from .utils.paths import resolve_app_path
from .utils.json_recovery import atomic_write_json, load_json_with_recovery


@dataclass(slots=True)
class RecordingHistoryEntry:
    task_id: str
    platform: PlatformType
    anchor_name: str
    room_url: str
    session_id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    output_mode: str = "ts"
    files: list[str] = field(default_factory=list)
    total_size_bytes: int = 0
    duration_seconds: float = 0.0
    status: str = "starting"
    exit_reason: RecordingExitReason | None = None
    return_code: int | None = None
    retry_number: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    conversion_status: str = "not_requested"
    converted_files: list[str] = field(default_factory=list)
    media_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["platform"] = self.platform.value
        data["exit_reason"] = self.exit_reason.value if self.exit_reason else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecordingHistoryEntry":
        payload = dict(data)
        payload["platform"] = PlatformType(payload.get("platform", "douyin"))
        reason = payload.get("exit_reason")
        payload["exit_reason"] = RecordingExitReason(reason) if reason else None
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in payload.items() if key in allowed})


class RecordingHistoryStore:
    def __init__(
        self,
        path: str | Path = "data/recording_history.json",
        max_entries: int = 1000,
    ) -> None:
        self.path = resolve_app_path(path)
        self.max_entries = max(1, max_entries)
        self._lock = threading.RLock()

    def load(self) -> list[RecordingHistoryEntry]:
        with self._lock:
            if not self.path.exists():
                self.save([])
                return []
            try:
                payload, _recovered_from = load_json_with_recovery(self.path)
                rows = payload.get("entries", []) if isinstance(payload, dict) else payload
                return [RecordingHistoryEntry.from_dict(row) for row in rows]
            except (OSError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
                raise RuntimeError(f"无法读取录制历史 {self.path}: {exc}") from exc

    def save(
        self, entries: list[RecordingHistoryEntry]
    ) -> list[RecordingHistoryEntry]:
        with self._lock:
            retained = sorted(
                entries,
                key=lambda item: item.ended_at or item.started_at or "",
                reverse=True,
            )[: self.max_entries]
            atomic_write_json(
                self.path,
                {
                    "version": 1,
                    "entries": [entry.to_dict() for entry in retained],
                },
            )
            return retained
