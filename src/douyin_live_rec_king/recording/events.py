"""Typed recording lifecycle events shared by services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..models import RecordingExitReason


class RecordingEventType(StrEnum):
    STARTING = "starting"
    RECORDING = "recording"
    ERROR = "error"
    EXITED = "exited"


@dataclass(frozen=True, slots=True)
class RecordingEvent:
    task_id: str
    type: RecordingEventType
    output_file: str | None = None
    error: str | None = None
    return_code: int | None = None
    expected_stop: bool = False
    started_at: str | None = None
    ended_at: str | None = None
    duration_seconds: float | None = None
    diagnostic: str | None = None
    exit_reason: RecordingExitReason | None = None
    source_files: tuple[str, ...] = ()
    converted_files: tuple[str, ...] = ()
