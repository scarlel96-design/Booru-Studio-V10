from __future__ import annotations

import sqlite3
from dataclasses import replace

from booru_studio.common.ids import JobId, JobRunId, SubmissionId
from booru_studio.common.serialization import (
    canonical_json_dumps,
    canonical_json_sha256,
    json_loads_object,
)
from booru_studio.domain.commands import (
    CommandType,
    CreateJobCommand,
    CreateJobResult,
    StartJobRunRequest,
    StartJobRunResult,
)
from booru_studio.domain.enums import ControlIntent, JobLifecycle
from booru_studio.domain.invariants import validate_job, validate_run
from booru_studio.domain.job import Job
from booru_studio.domain.run import JobRun
from booru_studio.domain.submission import Submission
from booru_studio.domain.transitions import assert_job_transition
from booru_studio.persistence.repositories.command_receipt_repository import (
    get_command_receipt,
    insert_command_receipt,
)
from booru_studio.persistence.repositories.job_repository import (
    get_job,
    insert_job,
    update_job_lifecycle,
)
from booru_studio.persistence.repositories.queue_repository import (
    enqueue_job,
    remove_job_from_queue,
)
from booru_studio.persistence.repositories.run_repository import get_open_run, insert_run
from booru_studio.persistence.repositories.state_repository import (
    append_domain_event,
    bump_state_revision,
)
from booru_studio.persistence.repositories.submission_repository import insert_submission
from booru_studio.persistence.transactions.base import write_transaction


class CommandReplayConflict(ValueError):
    """The same idempotency key was reused for a different command payload."""


class JobRunConflict(ValueError):
    """A new run could not start because the job/run state is incompatible."""


def _validate_create_job_command(command: CreateJobCommand) -> None:
    if not command.redacted_input.strip():
        raise ValueError("redacted_input must not be empty")
    if not command.title.strip():
        raise ValueError("title must not be empty")
    if (command.storage_target_id is None) != (command.storage_target_generation is None):
        raise ValueError("storage target id and generation must be supplied together")
    if command.storage_target_generation is not None and command.storage_target_generation < 0:
        raise ValueError("storage target generation cannot be negative")


def _decode_create_job_result(raw: str, *, replayed: bool) -> CreateJobResult:
    obj = json_loads_object(raw)
    return CreateJobResult(
        submission_id=SubmissionId.parse(str(obj["submission_id"])),
        job_id=JobId.parse(str(obj["job_id"])),
        committed_state_revision=int(obj["committed_state_revision"]),
        replayed=replayed,
    )


def execute_create_job_command(
    connection: sqlite3.Connection,
    *,
    command: CreateJobCommand,
    now_utc_ms: int,
) -> CreateJobResult:
    """Atomically create Submission + Job + QueueEntry + receipt + revision.

    A replay after a lost response returns the original result without creating a
    second Job or advancing state_revision. Reusing the same command identity for
    different content is rejected rather than silently replaying the wrong result.
    """

    _validate_create_job_command(command)
    request_hash = canonical_json_sha256(command.request_payload())

    with write_transaction(connection):
        receipt = get_command_receipt(
            connection,
            client_instance_id=command.identity.client_instance_id,
            command_id=command.identity.command_id,
        )
        if receipt is not None:
            if receipt.command_type != CommandType.CREATE_JOB.value:
                raise CommandReplayConflict("command id was already used for another command type")
            if receipt.request_hash != request_hash:
                raise CommandReplayConflict("command id was replayed with a different payload")
            return _decode_create_job_result(receipt.result_json, replayed=True)

        submission = Submission(
            submission_id=SubmissionId.new(),
            input_kind=command.input_kind,
            redacted_input=command.redacted_input,
            created_at_utc_ms=now_utc_ms,
        )
        job = Job(
            job_id=JobId.new(),
            submission_id=submission.submission_id,
            kind=command.job_kind,
            title=command.title,
            lifecycle=JobLifecycle.QUEUED,
            control_intent=ControlIntent.NONE,
            storage_target_id=command.storage_target_id,
            storage_target_generation=command.storage_target_generation,
            priority=command.priority,
            created_at_utc_ms=now_utc_ms,
            updated_at_utc_ms=now_utc_ms,
        )
        validate_job(job)

        insert_submission(connection, submission)
        insert_job(connection, job)
        enqueue_job(connection, job_id=job.job_id, now_utc_ms=now_utc_ms)

        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        payload_json = canonical_json_dumps(
            {
                "job_id": str(job.job_id),
                "submission_id": str(submission.submission_id),
            }
        )
        append_domain_event(
            connection,
            state_revision=revision,
            event_type="JOB_CREATED",
            subject_kind="JOB",
            subject_id=str(job.job_id),
            payload_json=payload_json,
            now_utc_ms=now_utc_ms,
        )

        result_json = canonical_json_dumps(
            {
                "submission_id": str(submission.submission_id),
                "job_id": str(job.job_id),
                "committed_state_revision": revision,
            }
        )
        insert_command_receipt(
            connection,
            client_instance_id=command.identity.client_instance_id,
            command_id=command.identity.command_id,
            command_type=CommandType.CREATE_JOB.value,
            request_hash=request_hash,
            result_json=result_json,
            committed_state_revision=revision,
            now_utc_ms=now_utc_ms,
        )

        return CreateJobResult(
            submission_id=submission.submission_id,
            job_id=job.job_id,
            committed_state_revision=revision,
            replayed=False,
        )


def start_job_run_transaction(
    connection: sqlite3.Connection,
    *,
    request: StartJobRunRequest,
    now_utc_ms: int,
) -> StartJobRunResult:
    """Atomically move a Job into ACTIVE and persist its first/open JobRun."""

    if request.worker_generation < 0:
        raise ValueError("worker_generation cannot be negative")

    with write_transaction(connection):
        job = get_job(connection, request.job_id)
        if job is None:
            raise KeyError(f"job not found: {request.job_id}")
        if get_open_run(connection, request.job_id) is not None:
            raise JobRunConflict("job already has an open run")

        try:
            assert_job_transition(job.lifecycle, JobLifecycle.ACTIVE)
        except ValueError as exc:
            raise JobRunConflict(str(exc)) from exc

        run = JobRun(
            run_id=JobRunId.new(),
            job_id=request.job_id,
            engine_pack_id=request.engine_pack_id,
            execution_spec=request.execution_spec,
            runtime_policy=replace(request.runtime_policy),
            started_at_utc_ms=now_utc_ms,
            worker_generation=request.worker_generation,
        )
        validate_run(run)
        # Force deterministic JSON serialization now, before any durable mutations.
        canonical_json_dumps(dict(run.execution_spec.values))

        insert_run(connection, run)
        update_job_lifecycle(
            connection,
            job_id=job.job_id,
            lifecycle=JobLifecycle.ACTIVE,
            now_utc_ms=now_utc_ms,
        )
        remove_job_from_queue(connection, job.job_id)

        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(
            connection,
            state_revision=revision,
            event_type="JOB_RUN_STARTED",
            subject_kind="JOB",
            subject_id=str(job.job_id),
            payload_json=canonical_json_dumps(
                {
                    "job_id": str(job.job_id),
                    "run_id": str(run.run_id),
                    "engine_pack_id": str(run.engine_pack_id),
                }
            ),
            now_utc_ms=now_utc_ms,
        )
        return StartJobRunResult(
            run_id=run.run_id,
            job_id=job.job_id,
            committed_state_revision=revision,
        )


def settle_job_run_transaction(
    connection: sqlite3.Connection,
    *,
    run_id: JobRunId,
    run_outcome,
    job_outcome,
    now_utc_ms: int,
) -> int:
    """Atomically close an open Run and settle its Job for UI/history projection."""
    from booru_studio.domain.enums import JobOutcome, RunOutcome
    from booru_studio.persistence.repositories.run_repository import get_run, settle_run
    from booru_studio.persistence.repositories.job_repository import settle_job

    if not isinstance(run_outcome, RunOutcome):
        raise TypeError("run_outcome must be RunOutcome")
    if not isinstance(job_outcome, JobOutcome):
        raise TypeError("job_outcome must be JobOutcome")
    if run_outcome is RunOutcome.SUSPENDED:
        raise ValueError("SUSPENDED run cannot settle a Job")
    valid = {
        RunOutcome.SUCCESS: {JobOutcome.SUCCESS, JobOutcome.NOOP, JobOutcome.EMPTY, JobOutcome.PARTIAL_SUCCESS},
        RunOutcome.FAILED: {JobOutcome.FAILED, JobOutcome.PARTIAL_SUCCESS},
        RunOutcome.CANCELLED: {JobOutcome.CANCELLED},
        RunOutcome.CRASHED: {JobOutcome.FAILED},
    }
    if job_outcome not in valid.get(run_outcome, set()):
        raise ValueError("RunOutcome and JobOutcome are inconsistent")

    with write_transaction(connection):
        run = get_run(connection, run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        if run.ended_at_utc_ms is not None:
            raise JobRunConflict("run is already settled")
        job = get_job(connection, run.job_id)
        if job is None:
            raise KeyError(f"job not found: {run.job_id}")
        assert_job_transition(job.lifecycle, JobLifecycle.SETTLED)
        settle_run(connection, run_id=run_id, outcome=run_outcome, now_utc_ms=now_utc_ms)
        settle_job(connection, job_id=run.job_id, outcome=job_outcome, now_utc_ms=now_utc_ms)
        remove_job_from_queue(connection, run.job_id)
        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(
            connection,
            state_revision=revision,
            event_type="JOB_SETTLED",
            subject_kind="JOB",
            subject_id=str(run.job_id),
            payload_json=canonical_json_dumps(
                {
                    "job_id": str(run.job_id),
                    "run_id": str(run_id),
                    "run_outcome": run_outcome.value,
                    "job_outcome": job_outcome.value,
                }
            ),
            now_utc_ms=now_utc_ms,
        )
        return revision


def apply_worker_control_observation(
    connection: sqlite3.Connection,
    *,
    run_id: JobRunId,
    job_id: JobId,
    observation: str,
    now_utc_ms: int,
) -> int:
    """Apply an authenticated Worker Pause/Cancel observation inside an existing transaction.

    This function intentionally does *not* open its own transaction. It is designed to run as the
    side effect of ``commit_worker_transaction`` so the durable Worker transaction receipt and the
    authoritative Job/Run state transition either commit together or roll back together.
    """
    from booru_studio.domain.enums import JobOutcome, RunOutcome
    from booru_studio.persistence.repositories.run_repository import get_run, settle_run
    from booru_studio.persistence.repositories.job_repository import settle_job

    if observation not in {"PAUSE_OBSERVED", "CANCEL_OBSERVED"}:
        raise ValueError("unsupported Worker control observation")
    run = get_run(connection, run_id)
    if run is None or run.job_id != job_id:
        raise KeyError("Worker control observation references an unknown Run/Job")
    if run.ended_at_utc_ms is not None:
        raise JobRunConflict("Worker control observation arrived for a closed Run")
    job = get_job(connection, job_id)
    if job is None:
        raise KeyError(f"job not found: {job_id}")

    # Cancel is stronger than Pause. If the user upgraded a durable PAUSE request to CANCEL before
    # the Worker reached the checkpoint, a late PAUSE_OBSERVED still closes the stopped Run as a
    # cancellation rather than losing the user's newer intent.
    cancel = observation == "CANCEL_OBSERVED" or job.control_intent is ControlIntent.CANCEL_REQUESTED
    if cancel:
        if job.control_intent is not ControlIntent.CANCEL_REQUESTED:
            raise JobRunConflict("Worker reported cancellation without a durable cancel intent")
        assert_job_transition(job.lifecycle, JobLifecycle.SETTLED)
        settle_run(connection, run_id=run_id, outcome=RunOutcome.CANCELLED, now_utc_ms=now_utc_ms)
        settle_job(connection, job_id=job_id, outcome=JobOutcome.CANCELLED, now_utc_ms=now_utc_ms)
        connection.execute(
            "UPDATE jobs SET control_intent=?,activities_json='[]',waiting_reasons_json='[]',updated_at_utc_ms=? WHERE job_id=?",
            (ControlIntent.NONE.value, now_utc_ms, str(job_id)),
        )
        remove_job_from_queue(connection, job_id)
        event_type = "JOB_CANCEL_OBSERVED"
        payload = {"job_id": str(job_id), "run_id": str(run_id), "worker_observation": observation}
    else:
        if job.control_intent is not ControlIntent.PAUSE_REQUESTED:
            raise JobRunConflict("Worker reported pause without a durable pause intent")
        assert_job_transition(job.lifecycle, JobLifecycle.PAUSED)
        settle_run(connection, run_id=run_id, outcome=RunOutcome.SUSPENDED, now_utc_ms=now_utc_ms)
        connection.execute(
            """
            UPDATE jobs
            SET lifecycle=?, outcome=NULL, control_intent=?, activities_json='[]',
                waiting_reasons_json='[]', updated_at_utc_ms=?
            WHERE job_id=?
            """,
            (JobLifecycle.PAUSED.value, ControlIntent.NONE.value, now_utc_ms, str(job_id)),
        )
        remove_job_from_queue(connection, job_id)
        event_type = "JOB_PAUSE_OBSERVED"
        payload = {"job_id": str(job_id), "run_id": str(run_id)}

    revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
    append_domain_event(
        connection, state_revision=revision, event_type=event_type, subject_kind="JOB",
        subject_id=str(job_id), payload_json=canonical_json_dumps(payload), now_utc_ms=now_utc_ms,
    )
    return revision


def suspend_job_run_transaction(
    connection: sqlite3.Connection,
    *,
    run_id: JobRunId,
    now_utc_ms: int,
) -> int:
    """Close the current Run as SUSPENDED and make its Job durably PAUSED."""
    from booru_studio.domain.enums import ControlIntent, JobLifecycle, RunOutcome
    from booru_studio.persistence.repositories.run_repository import get_run, settle_run
    from booru_studio.persistence.repositories.job_repository import get_job

    with write_transaction(connection):
        run = get_run(connection, run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        if run.ended_at_utc_ms is not None:
            raise JobRunConflict("run is already settled")
        job = get_job(connection, run.job_id)
        if job is None:
            raise KeyError(f"job not found: {run.job_id}")
        assert_job_transition(job.lifecycle, JobLifecycle.PAUSED)
        settle_run(connection, run_id=run_id, outcome=RunOutcome.SUSPENDED, now_utc_ms=now_utc_ms)
        connection.execute(
            """
            UPDATE jobs
            SET lifecycle=?, outcome=NULL, control_intent=?, activities_json='[]',
                waiting_reasons_json='[]', updated_at_utc_ms=?
            WHERE job_id=?
            """,
            (JobLifecycle.PAUSED.value, ControlIntent.NONE.value, now_utc_ms, str(run.job_id)),
        )
        remove_job_from_queue(connection, run.job_id)
        revision = bump_state_revision(connection, now_utc_ms=now_utc_ms)
        append_domain_event(
            connection, state_revision=revision, event_type="JOB_RUN_SUSPENDED",
            subject_kind="JOB", subject_id=str(run.job_id),
            payload_json=canonical_json_dumps({"job_id":str(run.job_id),"run_id":str(run_id)}),
            now_utc_ms=now_utc_ms,
        )
        return revision
