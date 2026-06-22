"""Project path resolution that remains predictable in source and frozen builds."""

from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def resolve_app_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root() / path

