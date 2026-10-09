from __future__ import annotations

from typing import Any, Iterable, Mapping


class ListData:
    """Qt-independent stable-ID list data used by QAbstractListModel adapters."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._by_id: dict[str, int] = {}

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._rows)

    @property
    def job_ids(self) -> tuple[str, ...]:
        return tuple(str(row["job_id"]) for row in self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def replace(self, rows: Iterable[Mapping[str, object]]) -> None:
        materialized = [{str(k): v for k, v in row.items()} for row in rows]
        identifiers = [str(row.get("job_id") or "") for row in materialized]
        if any(not value for value in identifiers):
            raise ValueError("every model row requires job_id")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate job_id in model projection")
        self._rows = materialized
        self._by_id = {job_id: index for index, job_id in enumerate(identifiers)}

    def index_of(self, job_id: str) -> int | None:
        return self._by_id.get(job_id)

    def get(self, index: int) -> dict[str, Any]:
        return dict(self._rows[index])
