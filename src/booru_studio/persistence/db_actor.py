from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from booru_studio.persistence.schema import configure_connection, initialize_schema

T = TypeVar("T")


@dataclass(slots=True)
class _Task(Generic[T]):
    operation: Callable[[sqlite3.Connection], T]
    future: Future[T]


_STOP = object()


class DbActor:
    """Single-writer SQLite actor.

    The SQLite connection is constructed, used and closed exclusively on the actor
    thread. Other threads submit functions and receive Futures.
    """

    def __init__(self, path: Path, *, now_utc_ms: int, max_pending: int = 1024) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self._path = path
        self._now_utc_ms = now_utc_ms
        self._queue: queue.Queue[_Task[Any] | object] = queue.Queue(maxsize=max_pending)
        self._thread = threading.Thread(target=self._run, name="BooruStudio.DbActor", daemon=True)
        self._started = False
        self._closed = False
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("DbActor is closed")
        if self._started:
            return
        self._started = True
        self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            raise RuntimeError("DbActor failed to start") from self._startup_error

    def submit(self, operation: Callable[[sqlite3.Connection], T], *, timeout: float | None = None) -> Future[T]:
        if not self._started:
            raise RuntimeError("DbActor has not been started")
        if self._closed:
            raise RuntimeError("DbActor is closed")
        future: Future[T] = Future()
        self._queue.put(_Task(operation=operation, future=future), timeout=timeout)
        return future

    def close(self, *, timeout: float | None = 5.0) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._started:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise TimeoutError("DbActor did not stop within timeout")

    def _run(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
            connection.row_factory = sqlite3.Row
            configure_connection(connection)
            initialize_schema(connection, now_utc_ms=self._now_utc_ms)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            return

        self._ready.set()
        try:
            while True:
                task = self._queue.get()
                try:
                    if task is _STOP:
                        return
                    assert isinstance(task, _Task)
                    if task.future.set_running_or_notify_cancel():
                        try:
                            result = task.operation(connection)
                        except BaseException as exc:
                            task.future.set_exception(exc)
                        else:
                            task.future.set_result(result)
                finally:
                    self._queue.task_done()
        finally:
            connection.close()
