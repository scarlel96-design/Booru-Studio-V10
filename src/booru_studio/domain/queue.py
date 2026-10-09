from __future__ import annotations

from dataclasses import dataclass

from booru_studio.common.ids import JobId


@dataclass(frozen=True, slots=True)
class QueueEntry:
    job_id: JobId
    sort_key: int
    enqueued_at_utc_ms: int


@dataclass(frozen=True, slots=True)
class QueuedJob:
    job_id: JobId
    title: str
    sort_key: int
    enqueued_at_utc_ms: int
    priority: int
    position: int
