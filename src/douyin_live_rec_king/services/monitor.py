"""Concurrent polling loop with shared per-task in-flight protection."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait

from ..models import LiveTask


class Monitor:
    def __init__(
        self,
        task_provider: Callable[[], list[LiveTask]],
        poll_task: Callable[[LiveTask], None],
        interval_provider: Callable[[], int],
        workers_provider: Callable[[], int],
        logger: logging.Logger,
    ) -> None:
        self.task_provider = task_provider
        self.poll_task = poll_task
        self.interval_provider = interval_provider
        self.workers_provider = workers_provider
        self.logger = logger
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._inflight: set[str] = set()
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="live-monitor", daemon=True
            )
            self._thread.start()
        self.logger.info("直播监控已启动")

    def _guarded_poll(self, task: LiveTask) -> bool:
        with self._lock:
            if task.id in self._inflight:
                return False
            self._inflight.add(task.id)
        try:
            self.poll_task(task)
            return True
        finally:
            with self._lock:
                self._inflight.discard(task.id)

    def poll_now(self, tasks: Iterable[LiveTask] | None = None) -> None:
        selected = list(tasks if tasks is not None else self.task_provider())
        selected = [task for task in selected if task.enabled]
        if not selected:
            return

        def run_batch() -> None:
            with ThreadPoolExecutor(
                max_workers=max(1, self.workers_provider()),
                thread_name_prefix="live-check",
            ) as executor:
                futures = [executor.submit(self._guarded_poll, task) for task in selected]
                wait(futures)

        threading.Thread(target=run_batch, name="manual-refresh", daemon=True).start()

    def _poll_batch(self) -> None:
        tasks = [task for task in self.task_provider() if task.enabled]
        if not tasks:
            return
        with ThreadPoolExecutor(
            max_workers=max(1, self.workers_provider()),
            thread_name_prefix="live-check",
        ) as executor:
            futures = [executor.submit(self._guarded_poll, task) for task in tasks]
            wait(futures)

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._poll_batch()
                if self._stop_event.is_set():
                    break
                self._wake_event.wait(max(2, self.interval_provider()))
                self._wake_event.clear()
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def wake(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        with self._lock:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=10)
        self.logger.info("直播监控已停止")
