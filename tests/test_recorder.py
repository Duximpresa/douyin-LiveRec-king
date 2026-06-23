import logging
import subprocess
import time
from pathlib import Path

import pytest

import douyin_live_rec_king.recording.recorder as recorder_module
from douyin_live_rec_king.recording.recorder import Recorder


class FakeProcess:
    def __init__(self, wait_results=None):
        self.stdin = self
        self.stderr = []
        self._returncode = None
        self.wait_results = list(wait_results or [0])
        self.writes = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._returncode

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        pass

    def wait(self, timeout=None):
        result = self.wait_results.pop(0) if self.wait_results else 0
        if isinstance(result, BaseException):
            raise result
        self._returncode = result
        return result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class NoopThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def test_recorder_reserves_task_before_second_start(tmp_path: Path, monkeypatch) -> None:
    process = FakeProcess()
    monkeypatch.setattr(recorder_module.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(recorder_module.threading, "Thread", NoopThread)
    recorder = Recorder("", logging.getLogger("recorder"))
    monkeypatch.setattr(recorder.ffmpeg, "resolved_executable", lambda: "ffmpeg")
    recorder.start("task", "stream", tmp_path / "out.ts")
    with pytest.raises(RuntimeError):
        recorder.start("task", "stream", tmp_path / "out2.ts")


def test_recorder_stop_escalates_to_kill() -> None:
    expired = subprocess.TimeoutExpired("ffmpeg", 1)
    process = FakeProcess([expired, expired, 0])
    recorder = Recorder("", logging.getLogger("recorder"))
    recorder._processes["task"] = process
    assert recorder.stop("task", timeout=0.01)
    assert process.writes == ["q\n"]
    assert process.terminated
    assert process.killed


def test_stop_all_stops_tasks_in_parallel(monkeypatch) -> None:
    recorder = Recorder("", logging.getLogger("recorder"))
    recorder._processes = {"one": FakeProcess(), "two": FakeProcess()}
    entered = set()
    release = __import__("threading").Event()

    def stop(task_id, timeout=8.0):
        entered.add(task_id)
        if len(entered) == 2:
            release.set()
        release.wait(1)
        recorder._processes.pop(task_id, None)
        return True

    monkeypatch.setattr(recorder, "stop", stop)
    result = recorder.stop_all(timeout=2)
    assert entered == {"one", "two"}
    assert result.requested == 2
    assert result.stopped == 2


def test_stop_all_forces_process_after_total_timeout(monkeypatch) -> None:
    recorder = Recorder("", logging.getLogger("recorder"))
    process = FakeProcess()
    recorder._processes = {"slow": process}

    def slow_stop(_task_id, timeout=8.0):
        time.sleep(0.1)
        return True

    monkeypatch.setattr(recorder, "stop", slow_stop)
    result = recorder.stop_all(timeout=0.01)
    assert result.timed_out == ("slow",)
    assert result.forced == 1
    assert process.killed
