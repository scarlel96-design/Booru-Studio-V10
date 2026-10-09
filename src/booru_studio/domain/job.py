from __future__ import annotations

from dataclasses import dataclass, field

from booru_studio.common.ids import JobId, StorageTargetId, SubmissionId
from booru_studio.domain.enums import (
    ControlIntent,
    JobActivity,
    JobKind,
    JobLifecycle,
    JobOutcome,
    WaitingReason,
)


@dataclass(slots=True)
class Job:
    job_id: JobId
    submission_id: SubmissionId
    kind: JobKind
    title: str
    lifecycle: JobLifecycle = JobLifecycle.QUEUED
    outcome: JobOutcome | None = None
    control_intent: ControlIntent = ControlIntent.NONE
    activities: frozenset[JobActivity] = field(default_factory=frozenset)
    waiting_reasons: frozenset[WaitingReason] = field(default_factory=frozenset)
    storage_target_id: StorageTargetId | None = None
    storage_target_generation: int | None = None
    priority: int = 0
    created_at_utc_ms: int = 0
    updated_at_utc_ms: int = 0
