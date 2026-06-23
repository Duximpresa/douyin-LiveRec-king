from pathlib import Path

import pytest

from douyin_live_rec_king.history import RecordingHistoryEntry, RecordingHistoryStore
from douyin_live_rec_king.models import LiveStatus, LiveTask, PlatformType, RecordingExitReason
from douyin_live_rec_king.services.file_integrity import FileIntegrityGuard
from douyin_live_rec_king.services.recording_history import RecordingHistoryService


def test_history_lifecycle_and_delete_record_only(tmp_path: Path) -> None:
    store = RecordingHistoryStore(tmp_path / "history.json")
    service = RecordingHistoryService(store, FileIntegrityGuard())
    task = LiveTask(url="mock://live", anchor_name="Anchor")
    output = tmp_path / "record.ts"
    output.write_bytes(b"x" * 300_000)
    entry = service.create(
        task, LiveStatus(True, title="Title"), str(output), "ts"
    )
    service.mark_recording(entry.session_id)
    finished = service.finish(
        entry.session_id,
        output_file=str(output),
        duration_seconds=12,
        return_code=0,
        reason=RecordingExitReason.LIVE_ENDED,
        error=None,
    )
    assert finished and finished.status == "success"
    assert finished.total_size_bytes == 300_000
    assert service.delete_entry(entry.session_id)
    assert output.exists()


def test_history_retains_latest_1000(tmp_path: Path) -> None:
    store = RecordingHistoryStore(tmp_path / "history.json", max_entries=1000)
    entries = [
        RecordingHistoryEntry(
            task_id=str(index),
            platform=PlatformType.DOUYIN,
            anchor_name="A",
            room_url="mock://offline",
            started_at=f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
        )
        for index in range(1005)
    ]
    store.save(entries)
    assert len(store.load()) == 1000


def test_interrupted_history_is_recovered(tmp_path: Path) -> None:
    store = RecordingHistoryStore(tmp_path / "history.json")
    entry = RecordingHistoryEntry(
        task_id="task",
        platform=PlatformType.DOUYIN,
        anchor_name="A",
        room_url="mock://offline",
        status="recording",
        files=[str(tmp_path / "missing.ts")],
    )
    store.save([entry])
    service = RecordingHistoryService(store, FileIntegrityGuard())
    service.scan_interrupted(tmp_path)
    recovered = service.get(entry.session_id)
    assert recovered and recovered.status == "interrupted"
    assert recovered.exit_reason is RecordingExitReason.INTERRUPTED


def test_history_corruption_has_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="无法读取录制历史"):
        RecordingHistoryStore(path).load()


def test_delete_files_keeps_history(tmp_path: Path) -> None:
    store = RecordingHistoryStore(tmp_path / "history.json")
    service = RecordingHistoryService(store, FileIntegrityGuard())
    task = LiveTask(url="mock://live")
    output = tmp_path / "video.ts"
    output.write_bytes(b"x" * 300_000)
    entry = service.create(task, LiveStatus(True), str(output), "ts")
    service.finish(
        entry.session_id,
        output_file=str(output),
        duration_seconds=1,
        return_code=0,
        reason=RecordingExitReason.LIVE_ENDED,
        error=None,
    )
    deleted, errors = service.delete_files(entry.session_id)
    assert deleted == 1
    assert not errors
    assert service.get(entry.session_id) is not None
    assert not output.exists()
