"""Thread-safe FFmpeg process lifecycle with optional post-conversion."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .ffmpeg import FFmpegTool

@dataclass(frozen=True, slots=True)
class RecorderExitResult:
    return_code: int
    final_path: str | None
    started_at: str
    ended_at: str
    duration_seconds: float
    diagnostic: str | None
    source_files: tuple[str, ...]
    converted_files: tuple[str, ...]
    conversion_failed: bool = False


ExitCallback = Callable[[str, RecorderExitResult], None]
StateCallback = Callable[[str, str, str | None], None]


@dataclass(frozen=True, slots=True)
class StopAllResult:
    requested: int
    stopped: int
    forced: int
    failed: tuple[str, ...]
    timed_out: tuple[str, ...]


class Recorder:
    def __init__(self, ffmpeg_path: str, logger: logging.Logger) -> None:
        self.ffmpeg = FFmpegTool(ffmpeg_path)
        self.logger = logger
        self._processes: dict[str, subprocess.Popen[str] | None] = {}
        self._cancel_requested: set[str] = set()
        self._lock = threading.RLock()

    def is_recording(self, task_id: str) -> bool:
        with self._lock:
            process = self._processes.get(task_id)
            return process is not None and process.poll() is None

    def is_active(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._processes

    def active_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._processes)

    def start(
        self,
        task_id: str,
        stream_url: str,
        output_path: Path,
        on_exit: ExitCallback | None = None,
        on_state: StateCallback | None = None,
        *,
        proxy: str | None = None,
        segmented: bool = False,
        segment_seconds: int = 1800,
        convert_mp4: bool = False,
        delete_original: bool = False,
        headers: dict[str, str] | None = None,
        user_agent: str | None = None,
        referer: str | None = None,
        cookie: str | None = None,
        reconnect: bool = True,
    ) -> None:
        with self._lock:
            if task_id in self._processes:
                raise RuntimeError("该任务已经在录制或启动中")
            self._processes[task_id] = None
        try:
            command = self.ffmpeg.recording_command(
                stream_url,
                output_path,
                proxy,
                segmented,
                segment_seconds,
                headers,
                user_agent,
                referer,
                cookie,
                reconnect,
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
            with self._lock:
                self._processes[task_id] = process
                cancel_requested = task_id in self._cancel_requested
            self.logger.info("录制已启动: %s", output_path)
            if on_state:
                on_state(task_id, "recording", None)
            watcher = threading.Thread(
                target=self._watch,
                args=(
                    task_id,
                    process,
                    output_path,
                    on_exit,
                    on_state,
                    convert_mp4,
                    delete_original,
                    segmented,
                ),
                name=f"ffmpeg-{task_id[:8]}",
                daemon=True,
            )
            watcher.start()
            if cancel_requested:
                self.stop(task_id)
        except Exception as exc:
            with self._lock:
                self._processes.pop(task_id, None)
                self._cancel_requested.discard(task_id)
            self.logger.exception("启动 FFmpeg 失败: %s", task_id)
            if on_state:
                on_state(task_id, "error", str(exc))
            raise

    def _watch(
        self,
        task_id: str,
        process: subprocess.Popen[str],
        output_path: Path,
        on_exit: ExitCallback | None,
        on_state: StateCallback | None,
        convert_mp4: bool,
        delete_original: bool,
        segmented: bool,
    ) -> None:
        return_code = -1
        final_path: str | None = str(output_path)
        started_at = datetime.now().astimezone()
        started_monotonic = time.monotonic()
        diagnostic: str | None = None
        converted_files: list[str] = []
        conversion_failed = False
        try:
            last_log_at = 0.0
            if process.stderr:
                for line in process.stderr:
                    message = line.strip()
                    lower = message.lower()
                    important = any(
                        token in lower
                        for token in (
                            "warning",
                            "error",
                            "failed",
                            "invalid",
                            "timed out",
                            "timeout",
                            "connection",
                            "server returned",
                            "end of file",
                            "eof",
                            "broken pipe",
                        )
                    )
                    now = time.monotonic()
                    if message and important:
                        diagnostic = message
                    if message and important and now - last_log_at >= 1.0:
                        self.logger.warning("FFmpeg[%s]: %s", task_id[:8], message)
                        last_log_at = now
            return_code = process.wait()
            if return_code == 0 and convert_mp4 and output_path.suffix.lower() == ".ts":
                try:
                    if segmented:
                        pattern = output_path.name.replace("%03d", "*")
                        segments = sorted(output_path.parent.glob(pattern))
                        converted = [
                            self.ffmpeg.convert_to_mp4(segment, delete_original)
                            for segment in segments
                        ]
                        converted_files = [str(item) for item in converted]
                        final_path = str(converted[-1]) if converted else str(output_path)
                        self.logger.info("已转封装 %d 个 MP4 分段", len(converted))
                    else:
                        converted = self.ffmpeg.convert_to_mp4(
                            output_path, delete_original
                        )
                        converted_files = [str(converted)]
                        final_path = str(converted)
                        self.logger.info("已转封装 MP4: %s", final_path)
                except Exception:
                    self.logger.exception("自动转 MP4 失败: %s", output_path)
                    return_code = -2
                    conversion_failed = True
                    diagnostic = f"自动转 MP4 失败: {output_path}"
        except Exception as exc:
            self.logger.exception("监控 FFmpeg 进程失败: %s", task_id)
            diagnostic = str(exc)
            if on_state:
                on_state(task_id, "error", str(exc))
        finally:
            with self._lock:
                if self._processes.get(task_id) is process:
                    self._processes.pop(task_id, None)
                self._cancel_requested.discard(task_id)
            self.logger.info("录制进程结束，返回码=%s，任务=%s", return_code, task_id)
            if on_exit:
                ended_at = datetime.now().astimezone()
                on_exit(
                    task_id,
                    RecorderExitResult(
                        return_code=return_code,
                        final_path=final_path,
                        started_at=started_at.isoformat(timespec="seconds"),
                        ended_at=ended_at.isoformat(timespec="seconds"),
                        duration_seconds=max(
                            0.0, time.monotonic() - started_monotonic
                        ),
                        diagnostic=diagnostic,
                        source_files=tuple(
                            str(path)
                            for path in self._resolve_output_files(
                                output_path, segmented
                            )
                        ),
                        converted_files=tuple(converted_files),
                        conversion_failed=conversion_failed,
                    ),
                )

    @staticmethod
    def _resolve_output_files(output_path: Path, segmented: bool) -> list[Path]:
        if segmented:
            pattern = output_path.name.replace("%03d", "*")
            return sorted(
                path for path in output_path.parent.glob(pattern) if path.is_file()
            )
        return [output_path] if output_path.exists() else []

    def stop(self, task_id: str, timeout: float = 8.0) -> bool:
        with self._lock:
            process = self._processes.get(task_id)
            if task_id in self._processes and process is None:
                self._cancel_requested.add(task_id)
                return True
        if process is None or process.poll() is not None:
            return False
        try:
            if process.stdin:
                process.stdin.write("q\n")
                process.stdin.flush()
            process.wait(timeout=timeout)
            return True
        except OSError:
            self.logger.exception("向 FFmpeg 发送退出命令失败: %s", task_id)
        except subprocess.TimeoutExpired:
            self.logger.warning("FFmpeg 优雅退出超时，准备 terminate: %s", task_id)
        try:
            process.terminate()
            process.wait(timeout=3)
            return True
        except OSError:
            self.logger.exception("terminate FFmpeg 失败: %s", task_id)
        except subprocess.TimeoutExpired:
            self.logger.warning("FFmpeg terminate 超时，准备 kill: %s", task_id)
        try:
            process.kill()
            process.wait(timeout=3)
        except Exception:
            self.logger.exception("kill FFmpeg 失败: %s", task_id)
        return True

    def stop_all(self, timeout: float = 20.0) -> StopAllResult:
        started_at = time.monotonic()
        with self._lock:
            ids = list(self._processes)
        if not ids:
            return StopAllResult(0, 0, 0, (), ())
        outcomes: dict[str, bool] = {}

        def stop_one(task_id: str) -> None:
            try:
                outcomes[task_id] = self.stop(task_id)
            except Exception:
                outcomes[task_id] = False
                self.logger.exception("停止录制进程失败: %s", task_id)

        executor = ThreadPoolExecutor(
            max_workers=max(1, len(ids)), thread_name_prefix="stop-ffmpeg"
        )
        futures = {executor.submit(stop_one, task_id): task_id for task_id in ids}
        done, pending = wait(futures, timeout=max(0.0, timeout))
        timed_out_ids = set(futures[future] for future in pending)
        forced = self.force_stop_all(tuple(timed_out_ids))
        executor.shutdown(wait=False, cancel_futures=True)
        remaining = max(0.0, timeout - (time.monotonic() - started_at))
        if not self.wait_for_inactive(remaining):
            leftovers = set(self.active_ids())
            newly_timed_out = leftovers - timed_out_ids
            timed_out_ids.update(leftovers)
            forced += self.force_stop_all(tuple(newly_timed_out))
        timed_out = tuple(sorted(timed_out_ids))
        failed = tuple(
            task_id
            for task_id in ids
            if task_id not in timed_out and not outcomes.get(task_id, False)
        )
        return StopAllResult(
            requested=len(ids),
            stopped=sum(1 for task_id in ids if outcomes.get(task_id, False)),
            forced=forced,
            failed=failed,
            timed_out=timed_out,
        )

    def wait_for_inactive(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while self.active_ids():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))
        return True

    def force_stop_all(self, task_ids: tuple[str, ...] | None = None) -> int:
        with self._lock:
            selected = list(task_ids) if task_ids is not None else list(self._processes)
            processes = {
                task_id: self._processes.get(task_id) for task_id in selected
            }
        forced = 0
        for task_id, process in processes.items():
            if process is None:
                with self._lock:
                    self._cancel_requested.add(task_id)
                continue
            if process.poll() is not None:
                continue
            try:
                process.kill()
                forced += 1
            except Exception:
                self.logger.exception("强制结束 FFmpeg 失败: %s", task_id)
        return forced
