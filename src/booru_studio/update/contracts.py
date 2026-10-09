from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UpdatePhase(StrEnum):
    AVAILABLE = "AVAILABLE"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    STAGED = "STAGED"
    QUIESCING = "QUIESCING"
    ACTIVATING = "ACTIVATING"
    HEALTH_CHECK = "HEALTH_CHECK"
    COMMITTING = "COMMITTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True, slots=True)
class CandidateHealthReport:
    identity_verified: bool
    core_started: bool
    database_opened: bool
    ui_protocol_healthy: bool
    worker_self_spawn_healthy: bool
    engine_pack_loaded: bool
    migration_healthy: bool

    @property
    def healthy(self) -> bool:
        return all((
            self.identity_verified,
            self.core_started,
            self.database_opened,
            self.ui_protocol_healthy,
            self.worker_self_spawn_healthy,
            self.engine_pack_loaded,
            self.migration_healthy,
        ))


@dataclass(frozen=True, slots=True)
class UpdateCommitEvidence:
    candidate_health: CandidateHealthReport
    current_pointer_matches_candidate: bool
    previous_capsule_retained: bool

    @property
    def sufficient_for_success(self) -> bool:
        return (
            self.candidate_health.healthy
            and self.current_pointer_matches_candidate
            and self.previous_capsule_retained
        )


_NORMAL_TRANSITIONS: dict[UpdatePhase, frozenset[UpdatePhase]] = {
    UpdatePhase.AVAILABLE: frozenset({UpdatePhase.DOWNLOADING}),
    UpdatePhase.DOWNLOADING: frozenset({UpdatePhase.VERIFYING}),
    UpdatePhase.VERIFYING: frozenset({UpdatePhase.STAGED}),
    UpdatePhase.STAGED: frozenset({UpdatePhase.QUIESCING}),
    UpdatePhase.QUIESCING: frozenset({UpdatePhase.ACTIVATING}),
    UpdatePhase.ACTIVATING: frozenset({UpdatePhase.HEALTH_CHECK}),
    UpdatePhase.HEALTH_CHECK: frozenset({UpdatePhase.COMMITTING}),
    UpdatePhase.COMMITTING: frozenset({UpdatePhase.SUCCESS}),
    UpdatePhase.SUCCESS: frozenset(),
    UpdatePhase.FAILED: frozenset(),
    UpdatePhase.ROLLED_BACK: frozenset(),
}


def validate_update_transition(
    previous: UpdatePhase,
    target: UpdatePhase,
    *,
    candidate_health: CandidateHealthReport | None = None,
    evidence: UpdateCommitEvidence | None = None,
) -> None:
    """Validate one durable updater state transition.

    Failure is legal from every non-terminal pre-success phase.  Rollback is legal only after the
    candidate may have been activated.  ``SUCCESS`` requires concrete candidate health and pointer
    evidence; download progress or a helper launch can never satisfy this contract.
    """

    if previous in {UpdatePhase.SUCCESS, UpdatePhase.FAILED, UpdatePhase.ROLLED_BACK}:
        raise ValueError("terminal update phase cannot transition")
    if target is UpdatePhase.FAILED:
        return
    if target is UpdatePhase.ROLLED_BACK:
        if previous not in {
            UpdatePhase.ACTIVATING,
            UpdatePhase.HEALTH_CHECK,
            UpdatePhase.COMMITTING,
        }:
            raise ValueError("rollback is only valid after candidate activation begins")
        return
    if target not in _NORMAL_TRANSITIONS[previous]:
        raise ValueError(f"illegal update transition: {previous.value} -> {target.value}")
    if previous is UpdatePhase.HEALTH_CHECK and target is UpdatePhase.COMMITTING:
        if candidate_health is None or not candidate_health.healthy:
            raise ValueError("COMMITTING requires a healthy installed candidate")
    if target is UpdatePhase.SUCCESS:
        if evidence is None or not evidence.sufficient_for_success:
            raise ValueError("update SUCCESS requires healthy candidate and committed pointer evidence")
