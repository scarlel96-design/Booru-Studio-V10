from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GateArea(StrEnum):
    ENGINE = "ENGINE"
    WINDOWS_IPC = "WINDOWS_IPC"
    PROCESS = "PROCESS"
    FROZEN_RUNTIME = "FROZEN_RUNTIME"
    UPDATE = "UPDATE"
    MIGRATION = "MIGRATION"


@dataclass(frozen=True, slots=True)
class ReleaseGateScenario:
    scenario_id: str
    area: GateArea
    expected_invariant: str

    def __post_init__(self) -> None:
        if not self.scenario_id.startswith("G65-"):
            raise ValueError("Gate 6.5 scenario IDs must start with G65-")
        if not self.expected_invariant.strip():
            raise ValueError("release gate invariant cannot be empty")


GATE65_SCENARIOS: tuple[ReleaseGateScenario, ...] = (
    ReleaseGateScenario("G65-ENG-RETRY-COMPOUND", GateArea.ENGINE, "compound attempt ceiling is never exceeded"),
    ReleaseGateScenario("G65-ENG-SECRET-DURABILITY", GateArea.ENGINE, "signed URLs and credential material are never durable state"),
    ReleaseGateScenario("G65-WIN-IPC-SAME-USER", GateArea.WINDOWS_IPC, "QLocal endpoint rejects cross-user access"),
    ReleaseGateScenario("G65-WIN-IPC-BOOTSTRAP", GateArea.WINDOWS_IPC, "stale endpoint knowledge cannot authenticate a new session"),
    ReleaseGateScenario("G65-WIN-JOB-KILL", GateArea.PROCESS, "Supervisor shutdown leaves no Worker or engine child orphan"),
    ReleaseGateScenario("G65-FROZEN-QML-LOAD", GateArea.FROZEN_RUNTIME, "installed frozen UI loads QML and Qt plugins"),
    ReleaseGateScenario("G65-FROZEN-WORKER-SPAWN", GateArea.FROZEN_RUNTIME, "installed candidate can self-spawn and authenticate a Worker"),
    ReleaseGateScenario("G65-UPD-100PCT-NOT-SUCCESS", GateArea.UPDATE, "download 100 percent is not update success"),
    ReleaseGateScenario("G65-UPD-CANDIDATE-KILL", GateArea.UPDATE, "candidate crash preserves or restores previous capsule"),
    ReleaseGateScenario("G65-UPD-REPLAY", GateArea.UPDATE, "valid but stale signed metadata cannot roll the product back"),
    ReleaseGateScenario("G65-UPD-FILENAME-INDEPENDENT", GateArea.UPDATE, "executable filename is not product identity"),
    ReleaseGateScenario("G65-UPD-HELPER-DIAGNOSTIC", GateArea.UPDATE, "updater failure remains durably diagnosable after restart"),
    ReleaseGateScenario("G65-MIGRATION-FAIL", GateArea.MIGRATION, "failed migration does not destroy the last bootable capsule or user database"),
)


def validate_gate65_matrix() -> None:
    ids = [scenario.scenario_id for scenario in GATE65_SCENARIOS]
    if len(ids) != len(set(ids)):
        raise ValueError("Gate 6.5 scenario IDs must be unique")
