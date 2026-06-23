"""Recording-history statistics and Excel-friendly CSV exports."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from ..history import RecordingHistoryEntry


class RecordingStatisticsService:
    def __init__(self, entries_provider) -> None:
        self.entries_provider = entries_provider

    def _entries(self) -> list[RecordingHistoryEntry]:
        return list(self.entries_provider())

    @staticmethod
    def _within(entry: RecordingHistoryEntry, days: int) -> bool:
        value = entry.ended_at or entry.started_at
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed >= (datetime.now(timezone.utc) - timedelta(days=days))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _summary(entries: Iterable[RecordingHistoryEntry]) -> dict[str, float | int]:
        rows = list(entries)
        successes = sum(1 for item in rows if item.status == "success")
        return {
            "count": len(rows),
            "success_count": successes,
            "success_rate": successes / len(rows) if rows else 0.0,
            "duration_seconds": sum(item.duration_seconds for item in rows),
            "size_bytes": sum(item.total_size_bytes for item in rows),
        }

    def summary(self) -> dict[str, object]:
        entries = self._entries()
        return {
            "all": self._summary(entries),
            "last_7_days": self._summary(
                item for item in entries if self._within(item, 7)
            ),
            "last_30_days": self._summary(
                item for item in entries if self._within(item, 30)
            ),
        }

    def _group(self, key_fn) -> list[dict[str, object]]:
        grouped: dict[str, list[RecordingHistoryEntry]] = defaultdict(list)
        for entry in self._entries():
            grouped[str(key_fn(entry))].append(entry)
        return [
            {"key": key, **self._summary(rows)}
            for key, rows in sorted(grouped.items())
        ]

    def by_anchor(self) -> list[dict[str, object]]:
        return self._group(lambda item: item.anchor_name or "未知主播")

    def by_platform(self) -> list[dict[str, object]]:
        return self._group(lambda item: item.platform.value)

    def by_date(self) -> list[dict[str, object]]:
        return self._group(
            lambda item: (item.ended_at or item.started_at or "未知日期")[:10]
        )

    @staticmethod
    def _write(path: Path, headers: list[str], rows: Iterable[dict[str, object]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def export_csv(self, kind: str, path: str | Path) -> Path:
        target = Path(path)
        if kind == "history":
            rows = [
                {
                    "session_id": item.session_id,
                    "platform": item.platform.value,
                    "anchor": item.anchor_name,
                    "title": item.title,
                    "started_at": item.started_at or "",
                    "ended_at": item.ended_at or "",
                    "status": item.status,
                    "duration_seconds": item.duration_seconds,
                    "size_bytes": item.total_size_bytes,
                    "files": ";".join([*item.files, *item.converted_files]),
                    "error": item.error or "",
                }
                for item in self._entries()
            ]
            return self._write(target, list(rows[0]) if rows else [
                "session_id", "platform", "anchor", "title", "started_at",
                "ended_at", "status", "duration_seconds", "size_bytes", "files", "error"
            ], rows)
        rows = (
            self.by_date()
            if kind == "daily"
            else [
                {"dimension": "anchor", **row} for row in self.by_anchor()
            ]
            + [
                {"dimension": "platform", **row} for row in self.by_platform()
            ]
        )
        headers = (
            ["key", "count", "success_count", "success_rate", "duration_seconds", "size_bytes"]
            if kind == "daily"
            else ["dimension", "key", "count", "success_count", "success_rate", "duration_seconds", "size_bytes"]
        )
        return self._write(target, headers, rows)
