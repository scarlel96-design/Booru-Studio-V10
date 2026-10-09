from __future__ import annotations

import sqlite3

from booru_studio.common.ids import JobId, StorageTargetId, SubmissionId
from booru_studio.common.serialization import canonical_json_dumps, json_loads_list
from booru_studio.domain.enums import (
    ControlIntent,
    JobActivity,
    JobKind,
    JobLifecycle,
    JobOutcome,
    WaitingReason,
)
from booru_studio.domain.job import Job
from booru_studio.domain.invariants import validate_job


def insert_job(connection: sqlite3.Connection, job: Job) -> None:
    validate_job(job)
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, submission_id, kind, title, lifecycle, outcome, control_intent,
            activities_json, waiting_reasons_json, storage_target_id,
            storage_target_generation, priority, created_at_utc_ms, updated_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(job.job_id),
            str(job.submission_id),
            job.kind.value,
            job.title,
            job.lifecycle.value,
            job.outcome.value if job.outcome is not None else None,
            job.control_intent.value,
            canonical_json_dumps(sorted(a.value for a in job.activities)),
            canonical_json_dumps(sorted(w.value for w in job.waiting_reasons)),
            str(job.storage_target_id) if job.storage_target_id is not None else None,
            job.storage_target_generation,
            job.priority,
            job.created_at_utc_ms,
            job.updated_at_utc_ms,
        ),
    )


def get_job(connection: sqlite3.Connection, job_id: JobId) -> Job | None:
    row = connection.execute(
        """
        SELECT job_id, submission_id, kind, title, lifecycle, outcome, control_intent,
               activities_json, waiting_reasons_json, storage_target_id,
               storage_target_generation, priority, created_at_utc_ms, updated_at_utc_ms
        FROM jobs WHERE job_id=?
        """,
        (str(job_id),),
    ).fetchone()
    if row is None:
        return None
    activities = frozenset(JobActivity(v) for v in json_loads_list(row["activities_json"]))
    waiting = frozenset(WaitingReason(v) for v in json_loads_list(row["waiting_reasons_json"]))
    job = Job(
        job_id=JobId.parse(row["job_id"]),
        submission_id=SubmissionId.parse(row["submission_id"]),
        kind=JobKind(row["kind"]),
        title=str(row["title"]),
        lifecycle=JobLifecycle(row["lifecycle"]),
        outcome=JobOutcome(row["outcome"]) if row["outcome"] is not None else None,
        control_intent=ControlIntent(row["control_intent"]),
        activities=activities,
        waiting_reasons=waiting,
        storage_target_id=(
            StorageTargetId.parse(row["storage_target_id"])
            if row["storage_target_id"] is not None
            else None
        ),
        storage_target_generation=(
            int(row["storage_target_generation"])
            if row["storage_target_generation"] is not None
            else None
        ),
        priority=int(row["priority"]),
        created_at_utc_ms=int(row["created_at_utc_ms"]),
        updated_at_utc_ms=int(row["updated_at_utc_ms"]),
    )
    validate_job(job)
    return job


def update_job_lifecycle(
    connection: sqlite3.Connection,
    *,
    job_id: JobId,
    lifecycle: JobLifecycle,
    now_utc_ms: int,
) -> None:
    cursor = connection.execute(
        """
        UPDATE jobs
        SET lifecycle=?, updated_at_utc_ms=?
        WHERE job_id=?
        """,
        (lifecycle.value, now_utc_ms, str(job_id)),
    )
    if cursor.rowcount != 1:
        raise KeyError(f"job not found: {job_id}")


def settle_job(
    connection: sqlite3.Connection,
    *,
    job_id: JobId,
    outcome: JobOutcome,
    now_utc_ms: int,
) -> None:
    cursor = connection.execute(
        """
        UPDATE jobs
        SET lifecycle=?, outcome=?, updated_at_utc_ms=?
        WHERE job_id=? AND lifecycle<>'SETTLED'
        """,
        (JobLifecycle.SETTLED.value, outcome.value, now_utc_ms, str(job_id)),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("job is missing or already settled")


def classify_job_kind(
    connection: sqlite3.Connection, *, job_id: JobId, kind: JobKind, now_utc_ms: int
) -> bool:
    if kind is JobKind.UNKNOWN:
        raise ValueError("cannot classify a Job to UNKNOWN")
    row = connection.execute("SELECT kind FROM jobs WHERE job_id=?", (str(job_id),)).fetchone()
    if row is None:
        raise KeyError(f"job not found: {job_id}")
    current = JobKind(str(row["kind"]))
    if current is kind:
        return False
    if current is not JobKind.UNKNOWN:
        raise RuntimeError(f"Job already classified as {current.value}")
    connection.execute(
        "UPDATE jobs SET kind=?,updated_at_utc_ms=? WHERE job_id=?",
        (kind.value, now_utc_ms, str(job_id)),
    )
    return True
