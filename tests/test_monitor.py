import logging
import threading
import time

from douyin_live_rec_king.models import LiveTask
from douyin_live_rec_king.services.monitor import Monitor


def test_monitor_start_is_idempotent_and_stop_wakes() -> None:
    monitor = Monitor(lambda: [], lambda _task: None, lambda: 60, lambda: 1, logging.getLogger("monitor"))
    monitor.start()
    thread = monitor._thread
    monitor.start()
    assert monitor._thread is thread
    monitor.stop()
    assert not monitor.running


def test_manual_polls_share_inflight_guard() -> None:
    task = LiveTask(url="mock://offline")
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    lock = threading.Lock()

    def poll(_task: LiveTask) -> None:
        nonlocal calls
        with lock:
            calls += 1
        entered.set()
        release.wait(2)

    monitor = Monitor(lambda: [task], poll, lambda: 60, lambda: 2, logging.getLogger("monitor"))
    monitor.poll_now([task])
    assert entered.wait(1)
    monitor.poll_now([task])
    time.sleep(0.1)
    release.set()
    time.sleep(0.1)
    assert calls == 1
