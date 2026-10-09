from __future__ import annotations

from dataclasses import dataclass

from booru_studio.domain.enums import (
    ArtifactLifecycle,
    ItemLifecycle,
    JobLifecycle,
)


@dataclass(frozen=True, slots=True)
class InvalidTransition(ValueError):
    entity: str
    current: str
    target: str

    def __str__(self) -> str:
        return f"invalid {self.entity} transition: {self.current} -> {self.target}"


_JOB_TRANSITIONS: dict[JobLifecycle, frozenset[JobLifecycle]] = {
    JobLifecycle.QUEUED: frozenset(
        {JobLifecycle.ACTIVE, JobLifecycle.PAUSED, JobLifecycle.SETTLED}
    ),
    JobLifecycle.ACTIVE: frozenset(
        {JobLifecycle.WAITING, JobLifecycle.PAUSED, JobLifecycle.DRAINING, JobLifecycle.SETTLED}
    ),
    JobLifecycle.WAITING: frozenset(
        {JobLifecycle.ACTIVE, JobLifecycle.PAUSED, JobLifecycle.DRAINING, JobLifecycle.SETTLED}
    ),
    JobLifecycle.PAUSED: frozenset(
        {JobLifecycle.QUEUED, JobLifecycle.ACTIVE, JobLifecycle.SETTLED}
    ),
    JobLifecycle.DRAINING: frozenset({JobLifecycle.WAITING, JobLifecycle.SETTLED}),
    JobLifecycle.SETTLED: frozenset(),
}

_ITEM_TRANSITIONS: dict[ItemLifecycle, frozenset[ItemLifecycle]] = {
    ItemLifecycle.PENDING: frozenset(
        {ItemLifecycle.ACTIVE, ItemLifecycle.WAITING, ItemLifecycle.SETTLED}
    ),
    ItemLifecycle.ACTIVE: frozenset({ItemLifecycle.WAITING, ItemLifecycle.SETTLED}),
    ItemLifecycle.WAITING: frozenset({ItemLifecycle.ACTIVE, ItemLifecycle.SETTLED}),
    ItemLifecycle.SETTLED: frozenset(),
}

_ARTIFACT_TRANSITIONS: dict[ArtifactLifecycle, frozenset[ArtifactLifecycle]] = {
    ArtifactLifecycle.PLANNED: frozenset(
        {ArtifactLifecycle.MATERIALIZING, ArtifactLifecycle.FAILED}
    ),
    ArtifactLifecycle.MATERIALIZING: frozenset(
        {ArtifactLifecycle.PRODUCED, ArtifactLifecycle.FAILED}
    ),
    ArtifactLifecycle.PRODUCED: frozenset(
        {ArtifactLifecycle.VERIFIED, ArtifactLifecycle.FAILED}
    ),
    ArtifactLifecycle.VERIFIED: frozenset(
        {ArtifactLifecycle.COMMITTED, ArtifactLifecycle.FAILED}
    ),
    ArtifactLifecycle.COMMITTED: frozenset(),
    ArtifactLifecycle.FAILED: frozenset(),
}


def _assert_transition[T](
    entity: str,
    current: T,
    target: T,
    table: dict[T, frozenset[T]],
) -> None:
    if target not in table[current]:
        raise InvalidTransition(entity, str(current), str(target))


def assert_job_transition(current: JobLifecycle, target: JobLifecycle) -> None:
    _assert_transition("job", current, target, _JOB_TRANSITIONS)


def assert_item_transition(current: ItemLifecycle, target: ItemLifecycle) -> None:
    _assert_transition("item", current, target, _ITEM_TRANSITIONS)


def assert_artifact_transition(current: ArtifactLifecycle, target: ArtifactLifecycle) -> None:
    _assert_transition("artifact", current, target, _ARTIFACT_TRANSITIONS)
