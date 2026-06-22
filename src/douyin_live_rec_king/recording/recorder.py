"""Thread-safe FFmpeg process lifecycle with optional post-conversion."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .ffmpeg import FFmpegTool

ExitCallback = Callable[[str, int, str | None], None]


class Recorder:
    def __init__(self, ffmpeg_path: str, logger: logging.Logger) -> None:
        self.ffmpeg = FFmpegTool(ffmpeg_path)
        self.logger = logger
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def is_recording(self, task_id: str) -> bool:
        with self._lock:
            process = self._processes.get(task_id)
            return process is not None and process.poll() is None

    def start(
        self,
        task_id: str,
        stream_url: str,
        output_path: Path,
        on_exit: ExitCallback | None = None,
        *,
        proxy: str | None = None,
        segmented: bool = False,
        segment_seconds: int = 1800,
        convert_mp4: bool = False,
        delete_original: bool = False,
    ) -> None:
        with self._lock:
            if self.is_recording(task_id):
                raise RuntimeError("该任务已经在录制")
            command = self.ffmpeg.recording_command(
                stream_url, output_path, proxy, segmented, segment_seconds
            )
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self._processes[task_id] = process
            self.logger.info("录制已启动: %s", output_path)
            threading.Thread(
                target=self._watch,
                args=(task_id, process, output_path, on_exit, convert_mp4, delete_original, segmented),
                name=f"ffmpeg-{task_id[:8]}",
                daemon=True,
            ).start()

    def _watch(
        self,
        task_id: str,
        process: subprocess.Popen[str],
        output_path: Path,
        on_exit: ExitCallback | None,
        convert_mp4: bool,
        delete_original: bool,
        segmented: bool,
    ) -> None:
        if process.stderr:
            for line in process.stderr:
                if message := line.strip():
                    self.logger.warning("FFmpeg[%s]: %s", task_id[:8], message)
        return_code = process.wait()
        final_path: str | None = str(output_path)
        if return_code == 0 and convert_mp4 and output_path.suffix.lower() == ".ts":
            try:
                if segmented:
                    pattern = output_path.name.replace("%03d", "*")
                    segments = sorted(output_path.parent.glob(pattern))
                    converted = [
                        self.ffmpeg.convert_to_mp4(segment, delete_original)
                        for segment in segments
                    ]
                    final_path = str(converted[-1]) if converted else str(output_path)
                    self.logger.info("已转封装 %d 个 MP4 分段", len(converted))
                else:
                    final_path = str(self.ffmpeg.convert_to_mp4(output_path, delete_original))
                    self.logger.info("已转封装 MP4: %s", final_path)
            except Exception:
                self.logger.exception("自动转 MP4 失败: %s", output_path)
                return_code = -2
        with self._lock:
            if self._processes.get(task_id) is process:
                self._processes.pop(task_id, None)
        self.logger.info("录制进程结束，返回码=%s，任务=%s", return_code, task_id)
        if on_exit:
            on_exit(task_id, return_code, final_path)

    def stop(self, task_id: str, timeout: float = 8.0) -> bool:
        with self._lock:
            process = self._processes.get(task_id)
        if process is None or process.poll() is not None:
            return False
        try:
            if process.stdin:
                process.stdin.write("q\n")
                process.stdin.flush()
            process.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        return True

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self._processes)
        for task_id in ids:
            self.stop(task_id)
