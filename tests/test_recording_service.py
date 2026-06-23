import logging
from pathlib import Path

from douyin_live_rec_king.models import AppSettings, LiveStatus, LiveTask, RecordingExitReason
from douyin_live_rec_king.recording.events import RecordingEventType
from douyin_live_rec_king.recording.recorder import RecorderExitResult, StopAllResult
from douyin_live_rec_king.services.recording_service import RecordingService
from douyin_live_rec_king.services.storage_guard import StorageCheckResult


class FakeRecorder:
    def __init__(self):
        self.started = []
        self.ffmpeg = type("FFmpeg", (), {"custom_path": ""})()

    def is_recording(self, _task_id):
        return False

    def is_active(self, _task_id):
        return False

    def start(self, *args, **kwargs):
        self.started.append((args, kwargs))

    def stop(self, _task_id):
        return True

    def stop_all(self, _timeout=20.0):
        return StopAllResult(0, 0, 0, (), ())

    def active_ids(self):
        return ()

    def force_stop_all(self):
        return 0


class FakeGuard:
    def __init__(self, result):
        self.result = result

    def check(self, _path, _threshold):
        return self.result


def test_recording_service_starts_with_cookie(tmp_path: Path) -> None:
    events = []
    recorder = FakeRecorder()
    settings = AppSettings(output_directory=str(tmp_path), douyin_cookie="token=test")
    guard = FakeGuard(StorageCheckResult(True, tmp_path, 10.0, 1.0))
    service = RecordingService(
        lambda: settings,
        logging.getLogger("service"),
        events.append,
        recorder=recorder,
        storage_guard=guard,
    )
    task = LiveTask(url="mock://live")
    output = service.start(task, LiveStatus(True, stream_url="https://example.test/live"))
    assert output
    assert events[0].type is RecordingEventType.STARTING
    assert recorder.started[0][1]["cookie"] == "token=test"


def test_recording_service_reports_storage_failure(tmp_path: Path) -> None:
    events = []
    recorder = FakeRecorder()
    result = StorageCheckResult(False, tmp_path, 0.5, 1.0, "disk low")
    service = RecordingService(
        lambda: AppSettings(output_directory=str(tmp_path)),
        logging.getLogger("service"),
        events.append,
        recorder=recorder,
        storage_guard=FakeGuard(result),
    )
    assert service.start(LiveTask(url="mock://live"), LiveStatus(True, stream_url="stream")) is None
    assert events[-1].type is RecordingEventType.ERROR
    assert events[-1].error == "disk low"
    assert not recorder.started


def test_manual_stop_treats_forced_exit_as_expected(tmp_path: Path) -> None:
    events = []
    recorder = FakeRecorder()
    service = RecordingService(
        lambda: AppSettings(output_directory=str(tmp_path)),
        logging.getLogger("service"),
        events.append,
        recorder=recorder,
        storage_guard=FakeGuard(StorageCheckResult(True, tmp_path, 10.0, 1.0)),
    )
    assert service.stop("task")
    service._on_exit(
        "task",
        RecorderExitResult(
            return_code=-9,
            final_path="out.ts",
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:00:01+00:00",
            duration_seconds=1,
            diagnostic="killed",
            source_files=(),
            converted_files=(),
        ),
    )
    assert events[-1].type is RecordingEventType.EXITED
    assert events[-1].task_id == "task"
    assert events[-1].output_file == "out.ts"
    assert events[-1].expected_stop
    assert events[-1].error is None


def test_recording_exit_classification() -> None:
    base = dict(
        return_code=1,
        final_path=None,
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
        duration_seconds=1,
        source_files=(),
        converted_files=(),
    )
    network = RecorderExitResult(**base, diagnostic="Connection reset by peer")
    auth = RecorderExitResult(**base, diagnostic="HTTP error 403 Forbidden")
    parser = RecorderExitResult(**base, diagnostic="Invalid data found")
    unknown = RecorderExitResult(**base, diagnostic="Unknown encoder failure")
    converted = RecorderExitResult(
        **base, diagnostic="convert failed", conversion_failed=True
    )
    assert RecordingService.classify_exit(network, False) is RecordingExitReason.NETWORK_ERROR
    assert RecordingService.classify_exit(auth, False) is RecordingExitReason.AUTH_ERROR
    assert RecordingService.classify_exit(parser, False) is RecordingExitReason.PARSER_ERROR
    assert RecordingService.classify_exit(unknown, False) is RecordingExitReason.FFMPEG_ERROR
    assert RecordingService.classify_exit(converted, False) is RecordingExitReason.CONVERSION_ERROR
    assert RecordingService.classify_exit(unknown, True) is RecordingExitReason.MANUAL_STOP
