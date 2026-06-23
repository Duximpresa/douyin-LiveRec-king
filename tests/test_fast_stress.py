import threading
from pathlib import Path

import pytest

from douyin_live_rec_king.history import RecordingHistoryEntry, RecordingHistoryStore
from douyin_live_rec_king.models import PlatformType


pytestmark = pytest.mark.stress


def test_parallel_history_writes_remain_valid(tmp_path: Path) -> None:
    store = RecordingHistoryStore(tmp_path / "history.json", max_entries=1000)
    lock = threading.Lock()
    entries: list[RecordingHistoryEntry] = []

    def worker(worker_id: int) -> None:
        for index in range(20):
            entry = RecordingHistoryEntry(
                task_id=f"{worker_id}-{index}",
                platform=PlatformType.DOUYIN,
                anchor_name="stress",
                room_url="mock://offline",
                status="success",
                ended_at=f"2026-06-23T12:{worker_id:02d}:{index:02d}+08:00",
            )
            with lock:
                entries.append(entry)
                store.save(list(entries))

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    loaded = store.load()
    assert len(loaded) == 80
    assert len({entry.session_id for entry in loaded}) == 80
