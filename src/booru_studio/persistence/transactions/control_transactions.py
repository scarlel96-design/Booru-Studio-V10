from __future__ import annotations

import sqlite3

from booru_studio.common.serialization import canonical_json_dumps, canonical_json_sha256, json_loads_object
from booru_studio.domain.commands import (
    CancelJobCommand, CancelJobResult, CommandType, JobControlResult, MoveQueueJobCommand,
    PauseJobCommand, ResumeJobCommand,
)
from booru_studio.domain.enums import ControlIntent, JobLifecycle
from booru_studio.domain.transitions import assert_job_transition
from booru_studio.persistence.repositories.command_receipt_repository import get_command_receipt, insert_command_receipt
from booru_studio.persistence.repositories.job_repository import get_job
from booru_studio.persistence.repositories.queue_repository import QUEUE_SORT_STEP, enqueue_job, remove_job_from_queue
from booru_studio.persistence.repositories.state_repository import append_domain_event, bump_state_revision
from booru_studio.persistence.transactions.base import write_transaction
from booru_studio.persistence.transactions.job_transactions import CommandReplayConflict


def _replay_or_none(connection, *, command, command_type: CommandType, request_hash: bytes):
    receipt = get_command_receipt(connection, client_instance_id=command.identity.client_instance_id, command_id=command.identity.command_id)
    if receipt is None:
        return None
    if receipt.command_type != command_type.value or receipt.request_hash != request_hash:
        raise CommandReplayConflict("control command replay conflict")
    obj = json_loads_object(receipt.result_json)
    return JobControlResult(job_id=command.job_id, committed_state_revision=int(obj["committed_state_revision"]), replayed=True)


def _record(connection, *, command, command_type: CommandType, request_hash: bytes, revision: int, now_utc_ms: int) -> JobControlResult:
    result_json = canonical_json_dumps({"job_id": str(command.job_id), "committed_state_revision": revision})
    insert_command_receipt(connection, client_instance_id=command.identity.client_instance_id, command_id=command.identity.command_id, command_type=command_type.value, request_hash=request_hash, result_json=result_json, committed_state_revision=revision, now_utc_ms=now_utc_ms)
    return JobControlResult(command.job_id, revision, False)


def cancel_job_transaction(connection: sqlite3.Connection, *, command: CancelJobCommand, now_utc_ms: int) -> CancelJobResult:
    request_hash = canonical_json_sha256(command.request_payload())
    with write_transaction(connection):
        replay = _replay_or_none(connection, command=command, command_type=CommandType.CANCEL_JOB, request_hash=request_hash)
        if replay is not None:
            return CancelJobResult(replay.job_id, replay.committed_state_revision, True)
        job = get_job(connection, command.job_id)
        if job is None:
            raise KeyError("job not found")
        if job.lifecycle is JobLifecycle.SETTLED:
            raise ValueError("settled job cannot be cancelled")
        connection.execute("UPDATE jobs SET control_intent=?,updated_at_utc_ms=? WHERE job_id=?", (ControlIntent.CANCEL_REQUESTED.value, now_utc_ms, str(command.job_id)))
        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(connection, state_revision=revision, event_type="JOB_CANCEL_REQUESTED", subject_kind="JOB", subject_id=str(command.job_id), payload_json=canonical_json_dumps({"job_id": str(command.job_id)}), now_utc_ms=now_utc_ms)
        result = _record(connection, command=command, command_type=CommandType.CANCEL_JOB, request_hash=request_hash, revision=revision, now_utc_ms=now_utc_ms)
        return CancelJobResult(result.job_id, result.committed_state_revision, result.replayed)


def pause_job_transaction(connection: sqlite3.Connection, *, command: PauseJobCommand, now_utc_ms: int) -> JobControlResult:
    request_hash = canonical_json_sha256(command.request_payload())
    with write_transaction(connection):
        replay = _replay_or_none(connection, command=command, command_type=CommandType.PAUSE_JOB, request_hash=request_hash)
        if replay is not None:
            return replay
        job = get_job(connection, command.job_id)
        if job is None:
            raise KeyError("job not found")
        if job.lifecycle is JobLifecycle.SETTLED:
            raise ValueError("settled job cannot be paused")
        if job.lifecycle is JobLifecycle.PAUSED:
            raise ValueError("job is already paused")
        event_type = "JOB_PAUSE_REQUESTED"
        if job.lifecycle is JobLifecycle.QUEUED:
            assert_job_transition(job.lifecycle, JobLifecycle.PAUSED)
            connection.execute("UPDATE jobs SET lifecycle=?,control_intent=?,updated_at_utc_ms=? WHERE job_id=?", (JobLifecycle.PAUSED.value, ControlIntent.NONE.value, now_utc_ms, str(command.job_id)))
            remove_job_from_queue(connection, command.job_id)
            event_type = "JOB_PAUSED"
        else:
            connection.execute("UPDATE jobs SET control_intent=?,updated_at_utc_ms=? WHERE job_id=?", (ControlIntent.PAUSE_REQUESTED.value, now_utc_ms, str(command.job_id)))
        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(connection, state_revision=revision, event_type=event_type, subject_kind="JOB", subject_id=str(command.job_id), payload_json=canonical_json_dumps({"job_id": str(command.job_id)}), now_utc_ms=now_utc_ms)
        return _record(connection, command=command, command_type=CommandType.PAUSE_JOB, request_hash=request_hash, revision=revision, now_utc_ms=now_utc_ms)


def resume_job_transaction(connection: sqlite3.Connection, *, command: ResumeJobCommand, now_utc_ms: int) -> JobControlResult:
    request_hash = canonical_json_sha256(command.request_payload())
    with write_transaction(connection):
        replay = _replay_or_none(connection, command=command, command_type=CommandType.RESUME_JOB, request_hash=request_hash)
        if replay is not None:
            return replay
        job = get_job(connection, command.job_id)
        if job is None:
            raise KeyError("job not found")
        if job.lifecycle is not JobLifecycle.PAUSED:
            raise ValueError("only paused jobs can be resumed from the UI")
        assert_job_transition(job.lifecycle, JobLifecycle.QUEUED)
        connection.execute("UPDATE jobs SET lifecycle=?,control_intent=?,updated_at_utc_ms=? WHERE job_id=?", (JobLifecycle.QUEUED.value, ControlIntent.NONE.value, now_utc_ms, str(command.job_id)))
        enqueue_job(connection, job_id=command.job_id, now_utc_ms=now_utc_ms)
        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(connection, state_revision=revision, event_type="JOB_RESUMED_TO_QUEUE", subject_kind="JOB", subject_id=str(command.job_id), payload_json=canonical_json_dumps({"job_id": str(command.job_id)}), now_utc_ms=now_utc_ms)
        return _record(connection, command=command, command_type=CommandType.RESUME_JOB, request_hash=request_hash, revision=revision, now_utc_ms=now_utc_ms)


def move_queue_job_transaction(connection: sqlite3.Connection, *, command: MoveQueueJobCommand, now_utc_ms: int) -> JobControlResult:
    request_hash = canonical_json_sha256(command.request_payload())
    direction = command.direction.upper()
    if direction not in {"UP", "DOWN"}:
        raise ValueError("queue direction must be UP or DOWN")
    with write_transaction(connection):
        replay = _replay_or_none(connection, command=command, command_type=CommandType.MOVE_QUEUE_JOB, request_hash=request_hash)
        if replay is not None:
            return replay
        rows = list(connection.execute("SELECT job_id FROM queue_entries ORDER BY sort_key ASC, job_id ASC").fetchall())
        ids = [str(r["job_id"]) for r in rows]
        target = str(command.job_id)
        if target not in ids:
            raise ValueError("job is not in the queue")
        idx = ids.index(target)
        other = idx - 1 if direction == "UP" else idx + 1
        if other < 0 or other >= len(ids):
            raise ValueError("job is already at the queue boundary")
        ids[idx], ids[other] = ids[other], ids[idx]
        # Avoid transient collisions with the UNIQUE(sort_key) constraint by moving the current
        # queue to a disjoint negative key space before assigning normalized positive keys.
        for n, job_id in enumerate(ids, start=1):
            connection.execute("UPDATE queue_entries SET sort_key=? WHERE job_id=?", (-n, job_id))
        for n, job_id in enumerate(ids, start=1):
            connection.execute("UPDATE queue_entries SET sort_key=? WHERE job_id=?", (n * QUEUE_SORT_STEP, job_id))
        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(connection, state_revision=revision, event_type="QUEUE_JOB_MOVED", subject_kind="JOB", subject_id=target, payload_json=canonical_json_dumps({"job_id": target, "direction": direction}), now_utc_ms=now_utc_ms)
        return _record(connection, command=command, command_type=CommandType.MOVE_QUEUE_JOB, request_hash=request_hash, revision=revision, now_utc_ms=now_utc_ms)
