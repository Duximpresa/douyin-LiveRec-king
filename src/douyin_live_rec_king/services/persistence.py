"""Debounced task persistence using immutable snapshots."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

from ..config import TaskStore
from ..models import LiveTask


class TaskPersistenceCoordinator:
    def __init__(
        self,
        task_store: TaskStore,
        logger: logging.Logger,
        debounce_seconds: float = 0.25,
    ) -> None:
        self.task_store = task_store
        self.logger = logger
        self.debounce_seconds = max(0.0, debounce_seconds)
        self._condition = threading.Condition()
        self._pending: list[dict[str, Any]] | None = None
        self._deadline: float | None = None
        self._writing = False
        self._closed = False
        self._last_error: Exception | None = None
        self._thread = threading.Thread(
            target=self._run, name="task-persistence", daemon=True
        )
        self._thread.start()

    @staticmethod
    def snapshot(tasks: Iterable[LiveTask]) -> list[dict[str, Any]]:
        return [dict(task.to_dict()) for task in tasks]

    def request_save(self, tasks: Iterable[LiveTask]) -> bool:
        snapshot = self.snapshot(tasks)
        with self._condition:
            if self._closed:
                return False
            self._pending = snapshot
            self._deadline = time.monotonic() + self.debounce_seconds
            self._condition.notify_all()
        return True

    def save_now(self, tasks: Iterable[LiveTask]) -> None:
        snapshot = self.snapshot(tasks)
        with self._condition:
            if self._closed:
                raise RuntimeError("任务持久化协调器已关闭")
            while self._writing:
                self._condition.wait()
            self._pending = None
            self._deadline = None
            self._writing = True
        try:
            self.task_store.save_snapshot(snapshot)
            self._last_error = None
        except Exception as exc:
            self._last_error = exc
            raise
        finally:
            with self._condition:
                self._writing = False
                self._condition.notify_all()

    def flush(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            if self._pending is not None:
                self._deadline = time.monotonic()
                self._condition.notify_all()
            while self._pending is not None or self._writing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return self._last_error is None

    def close(self, timeout: float = 5.0) -> bool:
        flushed = self.flush(timeout)
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=max(0.0, timeout))
        return flushed and not self._thread.is_alive()

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed and self._pending is None:
                    return
                deadline = self._deadline or time.monotonic()
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                snapshot = self._pending
                self._pending = None
                self._deadline = None
                self._writing = True
            try:
                if snapshot is not None:
                    self.task_store.save_snapshot(snapshot)
                self._last_error = None
            except Exception as exc:
                self._last_error = exc
                self.logger.exception("后台保存任务失败")
            finally:
                with self._condition:
                    self._writing = False
                    self._condition.notify_all()
