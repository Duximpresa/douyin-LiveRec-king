import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from douyin_live_rec_king.config import SettingsStore, TaskStore
from douyin_live_rec_king.history import RecordingHistoryEntry
from douyin_live_rec_king.models import AppSettings, PlatformType
from douyin_live_rec_king.services.retry import RetryCoordinator
from douyin_live_rec_king.services.statistics import RecordingStatisticsService


def test_final_settings_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.ini")
    expected = AppSettings(
        bilibili_cookie="SESSDATA=x%2Fy",
        retry_max_attempts=5,
        retry_delays_seconds="1,2,8",
        max_concurrent_retries=4,
    )
    store.save(expected)
    actual = store.load()
    assert actual.bilibili_cookie == expected.bilibili_cookie
    assert actual.retry_max_attempts == 5
    assert actual.retry_delays == (1, 2, 8)
    assert actual.max_concurrent_retries == 4


def test_retry_dynamic_settings_and_concurrency_limit() -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()
    release = threading.Event()

    def callback(_task_id: str) -> None:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        release.wait(1)
        with lock:
            active -= 1

    coordinator = RetryCoordinator(
        callback,
        delays_provider=lambda: (1, 3),
        max_attempts_provider=lambda: 4,
        concurrency_provider=lambda: 2,
    )
    assert coordinator.delay_for(4) == 3
    threads = [
        threading.Thread(target=coordinator.trigger_now, args=(str(index),))
        for index in range(5)
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.1)
    assert maximum == 2
    release.set()
    for thread in threads:
        thread.join(2)
    coordinator.cancel_all()


def test_task_store_recovers_valid_tmp_and_backs_up_corrupt_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{broken", encoding="utf-8")
    path.with_suffix(".json.tmp").write_text(
        json.dumps({"version": 2, "tasks": [{"url": "mock://offline"}]}),
        encoding="utf-8",
    )
    tasks = TaskStore(path).load()
    assert len(tasks) == 1
    assert list(tmp_path.glob("tasks.json.corrupt-*.bak"))
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2


def test_task_store_corruption_reports_backup_path(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"corrupt-.*\.bak"):
        TaskStore(path).load()


def test_statistics_windows_groups_and_utf8_bom(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    entries = [
        RecordingHistoryEntry(
            task_id="1",
            platform=PlatformType.DOUYIN,
            anchor_name="主播甲",
            room_url="mock://offline",
            ended_at=(now - timedelta(days=2)).isoformat(),
            status="success",
            duration_seconds=10,
            total_size_bytes=100,
        ),
        RecordingHistoryEntry(
            task_id="2",
            platform=PlatformType.BILIBILI,
            anchor_name="主播乙",
            room_url="mock://offline",
            ended_at=(now - timedelta(days=10)).isoformat(),
            status="failed",
            duration_seconds=20,
            total_size_bytes=200,
        ),
    ]
    service = RecordingStatisticsService(lambda: entries)
    summary = service.summary()
    assert summary["all"]["count"] == 2
    assert summary["last_7_days"]["count"] == 1
    assert summary["last_30_days"]["count"] == 2
    assert {row["key"] for row in service.by_platform()} == {
        "douyin",
        "bilibili",
    }
    for kind in ("history", "summary", "daily"):
        target = service.export_csv(kind, tmp_path / f"{kind}.csv")
        assert target.read_bytes().startswith(b"\xef\xbb\xbf")
