"""FFprobe metadata inspection and safe TS-to-MP4 remuxing."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..recording.ffmpeg import FFmpegTool
from ..utils.paths import project_root


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    available: bool
    valid: bool
    duration_seconds: float | None
    format_name: str | None
    streams: tuple[dict[str, object], ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "valid": self.valid,
            "duration_seconds": self.duration_seconds,
            "format_name": self.format_name,
            "streams": list(self.streams),
            "error": self.error,
        }


class MediaProbeService:
    def __init__(self, ffmpeg_path: str = "") -> None:
        self.ffmpeg = FFmpegTool(ffmpeg_path)

    def resolved_ffprobe(self) -> str | None:
        local = project_root() / "runtime" / "ffmpeg" / "bin" / "ffprobe.exe"
        if local.exists():
            return str(local)
        system = shutil.which("ffprobe")
        if system:
            return system
        if self.ffmpeg.custom_path:
            candidate = Path(self.ffmpeg.custom_path).expanduser()
            sibling = candidate.with_name(
                "ffprobe.exe" if candidate.suffix.lower() == ".exe" else "ffprobe"
            )
            if sibling.exists():
                return str(sibling)
        return None

    def probe(self, path: str | Path) -> MediaProbeResult:
        source = Path(path)
        executable = self.resolved_ffprobe()
        if not executable:
            return MediaProbeResult(
                False, source.exists() and source.stat().st_size > 0, None, None, (),
                "未找到 ffprobe，已退回文件大小检查",
            )
        if not source.exists() or source.stat().st_size <= 0:
            return MediaProbeResult(True, False, None, None, (), "文件不存在或为空")
        try:
            result = subprocess.run(
                [
                    executable,
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(source),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=True,
            )
            payload = json.loads(result.stdout or "{}")
            format_data = payload.get("format") or {}
            streams = tuple(payload.get("streams") or ())
            duration = format_data.get("duration")
            return MediaProbeResult(
                True,
                bool(streams),
                float(duration) if duration not in (None, "N/A") else None,
                format_data.get("format_name"),
                streams,
                None if streams else "ffprobe 未发现音视频流",
            )
        except Exception as exc:
            return MediaProbeResult(True, False, None, None, (), str(exc))

    def remux(self, source: str | Path, delete_original: bool = False) -> Path:
        return self.ffmpeg.convert_to_mp4(Path(source), delete_original)
