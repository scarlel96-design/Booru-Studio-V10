from __future__ import annotations

import pytest

from booru_studio.common.ids import (
    ArtifactId,
    EnginePackId,
    ItemId,
    JobId,
    JobRunId,
    PathClaimId,
    SubmissionId,
)
from booru_studio.domain.artifact import Artifact
from booru_studio.domain.enums import (
    ArtifactLifecycle,
    CommitOwnership,
    JobKind,
    JobLifecycle,
    JobOutcome,
)
from booru_studio.domain.invariants import DomainInvariantError, validate_artifact, validate_job
from booru_studio.domain.job import Job
from booru_studio.domain.run import ExecutionSpecSnapshot, JobRun, RuntimePolicy
from booru_studio.domain.transitions import InvalidTransition, assert_artifact_transition, assert_job_transition


def make_job() -> Job:
    return Job(
        job_id=JobId.new(),
        submission_id=SubmissionId.new(),
        kind=JobKind.DIRECT_FILE,
        title="fixture",
    )


def test_job_terminal_invariant() -> None:
    job = make_job()
    job.lifecycle = JobLifecycle.SETTLED
    with pytest.raises(DomainInvariantError):
        validate_job(job)
    job.outcome = JobOutcome.SUCCESS
    validate_job(job)


def test_job_cannot_leave_settled_state() -> None:
    with pytest.raises(InvalidTransition):
        assert_job_transition(JobLifecycle.SETTLED, JobLifecycle.ACTIVE)


def test_artifact_commit_requires_commit_owned_and_path_claim() -> None:
    artifact = Artifact(
        artifact_id=ArtifactId.new(),
        job_id=JobId.new(),
        item_id=ItemId.new(),
        role="primary",
        lifecycle=ArtifactLifecycle.COMMITTED,
    )
    with pytest.raises(DomainInvariantError):
        validate_artifact(artifact)

    artifact.commit_ownership = CommitOwnership.COMMIT_OWNED
    artifact.path_claim_id = PathClaimId.new()
    validate_artifact(artifact)


def test_artifact_transition_is_monotonic() -> None:
    assert_artifact_transition(ArtifactLifecycle.VERIFIED, ArtifactLifecycle.COMMITTED)
    with pytest.raises(InvalidTransition):
        assert_artifact_transition(ArtifactLifecycle.COMMITTED, ArtifactLifecycle.PRODUCED)


def test_execution_spec_snapshot_copies_input_mapping() -> None:
    source: dict[str, object] = {"quality": "best"}
    snapshot = ExecutionSpecSnapshot(source)
    source["quality"] = "worst"
    assert snapshot.values["quality"] == "best"

    JobRun(
        run_id=JobRunId.new(),
        job_id=JobId.new(),
        engine_pack_id=EnginePackId.new(),
        execution_spec=snapshot,
        runtime_policy=RuntimePolicy(),
        started_at_utc_ms=1,
    )


def test_run_rejects_invalid_runtime_policy_limits() -> None:
    from booru_studio.common.ids import EnginePackId, JobId, JobRunId
    from booru_studio.domain.invariants import DomainInvariantError, validate_run
    from booru_studio.domain.run import ExecutionSpecSnapshot, JobRun, RuntimePolicy

    run = JobRun(
        run_id=JobRunId.new(),
        job_id=JobId.new(),
        engine_pack_id=EnginePackId.new(),
        execution_spec=ExecutionSpecSnapshot({}),
        runtime_policy=RuntimePolicy(max_parallel_transfers=0),
        started_at_utc_ms=1,
    )
    with pytest.raises(DomainInvariantError):
        validate_run(run)
