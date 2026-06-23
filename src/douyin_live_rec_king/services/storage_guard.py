"""Output-directory and free-space checks for recording startup."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageCheckResult:
    ok: bool
    output_directory: Path
    free_gb: float | None
    threshold_gb: float
    error: str | None = None


class StorageGuard:
    def check(self, output_directory: Path, threshold_gb: float) -> StorageCheckResult:
        threshold = max(0.0, float(threshold_gb))
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
            if not output_directory.is_dir():
                raise NotADirectoryError(str(output_directory))
            free_gb = shutil.disk_usage(output_directory).free / (1024**3)
        except (OSError, ValueError) as exc:
            return StorageCheckResult(
                False, output_directory, None, threshold, f"无法使用录制目录: {exc}"
            )
        if threshold > 0 and free_gb < threshold:
            return StorageCheckResult(
                False,
                output_directory,
                free_gb,
                threshold,
                f"磁盘剩余 {free_gb:.2f} GB，低于阈值 {threshold:.2f} GB",
            )
        return StorageCheckResult(True, output_directory, free_gb, threshold)
