"""FFmpeg discovery, environment diagnostics, and command generation."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..utils.paths import project_root


@dataclass(slots=True)
class EnvironmentStatus:
    executable: str | None
    version: str | None
    source: str
    error: str | None = None


class FFmpegTool:
    def __init__(self, custom_path: str = "") -> None:
        self.custom_path = custom_path

    def resolved_executable(self) -> str:
        local = project_root() / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if local.exists():
            return str(local)
        system = shutil.which("ffmpeg")
        if system:
            return system
        if self.custom_path:
            candidate = Path(self.custom_path).expanduser()
            if candidate.exists():
                return str(candidate)
        raise FileNotFoundError(
            "找不到 FFmpeg：请放入 runtime/ffmpeg/bin、加入 PATH，或在设置中指定"
        )

    def status(self) -> EnvironmentStatus:
        try:
            executable = self.resolved_executable()
            first = subprocess.run(
                [executable, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
                encoding="utf-8",
                errors="replace",
            ).stdout.splitlines()[0]
            local = project_root() / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
            source = "项目内置" if Path(executable).resolve() == local.resolve() else (
                "系统 PATH" if shutil.which("ffmpeg") and Path(executable).resolve() == Path(shutil.which("ffmpeg")).resolve()
                else "用户指定"
            )
            return EnvironmentStatus(executable, first, source)
        except Exception as exc:
            return EnvironmentStatus(None, None, "未找到", str(exc))

    def check(self) -> str:
        status = self.status()
        if not status.version:
            raise FileNotFoundError(status.error or "找不到 FFmpeg")
        return status.version

    def recording_command(
        self,
        stream_url: str,
        output: Path,
        proxy: str | None = None,
        segmented: bool = False,
        segment_seconds: int = 1800,
    ) -> list[str]:
        command = [
            self.resolved_executable(),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-rw_timeout",
            "15000000",
        ]
        if proxy:
            command += ["-http_proxy", proxy]
        command += ["-i", stream_url, "-map", "0", "-c", "copy"]
        if segmented:
            command += [
                "-f",
                "segment",
                "-segment_time",
                str(max(60, segment_seconds)),
                "-reset_timestamps",
                "1",
            ]
        command.append(str(output))
        return command

    def convert_to_mp4(self, source: Path, delete_original: bool = False) -> Path:
        target = source.with_suffix(".mp4")
        subprocess.run(
            [
                self.resolved_executable(),
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-i",
                str(source),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(target),
            ],
            check=True,
            timeout=3600,
        )
        if delete_original and source.exists() and source != target:
            source.unlink()
        return target


def node_status() -> EnvironmentStatus:
    executable = shutil.which("node")
    if not executable:
        return EnvironmentStatus(None, None, "未找到", "部分 streamget 抖音解析路径可能需要 Node.js")
    try:
        version = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
        return EnvironmentStatus(executable, version, "系统 PATH")
    except Exception as exc:
        return EnvironmentStatus(executable, None, "系统 PATH", str(exc))
