from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import TypeVar

from booru_studio.common.clock import Clock
from booru_studio.common.ids import JobId, JobRunId
from booru_studio.common.serialization import canonical_json_dumps
from booru_studio.domain.commands import (
    CancelJobCommand,
    CancelJobResult,
    JobControlResult,
    MoveQueueJobCommand,
    PauseJobCommand,
    ResumeJobCommand,
    CreateJobCommand,
    CreateJobResult,
    StartJobRunRequest,
    StartJobRunResult,
)
from booru_studio.domain.enums import JobKind, JobOutcome, RunOutcome
from booru_studio.domain.job import Job
from booru_studio.domain.queue import QueuedJob
from booru_studio.domain.run import JobRun
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.job_repository import classify_job_kind, get_job
from booru_studio.persistence.repositories.queue_repository import list_queued_jobs
from booru_studio.persistence.repositories.run_repository import get_open_run, get_run
from booru_studio.persistence.repositories.state_repository import append_domain_event, bump_state_revision, get_state_revision
from booru_studio.persistence.transactions.base import write_transaction
from booru_studio.persistence.transactions.control_transactions import (
    cancel_job_transaction, move_queue_job_transaction, pause_job_transaction, resume_job_transaction,
)
from booru_studio.persistence.transactions.job_transactions import (
    execute_create_job_command,
    start_job_run_transaction,
    settle_job_run_transaction,
    suspend_job_run_transaction,
)


T = TypeVar("T")


class JobService:
    """Core-facing Sprint 1 application service over the single DB actor."""

    def __init__(self, db_actor: DbActor, clock: Clock, *, db_timeout_s: float = 5.0) -> None:
        if db_timeout_s <= 0:
            raise ValueError("db_timeout_s must be positive")
        self._db_actor = db_actor
        self._clock = clock
        self._db_timeout_s = db_timeout_s

    def _wait(self, future: Future[T]) -> T:
        try:
            return future.result(timeout=self._db_timeout_s)
        except FutureTimeoutError as exc:
            raise TimeoutError("database operation timed out") from exc

    def create_job(self, command: CreateJobCommand) -> CreateJobResult:
        now = self._clock.utc_ms()
        return self._wait(
            self._db_actor.submit(
                lambda connection: execute_create_job_command(
                    connection,
                    command=command,
                    now_utc_ms=now,
                )
            )
        )


    def classify_job(self, job_id: JobId, kind: JobKind) -> int:
        now = self._clock.utc_ms()
        def op(connection):
            with write_transaction(connection):
                changed = classify_job_kind(connection, job_id=job_id, kind=kind, now_utc_ms=now)
                if not changed:
                    return get_state_revision(connection)
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection, state_revision=revision, event_type="JOB_CLASSIFIED",
                    subject_kind="JOB", subject_id=str(job_id),
                    payload_json=canonical_json_dumps({"kind": kind.value}), now_utc_ms=now,
                )
                return revision
        return self._wait(self._db_actor.submit(op))

    def start_job_run(self, request: StartJobRunRequest) -> StartJobRunResult:
        now = self._clock.utc_ms()
        return self._wait(
            self._db_actor.submit(
                lambda connection: start_job_run_transaction(
                    connection,
                    request=request,
                    now_utc_ms=now,
                )
            )
        )

    def settle_job_run(
        self,
        run_id: JobRunId,
        *,
        run_outcome: RunOutcome,
        job_outcome: JobOutcome,
    ) -> int:
        now = self._clock.utc_ms()
        return self._wait(
            self._db_actor.submit(
                lambda connection: settle_job_run_transaction(
                    connection,
                    run_id=run_id,
                    run_outcome=run_outcome,
                    job_outcome=job_outcome,
                    now_utc_ms=now,
                )
            )
        )

    def suspend_job_run(self, run_id: JobRunId) -> int:
        now = self._clock.utc_ms()
        return self._wait(self._db_actor.submit(lambda connection: suspend_job_run_transaction(
            connection, run_id=run_id, now_utc_ms=now
        )))

    def get_job(self, job_id: JobId) -> Job | None:
        return self._wait(self._db_actor.submit(lambda connection: get_job(connection, job_id)))

    def list_queue(self) -> list[QueuedJob]:
        return self._wait(self._db_actor.submit(list_queued_jobs))

    def get_open_run(self, job_id: JobId) -> JobRun | None:
        return self._wait(self._db_actor.submit(lambda connection: get_open_run(connection, job_id)))

    def get_run(self, run_id: JobRunId) -> JobRun | None:
        return self._wait(self._db_actor.submit(lambda connection: get_run(connection, run_id)))


    def cancel_job(self, command: CancelJobCommand) -> CancelJobResult:
        now = self._clock.utc_ms()
        return self._wait(
            self._db_actor.submit(
                lambda connection: cancel_job_transaction(
                    connection, command=command, now_utc_ms=now
                )
            )
        )


    def pause_job(self, command: PauseJobCommand) -> JobControlResult:
        now = self._clock.utc_ms()
        return self._wait(self._db_actor.submit(lambda connection: pause_job_transaction(connection, command=command, now_utc_ms=now)))

    def resume_job(self, command: ResumeJobCommand) -> JobControlResult:
        now = self._clock.utc_ms()
        return self._wait(self._db_actor.submit(lambda connection: resume_job_transaction(connection, command=command, now_utc_ms=now)))

    def move_queue_job(self, command: MoveQueueJobCommand) -> JobControlResult:
        now = self._clock.utc_ms()
        return self._wait(self._db_actor.submit(lambda connection: move_queue_job_transaction(connection, command=command, now_utc_ms=now)))

    def state_revision(self) -> int:
        return self._wait(self._db_actor.submit(get_state_revision))
