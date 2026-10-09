from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class StoreState:
    global_state_revision: int
    projection_revision: int
    downloads: tuple[dict[str, Any], ...]
    queue: tuple[dict[str, Any], ...]
    history: tuple[dict[str, Any], ...]
    history_has_more: bool = False
    stale: bool = False


_EMPTY = StoreState(0, 0, (), (), (), False, True)


class ProjectionStore:
    """UI-owned copy of Core projection state.

    It never becomes authoritative.  Revision regression is rejected so a delayed response
    cannot overwrite a newer UI projection after reconnect/resubscribe.
    """

    def __init__(self) -> None:
        self._state = _EMPTY

    @property
    def state(self) -> StoreState:
        return self._state

    def mark_stale(self) -> None:
        self._state = StoreState(
            self._state.global_state_revision,
            self._state.projection_revision,
            self._state.downloads,
            self._state.queue,
            self._state.history,
            self._state.history_has_more,
            True,
        )

    @staticmethod
    def _rows(raw: object, name: str) -> tuple[dict[str, Any], ...]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise ValueError(f"{name} must be an array")
        rows: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError(f"{name} entries must be objects")
            row = {str(key): value for key, value in item.items()}
            job_id = str(row.get("job_id") or "")
            if not job_id:
                raise ValueError(f"{name} entry is missing job_id")
            if job_id in identifiers:
                raise ValueError(f"{name} contains duplicate job_id")
            identifiers.add(job_id)
            rows.append(row)
        return tuple(rows)

    def apply_snapshot(self, snapshot: Mapping[str, object]) -> bool:
        global_revision = int(snapshot["global_state_revision"])
        projection_revision = int(snapshot["projection_revision"])
        if global_revision < 0 or projection_revision < 0:
            raise ValueError("projection revisions must be non-negative")
        if projection_revision > global_revision:
            raise ValueError("projection revision cannot exceed global state revision")
        if projection_revision < self._state.projection_revision:
            return False
        new_state = StoreState(
            global_revision,
            projection_revision,
            self._rows(snapshot.get("downloads", ()), "downloads"),
            self._rows(snapshot.get("queue", ()), "queue"),
            self._rows(snapshot.get("history", ()), "history"),
            bool(snapshot.get("history_has_more", False)),
            False,
        )
        changed = new_state != self._state
        self._state = new_state
        return changed
