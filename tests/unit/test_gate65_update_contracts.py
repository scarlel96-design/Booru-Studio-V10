from __future__ import annotations

import pytest

from booru_studio.reliability.release_gates import GATE65_SCENARIOS, validate_gate65_matrix
from booru_studio.update.contracts import (
    CandidateHealthReport,
    UpdateCommitEvidence,
    UpdatePhase,
    validate_update_transition,
)


def _healthy() -> CandidateHealthReport:
    return CandidateHealthReport(
        identity_verified=True,
        core_started=True,
        database_opened=True,
        ui_protocol_healthy=True,
        worker_self_spawn_healthy=True,
        engine_pack_loaded=True,
        migration_healthy=True,
    )


def test_update_success_requires_candidate_health_and_pointer_commit() -> None:
    validate_update_transition(UpdatePhase.AVAILABLE, UpdatePhase.DOWNLOADING)
    validate_update_transition(UpdatePhase.DOWNLOADING, UpdatePhase.VERIFYING)
    validate_update_transition(UpdatePhase.VERIFYING, UpdatePhase.STAGED)
    validate_update_transition(UpdatePhase.STAGED, UpdatePhase.QUIESCING)
    validate_update_transition(UpdatePhase.QUIESCING, UpdatePhase.ACTIVATING)
    validate_update_transition(UpdatePhase.ACTIVATING, UpdatePhase.HEALTH_CHECK)
    validate_update_transition(UpdatePhase.HEALTH_CHECK, UpdatePhase.COMMITTING, candidate_health=_healthy())

    with pytest.raises(ValueError, match="SUCCESS"):
        validate_update_transition(UpdatePhase.COMMITTING, UpdatePhase.SUCCESS)

    incomplete = UpdateCommitEvidence(
        candidate_health=_healthy(),
        current_pointer_matches_candidate=False,
        previous_capsule_retained=True,
    )
    with pytest.raises(ValueError, match="SUCCESS"):
        validate_update_transition(
            UpdatePhase.COMMITTING,
            UpdatePhase.SUCCESS,
            evidence=incomplete,
        )

    complete = UpdateCommitEvidence(
        candidate_health=_healthy(),
        current_pointer_matches_candidate=True,
        previous_capsule_retained=True,
    )
    validate_update_transition(UpdatePhase.COMMITTING, UpdatePhase.SUCCESS, evidence=complete)


def test_progress_or_staging_can_never_skip_to_success() -> None:
    evidence = UpdateCommitEvidence(_healthy(), True, True)
    for phase in (
        UpdatePhase.DOWNLOADING,
        UpdatePhase.VERIFYING,
        UpdatePhase.STAGED,
        UpdatePhase.QUIESCING,
        UpdatePhase.ACTIVATING,
        UpdatePhase.HEALTH_CHECK,
    ):
        with pytest.raises(ValueError):
            validate_update_transition(phase, UpdatePhase.SUCCESS, evidence=evidence)


def test_rollback_is_only_legal_after_candidate_activation_begins() -> None:
    with pytest.raises(ValueError, match="rollback"):
        validate_update_transition(UpdatePhase.STAGED, UpdatePhase.ROLLED_BACK)
    validate_update_transition(UpdatePhase.ACTIVATING, UpdatePhase.ROLLED_BACK)
    validate_update_transition(UpdatePhase.HEALTH_CHECK, UpdatePhase.ROLLED_BACK)
    validate_update_transition(UpdatePhase.COMMITTING, UpdatePhase.ROLLED_BACK)


def test_unhealthy_candidate_can_never_commit_success() -> None:
    health = CandidateHealthReport(
        identity_verified=True,
        core_started=True,
        database_opened=True,
        ui_protocol_healthy=True,
        worker_self_spawn_healthy=False,
        engine_pack_loaded=True,
        migration_healthy=True,
    )
    evidence = UpdateCommitEvidence(health, True, True)
    assert health.healthy is False
    with pytest.raises(ValueError, match="SUCCESS"):
        validate_update_transition(UpdatePhase.COMMITTING, UpdatePhase.SUCCESS, evidence=evidence)


def test_gate65_release_matrix_is_unique_and_covers_v9_update_regressions() -> None:
    validate_gate65_matrix()
    ids = {scenario.scenario_id for scenario in GATE65_SCENARIOS}
    assert {
        "G65-UPD-100PCT-NOT-SUCCESS",
        "G65-UPD-CANDIDATE-KILL",
        "G65-UPD-FILENAME-INDEPENDENT",
        "G65-UPD-HELPER-DIAGNOSTIC",
        "G65-FROZEN-WORKER-SPAWN",
        "G65-WIN-JOB-KILL",
    } <= ids

def test_health_check_cannot_advance_to_committing_when_candidate_is_unhealthy() -> None:
    unhealthy = CandidateHealthReport(
        identity_verified=True, core_started=True, database_opened=True,
        ui_protocol_healthy=True, worker_self_spawn_healthy=False,
        engine_pack_loaded=True, migration_healthy=True,
    )
    with pytest.raises(ValueError, match="COMMITTING"):
        validate_update_transition(
            UpdatePhase.HEALTH_CHECK, UpdatePhase.COMMITTING, candidate_health=unhealthy
        )

