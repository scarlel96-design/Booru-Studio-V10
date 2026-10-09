from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    """Clock abstraction separating durable UTC time from local monotonic time."""

    def utc_ms(self) -> int: ...

    def monotonic_ms(self) -> int: ...


@dataclass(slots=True)
class SystemClock:
    def utc_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


@dataclass(slots=True)
class ManualClock:
    """Deterministic test clock; monotonic time may never move backwards."""

    _utc_ms: int = 0
    _monotonic_ms: int = 0

    def utc_ms(self) -> int:
        return self._utc_ms

    def monotonic_ms(self) -> int:
        return self._monotonic_ms

    def advance(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("monotonic time cannot move backwards")
        self._utc_ms += milliseconds
        self._monotonic_ms += milliseconds

    def set_utc_ms(self, value: int) -> None:
        """Wall clock is deliberately allowed to jump for clock-anomaly tests."""
        self._utc_ms = value
