from __future__ import annotations

from dataclasses import dataclass

from booru_studio.domain.artifact import Artifact
from booru_studio.domain.enums import (
    ArtifactLifecycle,
    CommitOwnership,
    ItemLifecycle,
    JobLifecycle,
)
from booru_studio.domain.item import Item
from booru_studio.domain.job import Job
from booru_studio.domain.run import JobRun


@dataclass(frozen=True, slots=True)
class DomainInvariantError(ValueError):
    invariant: str

    def __str__(self) -> str:
        return self.invariant


def validate_job(job: Job) -> None:
    if job.lifecycle is JobLifecycle.SETTLED and job.outcome is None:
        raise DomainInvariantError("settled job must have an outcome")
    if job.lifecycle is not JobLifecycle.SETTLED and job.outcome is not None:
        raise DomainInvariantError("non-settled job cannot have a terminal outcome")
    if job.lifecycle is not JobLifecycle.WAITING and job.waiting_reasons:
        raise DomainInvariantError("waiting reasons require WAITING lifecycle")
    if (job.storage_target_id is None) != (job.storage_target_generation is None):
        raise DomainInvariantError("storage target id and generation must be supplied together")
    if job.storage_target_generation is not None and job.storage_target_generation < 0:
        raise DomainInvariantError("storage target generation cannot be negative")


def validate_run(run: JobRun) -> None:
    if (run.outcome is None) != (run.ended_at_utc_ms is None):
        raise DomainInvariantError("run outcome and ended timestamp must become terminal together")
    if run.worker_generation < 0:
        raise DomainInvariantError("worker generation cannot be negative")
    if (
        run.runtime_policy.bandwidth_limit_bps is not None
        and run.runtime_policy.bandwidth_limit_bps < 0
    ):
        raise DomainInvariantError("bandwidth limit cannot be negative")
    if (
        run.runtime_policy.max_parallel_transfers is not None
        and run.runtime_policy.max_parallel_transfers <= 0
    ):
        raise DomainInvariantError("max parallel transfers must be positive")


def validate_item(item: Item) -> None:
    if item.lifecycle is ItemLifecycle.SETTLED and item.outcome is None:
        raise DomainInvariantError("settled item must have an outcome")
    if item.lifecycle is not ItemLifecycle.SETTLED and item.outcome is not None:
        raise DomainInvariantError("non-settled item cannot have a terminal outcome")


def validate_artifact(artifact: Artifact) -> None:
    if artifact.lifecycle is ArtifactLifecycle.COMMITTED:
        if artifact.commit_ownership is not CommitOwnership.COMMIT_OWNED:
            raise DomainInvariantError("committed artifact must be commit-owned")
        if artifact.path_claim_id is None:
            raise DomainInvariantError("committed artifact must retain path claim identity")
    if artifact.expected_size is not None and artifact.expected_size < 0:
        raise DomainInvariantError("expected size cannot be negative")
    if artifact.sha256_hex is not None:
        if len(artifact.sha256_hex) != 64:
            raise DomainInvariantError("sha256 must be 64 hexadecimal characters")
        try:
            int(artifact.sha256_hex, 16)
        except ValueError as exc:
            raise DomainInvariantError("sha256 must be hexadecimal") from exc
