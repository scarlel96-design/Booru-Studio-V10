from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.projection_repository import read_projection_snapshot

T = TypeVar("T")


class ProjectionService:
    """Core-owned read model service for the UI boundary."""

    def __init__(self, db_actor: DbActor, *, db_timeout_s: float = 5.0) -> None:
        if db_timeout_s <= 0:
            raise ValueError("db_timeout_s must be positive")
        self._db_actor = db_actor
        self._db_timeout_s = db_timeout_s

    def _wait(self, future: Future[T]) -> T:
        try:
            return future.result(timeout=self._db_timeout_s)
        except FutureTimeoutError as exc:
            raise TimeoutError("projection database operation timed out") from exc

    def snapshot(self) -> dict[str, Any]:
        return self._wait(self._db_actor.submit(read_projection_snapshot))
