from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeoutError

from booru_studio.common.clock import Clock
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.network_repository import (
    delete_rate_limit_gate,
    get_rate_limit_deadline,
    upsert_rate_limit_gate,
)
from booru_studio.persistence.transactions.base import write_transaction


class DurableRateLimitRegistry:
    """Core-side durable 429/Retry-After gate; Worker event wiring is a later boundary."""

    def __init__(self, db_actor: DbActor, clock: Clock, *, db_timeout_s: float = 5.0) -> None:
        self._db = db_actor
        self._clock = clock
        self._timeout = db_timeout_s

    def penalize(
        self,
        gate_key: str,
        *,
        retry_after_s: float,
        network_context_key: str = "default",
        source: str = "HTTP_RETRY_AFTER",
    ) -> int:
        if not gate_key:
            raise ValueError("gate_key cannot be empty")
        if retry_after_s < 0:
            raise ValueError("retry_after_s cannot be negative")
        now = self._clock.utc_ms()
        deadline = now + int(retry_after_s * 1000)

        def op(connection):
            with write_transaction(connection):
                upsert_rate_limit_gate(
                    connection,
                    gate_key=gate_key,
                    network_context_key=network_context_key,
                    deadline_utc_ms=deadline,
                    source=source,
                    now_utc_ms=now,
                )
                return get_rate_limit_deadline(connection, gate_key)

        try:
            stored = self._db.submit(op).result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("rate-limit persistence timed out") from exc
        if stored is None:
            raise RuntimeError("rate-limit gate was not persisted")
        return stored

    def remaining_ms(self, gate_key: str) -> int:
        try:
            deadline = self._db.submit(
                lambda c: get_rate_limit_deadline(c, gate_key)
            ).result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("rate-limit read timed out") from exc
        if deadline is None:
            return 0
        return max(0, deadline - self._clock.utc_ms())

    def clear_if_expired(self, gate_key: str) -> bool:
        if self.remaining_ms(gate_key) > 0:
            return False
        now = self._clock.utc_ms()
        try:
            self._db.submit(
                lambda c: self._delete(c, gate_key)
            ).result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("rate-limit delete timed out") from exc
        return True

    @staticmethod
    def _delete(connection, gate_key: str) -> None:
        with write_transaction(connection):
            delete_rate_limit_gate(connection, gate_key)
