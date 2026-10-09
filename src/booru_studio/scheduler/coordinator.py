from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Generic, Iterator, TypeVar

from booru_studio.common.clock import Clock, SystemClock
from booru_studio.scheduler.adaptive_network import HostAdaptiveLimiter
from booru_studio.scheduler.resources import TransferPermitPool

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class NetworkActivitySnapshot:
    active: int
    peak: int
    configured_capacity: int
    host: str | None


class NetworkAdmissionController:
    """Global → host request admission and exact in-flight instrumentation."""

    def __init__(
        self,
        capacity: int,
        *,
        host_limiter: HostAdaptiveLimiter | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.permits = TransferPermitPool(capacity)
        self.host_limiter = host_limiter or HostAdaptiveLimiter(capacity, clock=self.clock)
        self._lock = threading.Lock()
        self._active = 0
        self._peak = 0
        self._last_host: str | None = None

    @contextmanager
    def request(self, url: str, cancel_event: threading.Event) -> Iterator[None]:
        global_permit = self.permits.acquire(cancel_event)
        try:
            host_lease = self.host_limiter.acquire(url, cancel_event)
        except BaseException:
            global_permit.release()
            raise
        with self._lock:
            self._active += 1
            self._peak = max(self._peak, self._active)
            self._last_host = host_lease.host
        try:
            yield
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)
            host_lease.release()
            global_permit.release()

    def report_transient_failure(self, url: str) -> tuple[int, int, int]:
        return self.host_limiter.transient_failure(url)

    def report_success(self, url: str) -> tuple[int, int]:
        return self.host_limiter.success(url)

    def snapshot(self) -> NetworkActivitySnapshot:
        with self._lock:
            return NetworkActivitySnapshot(
                active=self._active,
                peak=self._peak,
                configured_capacity=self.permits.capacity,
                host=self._last_host,
            )


@dataclass(slots=True)
class _QueuedTask(Generic[T, R]):
    task: T
    future: Future[R]


class ParallelTransferScheduler(Generic[T, R]):
    """Bounded rolling producer/consumer scheduler.

    Every worker owns the executor-local resources created by ``worker_factory``.
    The queue is bounded; callers block briefly on submission instead of creating an
    unbounded number of futures for huge galleries.
    """

    def __init__(
        self,
        parallelism: int,
        *,
        worker_factory: Callable[[], Callable[[T, threading.Event, NetworkAdmissionController], R]],
        admission: NetworkAdmissionController | None = None,
        queue_multiplier: int = 4,
        operation_gate: threading.Event | None = None,
    ) -> None:
        if parallelism <= 0:
            raise ValueError("parallelism must be positive")
        self.parallelism = int(parallelism)
        self.cancel_event = threading.Event()
        self.admission = admission or NetworkAdmissionController(self.parallelism)
        self._queue: queue.Queue[_QueuedTask[T, R] | None] = queue.Queue(
            maxsize=max(self.parallelism + 2, self.parallelism * max(1, queue_multiplier))
        )
        self._worker_factory = worker_factory
        self._operation_gate = operation_gate
        self._threads = [
            threading.Thread(target=self._worker_loop, name=f"V10Transfer-{i:02d}", daemon=False)
            for i in range(1, self.parallelism + 1)
        ]
        self._closed = False
        self._lock = threading.Lock()
        self._futures: set[Future[R]] = set()
        self._fatal_error: BaseException | None = None
        for thread in self._threads:
            thread.start()

    def submit(self, task: T, *, timeout_s: float = 5.0) -> Future[R]:
        with self._lock:
            if self._closed:
                raise RuntimeError("scheduler is closed")
            if self._fatal_error is not None:
                raise RuntimeError("transfer scheduler worker failed") from self._fatal_error
            future: Future[R] = Future()
            self._futures.add(future)
        queued = _QueuedTask(task=task, future=future)
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            if self.cancel_event.is_set():
                future.cancel()
                return future
            try:
                self._queue.put(queued, timeout=0.05)
                return future
            except queue.Full:
                if time.monotonic() >= deadline:
                    future.cancel()
                    with self._lock:
                        self._futures.discard(future)
                    raise TimeoutError("bounded transfer queue remained full")

    def _worker_loop(self) -> None:
        worker = None
        try:
            worker = self._worker_factory()
            while True:
                queued = self._queue.get()
                try:
                    if queued is None:
                        return
                    while self._operation_gate is not None and not self._operation_gate.wait(0.05):
                        if self.cancel_event.is_set():
                            queued.future.cancel()
                            break
                    if self.cancel_event.is_set() and not queued.future.running():
                        queued.future.cancel()
                    elif queued.future.set_running_or_notify_cancel():
                        try:
                            result = worker(queued.task, self.cancel_event, self.admission)
                        except BaseException as exc:
                            queued.future.set_exception(exc)
                        else:
                            queued.future.set_result(result)
                    with self._lock:
                        self._futures.discard(queued.future)
                finally:
                    self._queue.task_done()
        except BaseException as exc:
            with self._lock:
                if self._fatal_error is None:
                    self._fatal_error = exc
            self.cancel_event.set()
            # Fail queued work so callers cannot wait forever on a dead consumer.
            while True:
                try:
                    pending = self._queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if pending is not None and not pending.future.done():
                        pending.future.set_exception(RuntimeError("transfer worker terminated unexpectedly"))
                        with self._lock:
                            self._futures.discard(pending.future)
                finally:
                    self._queue.task_done()
        finally:
            if worker is not None:
                close = getattr(worker, "close", None)
                if callable(close):
                    close()

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            futures = tuple(self._futures)
        for future in futures:
            if not future.running():
                future.cancel()

    def close(self, *, wait: bool = True, timeout_s: float = 30.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        deadline = time.monotonic() + max(0.0, timeout_s)
        for _ in self._threads:
            while True:
                if time.monotonic() >= deadline:
                    break
                try:
                    self._queue.put(None, timeout=0.05)
                    break
                except queue.Full:
                    if not any(thread.is_alive() for thread in self._threads):
                        break
        if wait:
            for thread in self._threads:
                remaining = max(0.0, deadline - time.monotonic())
                thread.join(remaining)
            alive = [thread.name for thread in self._threads if thread.is_alive()]
            if alive:
                raise TimeoutError(f"transfer scheduler workers did not stop: {alive}")

    def __enter__(self) -> "ParallelTransferScheduler[T, R]":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.cancel()
        self.close()
