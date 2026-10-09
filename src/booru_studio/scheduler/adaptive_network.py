from __future__ import annotations

import threading
import time
import urllib.parse
from dataclasses import dataclass

from booru_studio.common.clock import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class HostLimiterSnapshot:
    host: str
    active: int
    limit: int
    fail_streak: int
    success_streak: int
    recover_after_monotonic_ms: int


@dataclass(slots=True)
class _HostState:
    active: int
    limit: int
    fail_streak: int = 0
    success_streak: int = 0
    recover_after_monotonic_ms: int = 0


class HostLease:
    __slots__ = ("_limiter", "host", "_released")

    def __init__(self, limiter: "HostAdaptiveLimiter", host: str) -> None:
        self._limiter = limiter
        self.host = host
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._limiter.release(self.host)

    def __enter__(self) -> "HostLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class HostAdaptiveLimiter:
    """Per-host concurrency feedback controller inherited from V9.1.5 semantics."""

    def __init__(
        self,
        ceiling: int,
        *,
        initial_limit: int | None = None,
        minimum: int = 2,
        clock: Clock | None = None,
    ) -> None:
        if ceiling <= 0:
            raise ValueError("ceiling must be positive")
        self.ceiling = int(ceiling)
        self.default_limit = max(1, min(self.ceiling, int(initial_limit or self.ceiling)))
        self.minimum = max(1, min(self.default_limit, int(minimum)))
        self._clock = clock or SystemClock()
        self._condition = threading.Condition()
        self._states: dict[str, _HostState] = {}

    @staticmethod
    def host_key(url_or_host: str) -> str:
        raw = str(url_or_host or "")
        if "://" not in raw:
            return raw.lower() or "<unknown>"
        try:
            return (urllib.parse.urlsplit(raw).hostname or "").lower() or "<unknown>"
        except ValueError:
            return "<unknown>"

    def _state(self, host: str) -> _HostState:
        return self._states.setdefault(host, _HostState(active=0, limit=self.default_limit))

    def snapshot(self, url_or_host: str) -> HostLimiterSnapshot:
        host = self.host_key(url_or_host)
        with self._condition:
            state = self._state(host)
            return HostLimiterSnapshot(
                host=host,
                active=state.active,
                limit=state.limit,
                fail_streak=state.fail_streak,
                success_streak=state.success_streak,
                recover_after_monotonic_ms=state.recover_after_monotonic_ms,
            )

    def acquire(
        self,
        url_or_host: str,
        cancel_event: threading.Event | None = None,
        *,
        poll_interval_s: float = 0.05,
    ) -> HostLease:
        host = self.host_key(url_or_host)
        with self._condition:
            state = self._state(host)
            while state.active >= state.limit:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("host permit acquisition cancelled")
                self._condition.wait(poll_interval_s)
                state = self._state(host)
            state.active += 1
            return HostLease(self, host)

    def release(self, url_or_host: str) -> None:
        host = self.host_key(url_or_host)
        with self._condition:
            state = self._state(host)
            state.active = max(0, state.active - 1)
            self._condition.notify_all()

    def transient_failure(self, url_or_host: str) -> tuple[int, int, int]:
        host = self.host_key(url_or_host)
        with self._condition:
            state = self._state(host)
            old = state.limit
            state.fail_streak += 1
            state.success_streak = 0
            if state.fail_streak >= 2:
                reduced = max(self.minimum, int(max(1, old) * 0.70))
                if reduced >= old and old > self.minimum:
                    reduced = old - 1
                state.limit = max(self.minimum, reduced)
            state.recover_after_monotonic_ms = self._clock.monotonic_ms() + min(
                90_000, 15_000 + state.fail_streak * 5_000
            )
            self._condition.notify_all()
            return old, state.limit, state.fail_streak

    def success(self, url_or_host: str) -> tuple[int, int]:
        host = self.host_key(url_or_host)
        with self._condition:
            state = self._state(host)
            old = state.limit
            state.success_streak += 1
            if state.success_streak % 6 == 0:
                state.fail_streak = max(0, state.fail_streak - 1)
            if (
                old < self.ceiling
                and state.success_streak >= 12
                and self._clock.monotonic_ms() >= state.recover_after_monotonic_ms
            ):
                state.limit = min(self.ceiling, old + 1)
                state.success_streak = 0
                self._condition.notify_all()
            return old, state.limit
