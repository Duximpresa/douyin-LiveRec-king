"""Per-task configurable retry scheduling with a global concurrency limit."""

from __future__ import annotations

import threading
from collections.abc import Callable


class RetryCoordinator:
    DEFAULT_DELAYS = (5, 15, 45)
    DELAYS = DEFAULT_DELAYS  # Compatibility alias.

    def __init__(
        self,
        callback: Callable[[str], None],
        delays_provider: Callable[[], tuple[int, ...]] | None = None,
        max_attempts_provider: Callable[[], int] | None = None,
        concurrency_provider: Callable[[], int] | None = None,
    ) -> None:
        self.callback = callback
        self.delays_provider = delays_provider or (lambda: self.DEFAULT_DELAYS)
        self.max_attempts_provider = max_attempts_provider or (
            lambda: len(self.delays_provider())
        )
        self.concurrency_provider = concurrency_provider or (lambda: 2)
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._active_retries = 0
        self._active_condition = threading.Condition(self._lock)

    @property
    def max_attempts(self) -> int:
        return max(0, int(self.max_attempts_provider()))

    def delay_for(self, retry_count: int) -> int | None:
        if retry_count < 1 or retry_count > self.max_attempts:
            return None
        delays = self.delays_provider() or self.DEFAULT_DELAYS
        return delays[min(retry_count - 1, len(delays) - 1)]

    def schedule(self, task_id: str, retry_count: int) -> int | None:
        delay = self.delay_for(retry_count)
        if delay is None:
            return None
        with self._lock:
            if self._closed or task_id in self._timers:
                return None
            timer = threading.Timer(delay, self._fire, args=(task_id,))
            timer.daemon = True
            self._timers[task_id] = timer
            timer.start()
        return delay

    def _fire(self, task_id: str) -> None:
        with self._active_condition:
            self._timers.pop(task_id, None)
            while (
                not self._closed
                and self._active_retries
                >= max(1, int(self.concurrency_provider()))
            ):
                self._active_condition.wait(0.25)
            if self._closed:
                return
            self._active_retries += 1
        try:
            self.callback(task_id)
        finally:
            with self._active_condition:
                self._active_retries -= 1
                self._active_condition.notify_all()

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            timer = self._timers.pop(task_id, None)
        if timer:
            timer.cancel()
            return True
        return False

    def cancel_all(self) -> None:
        with self._active_condition:
            self._closed = True
            timers = list(self._timers.values())
            self._timers.clear()
            self._active_condition.notify_all()
        for timer in timers:
            timer.cancel()

    def trigger_now(self, task_id: str) -> None:
        self.cancel(task_id)
        self._fire(task_id)

    def pending(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._timers
