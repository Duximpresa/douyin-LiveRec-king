"""Non-destructive recording file discovery and integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileIntegrityResult:
    files: tuple[str, ...]
    total_size_bytes: int
    ok: bool
    warnings: tuple[str, ...]
    error: str | None = None


class FileIntegrityGuard:
    SMALL_FILE_BYTES = 256 * 1024

    def resolve_files(self, output: str | Path | None) -> list[Path]:
        if not output:
            return []
        path = Path(output)
        if "%" in path.name:
            pattern = path.name.replace("%03d", "*")
            return sorted(item for item in path.parent.glob(pattern) if item.is_file())
        return [path] if path.exists() and path.is_file() else []

    def inspect(self, output: str | Path | None) -> FileIntegrityResult:
        files = self.resolve_files(output)
        if not files:
            return FileIntegrityResult((), 0, False, (), "录制文件不存在")
        warnings: list[str] = []
        total = 0
        for path in files:
            try:
                size = path.stat().st_size
            except OSError as exc:
                return FileIntegrityResult(
                    tuple(str(item) for item in files),
                    total,
                    False,
                    tuple(warnings),
                    f"无法读取录制文件: {exc}",
                )
            total += size
            if size == 0:
                return FileIntegrityResult(
                    tuple(str(item) for item in files),
                    total,
                    False,
                    tuple(warnings),
                    f"录制文件为空: {path.name}",
                )
            if size < self.SMALL_FILE_BYTES:
                warnings.append(f"文件较小，建议人工检查: {path.name}")
        return FileIntegrityResult(
            tuple(str(item) for item in files), total, True, tuple(warnings)
        )

    def scan_temporary(self, root: Path) -> list[str]:
        if not root.exists():
            return []
        return sorted(
            str(path)
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".part", ".tmp"}
        )
