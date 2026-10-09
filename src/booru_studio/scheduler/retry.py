from __future__ import annotations

import email.utils
import errno
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from booru_studio.common.random_source import RandomSource, SystemRandomSource

_TRANSIENT_WINERRORS = {64, 121, 995, 10053, 10054, 10060, 10061}
_TRANSIENT_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNRESET,
    errno.ECONNREFUSED,
    errno.ETIMEDOUT,
    errno.EPIPE,
}
_RETRY_CLASS_NAMES = {
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "ReadTimeout",
    "ConnectTimeout",
    "Timeout",
    "TimeoutError",
    "ChunkedEncodingError",
    "ProtocolError",
    "IncompleteRead",
    "RemoteDisconnected",
    "BrokenPipeError",
}


def walk_exception_chain(exc: BaseException, *, limit: int = 32) -> tuple[BaseException, ...]:
    output: list[BaseException] = []
    queue: list[Any] = [exc]
    seen: set[int] = set()
    while queue and len(output) < limit:
        item = queue.pop(0)
        if isinstance(item, BaseException):
            ident = id(item)
            if ident in seen:
                continue
            seen.add(ident)
            output.append(item)
            queue.extend(getattr(item, "args", ()) or ())
            cause = getattr(item, "__cause__", None)
            context = getattr(item, "__context__", None)
            if cause is not None:
                queue.append(cause)
            if context is not None:
                queue.append(context)
        elif isinstance(item, (list, tuple)):
            queue.extend(item)
    return tuple(output)


def transient_network_reason(exc: BaseException) -> str | None:
    chain = walk_exception_chain(exc)
    for item in chain:
        winerror = getattr(item, "winerror", None)
        if winerror in _TRANSIENT_WINERRORS:
            return f"WinError {winerror}"
        err = getattr(item, "errno", None)
        if err in _TRANSIENT_WINERRORS:
            return f"WinError {err}"
        if err in _TRANSIENT_ERRNOS:
            return f"errno {err}"
    for item in chain:
        if type(item).__name__ in _RETRY_CLASS_NAMES:
            return type(item).__name__
    return None


def parse_retry_after_seconds(headers: Any, *, now_utc_ms: int, fallback_s: float = 1.0) -> float:
    raw = str(headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return max(0.0, min(86_400.0, float(raw)))
    if raw:
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            now = datetime.fromtimestamp(now_utc_ms / 1000, tz=UTC)
            return max(0.0, min(86_400.0, (parsed - now).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            pass
    return max(0.0, float(fallback_s))


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    hard_ceiling: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 8.0
    jitter_s: float = 0.25

    def __post_init__(self) -> None:
        if self.hard_ceiling < 0:
            raise ValueError("hard_ceiling cannot be negative")
        if self.base_delay_s < 0 or self.max_delay_s < 0 or self.jitter_s < 0:
            raise ValueError("retry delays cannot be negative")

    def can_retry(self, failures_so_far: int) -> bool:
        return failures_so_far <= self.hard_ceiling

    def delay_seconds(
        self,
        failures_so_far: int,
        random_source: RandomSource | None = None,
    ) -> float:
        if failures_so_far <= 0:
            return 0.0
        rng = random_source or SystemRandomSource()
        exponential = self.base_delay_s * (2 ** min(failures_so_far - 1, 8))
        jitter = rng.uniform(0.0, self.jitter_s) if self.jitter_s else 0.0
        return min(self.max_delay_s, exponential + jitter)
