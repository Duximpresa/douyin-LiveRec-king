"""Helpers for atomic JSON writes and recovery from corrupted files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".last-good.bak"))
    temporary.replace(path)


def load_json_with_recovery(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as original:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        corrupt_backup = path.with_name(f"{path.name}.corrupt-{stamp}.bak")
        try:
            if path.exists():
                shutil.copy2(path, corrupt_backup)
        except OSError:
            pass
        candidates = [
            path.with_suffix(path.suffix + ".tmp"),
            path.with_suffix(path.suffix + ".last-good.bak"),
            *sorted(
                path.parent.glob(f"{path.name}.backup-*.bak"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            ),
        ]
        for candidate in candidates:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                atomic_write_json(path, payload)
                return payload, str(candidate)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        raise RuntimeError(
            f"JSON 文件损坏且无法恢复: {path}; 损坏备份: {corrupt_backup}; "
            f"原始错误: {original}"
        ) from original
