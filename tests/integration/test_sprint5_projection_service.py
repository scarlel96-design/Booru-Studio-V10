from __future__ import annotations

from pathlib import Path

from booru_studio.common.clock import SystemClock
from booru_studio.common.ids import ClientInstanceId, CommandId, EnginePackId
from booru_studio.core.job_service import JobService
from booru_studio.core.projection_service import ProjectionService
from booru_studio.domain.commands import (
    CommandIdentity,
    CreateJobCommand,
    StartJobRunRequest,
)
from booru_studio.domain.enums import InputKind, JobKind, JobOutcome, RunOutcome
from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy
from booru_studio.persistence.db_actor import DbActor


def _create(jobs: JobService, title: str):
    return jobs.create_job(
        CreateJobCommand(
            identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
            input_kind=InputKind.URL,
            redacted_input=f"https://example.test/{title}",
            job_kind=JobKind.DIRECT_FILE,
            title=title,
        )
    )


def test_projection_snapshot_separates_download_queue_and_history(tmp_path: Path) -> None:
    clock = SystemClock()
    actor = DbActor(tmp_path / "한글 상태" / "ui.sqlite3", now_utc_ms=clock.utc_ms())
    actor.start()
    jobs = JobService(actor, clock)
    projection = ProjectionService(actor)
    try:
        queued = _create(jobs, "Queued")
        completed = _create(jobs, "Completed")
        run = jobs.start_job_run(
            StartJobRunRequest(
                job_id=completed.job_id,
                engine_pack_id=EnginePackId.new(),
                execution_spec=ExecutionSpecSnapshot({"url": "https://example.test/completed"}),
                runtime_policy=RuntimePolicy(),
                worker_generation=1,
            )
        )
        settled_revision = jobs.settle_job_run(
            run.run_id,
            run_outcome=RunOutcome.SUCCESS,
            job_outcome=JobOutcome.SUCCESS,
        )
        snapshot = projection.snapshot()
        assert snapshot["global_state_revision"] == settled_revision
        assert snapshot["projection_revision"] == settled_revision
        assert [row["job_id"] for row in snapshot["queue"]] == [str(queued.job_id)]
        assert {row["job_id"] for row in snapshot["downloads"]} == {str(queued.job_id)}
        assert [row["job_id"] for row in snapshot["history"]] == [str(completed.job_id)]
        assert snapshot["history"][0]["outcome"] == "SUCCESS"
    finally:
        actor.close()


def test_projection_snapshot_is_persistent_across_actor_restart(tmp_path: Path) -> None:
    clock = SystemClock()
    path = tmp_path / "state.sqlite3"
    actor = DbActor(path, now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    created = _create(jobs, "Persist me")
    revision = jobs.state_revision()
    actor.close()

    actor2 = DbActor(path, now_utc_ms=clock.utc_ms()); actor2.start()
    try:
        snapshot = ProjectionService(actor2).snapshot()
        assert snapshot["global_state_revision"] == revision
        assert snapshot["queue"][0]["job_id"] == str(created.job_id)
        assert snapshot["downloads"][0]["title"] == "Persist me"
    finally:
        actor2.close()


def test_history_projection_is_bounded_and_reports_more(tmp_path: Path) -> None:
    from booru_studio.persistence.repositories.projection_repository import read_projection_snapshot

    clock = SystemClock()
    actor = DbActor(tmp_path / "history.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    try:
        for index in range(5):
            created = _create(jobs, f"Done-{index}")
            run = jobs.start_job_run(StartJobRunRequest(
                job_id=created.job_id, engine_pack_id=EnginePackId.new(),
                execution_spec=ExecutionSpecSnapshot({}), runtime_policy=RuntimePolicy(), worker_generation=1,
            ))
            jobs.settle_job_run(run.run_id, run_outcome=RunOutcome.SUCCESS, job_outcome=JobOutcome.SUCCESS)
        snapshot = actor.submit(lambda c: read_projection_snapshot(c, history_page_size=3)).result(3)
        assert len(snapshot["history"]) == 3
        assert snapshot["history_has_more"] is True
        assert snapshot["history_page_size"] == 3
    finally:
        actor.close()
