from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass

from booru_studio.common.clock import Clock
from booru_studio.common.ids import RetryEpisodeId
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.network_repository import (
    get_open_retry_episode,
    increment_retry_episode,
    insert_retry_episode,
    set_retry_episode_state,
)
from booru_studio.persistence.transactions.base import write_transaction


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry_episode_id: RetryEpisodeId
    failure_count: int
    hard_ceiling: int
    retry_allowed: bool
    next_retry_at_utc_ms: int | None


class DurableRetryBudget:
    """Core-side retry ceiling that survives Core restarts."""

    def __init__(self, db_actor: DbActor, clock: Clock, *, db_timeout_s: float = 5.0) -> None:
        self._db = db_actor
        self._clock = clock
        self._timeout = db_timeout_s

    def record_failure(
        self,
        *,
        scope_kind: str,
        scope_id: str,
        error_code: str,
        hard_ceiling: int,
        retry_delay_ms: int = 0,
    ) -> RetryDecision:
        if hard_ceiling < 0 or retry_delay_ms < 0:
            raise ValueError("retry limits cannot be negative")
        now = self._clock.utc_ms()
        next_retry = now + retry_delay_ms

        def op(connection):
            with write_transaction(connection):
                row = get_open_retry_episode(
                    connection, scope_kind=scope_kind, scope_id=scope_id, error_code=error_code
                )
                if row is None:
                    episode_id = RetryEpisodeId.new()
                    insert_retry_episode(
                        connection,
                        retry_episode_id=episode_id,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        error_code=error_code,
                        hard_ceiling=hard_ceiling,
                        next_retry_at_utc_ms=next_retry,
                        now_utc_ms=now,
                    )
                    count = 1
                    ceiling = hard_ceiling
                else:
                    episode_id = RetryEpisodeId.parse(str(row["retry_episode_id"]))
                    ceiling = min(int(row["hard_ceiling"]), hard_ceiling)
                    count, _stored_ceiling = increment_retry_episode(
                        connection,
                        retry_episode_id=episode_id,
                        next_retry_at_utc_ms=next_retry,
                        now_utc_ms=now,
                    )
                allowed = count <= ceiling
                if not allowed:
                    set_retry_episode_state(
                        connection, retry_episode_id=episode_id, state="EXHAUSTED", now_utc_ms=now
                    )
                return RetryDecision(episode_id, count, ceiling, allowed, next_retry if allowed else None)

        try:
            return self._db.submit(op).result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("retry persistence timed out") from exc

    def mark_recovered(self, retry_episode_id: RetryEpisodeId) -> None:
        now = self._clock.utc_ms()
        try:
            self._db.submit(
                lambda c: self._mark(c, retry_episode_id, now)
            ).result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("retry persistence timed out") from exc

    @staticmethod
    def _mark(connection, retry_episode_id: RetryEpisodeId, now: int) -> None:
        with write_transaction(connection):
            set_retry_episode_state(
                connection, retry_episode_id=retry_episode_id, state="RECOVERED", now_utc_ms=now
            )
