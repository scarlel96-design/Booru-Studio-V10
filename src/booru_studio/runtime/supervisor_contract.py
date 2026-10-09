from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CoreHealth(StrEnum):
    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    UNRESPONSIVE = "UNRESPONSIVE"
    RESUME_GRACE = "RESUME_GRACE"


@dataclass(frozen=True, slots=True)
class SupervisorLeasePolicy:
    suspect_after_ms: int = 8_000
    unresponsive_after_ms: int = 20_000
    resume_grace_ms: int = 12_000

    def __post_init__(self) -> None:
        if self.suspect_after_ms <= 0:
            raise ValueError("suspect_after_ms must be positive")
        if self.unresponsive_after_ms <= self.suspect_after_ms:
            raise ValueError("unresponsive_after_ms must exceed suspect_after_ms")
        if self.resume_grace_ms <= 0:
            raise ValueError("resume_grace_ms must be positive")


class SupervisorLeaseTracker:
    """Pure lease/fencing model; elapsed_ms must exclude system sleep on Windows.

    The native Supervisor uses QueryUnbiasedInterruptTime so a long suspend does not look like a
    Core hang. A power epoch still fences stale heartbeat/Worker admission after resume.
    """

    def __init__(self, policy: SupervisorLeasePolicy | None = None) -> None:
        self.policy = policy or SupervisorLeasePolicy()
        self.power_epoch = 0
        self._last_heartbeat_ms: int | None = None
        self._resume_started_ms: int | None = None

    def heartbeat(self, *, elapsed_ms: int, power_epoch: int) -> None:
        if power_epoch != self.power_epoch:
            raise ValueError("stale or future power epoch heartbeat")
        if self._last_heartbeat_ms is not None and elapsed_ms < self._last_heartbeat_ms:
            raise ValueError("elapsed time cannot move backwards")
        self._last_heartbeat_ms = elapsed_ms
        self._resume_started_ms = None

    def resume(self, *, elapsed_ms: int) -> int:
        self.power_epoch += 1
        self._last_heartbeat_ms = None
        self._resume_started_ms = elapsed_ms
        return self.power_epoch

    def evaluate(self, *, elapsed_ms: int, process_alive: bool, health_probe_ok: bool) -> CoreHealth:
        if not process_alive:
            return CoreHealth.UNRESPONSIVE
        if self._resume_started_ms is not None:
            if elapsed_ms - self._resume_started_ms <= self.policy.resume_grace_ms:
                return CoreHealth.RESUME_GRACE
        if self._last_heartbeat_ms is None:
            return CoreHealth.SUSPECT
        age = elapsed_ms - self._last_heartbeat_ms
        if age < 0:
            raise ValueError("elapsed time cannot move backwards")
        if age < self.policy.suspect_after_ms:
            return CoreHealth.HEALTHY
        if age < self.policy.unresponsive_after_ms:
            return CoreHealth.SUSPECT
        return CoreHealth.SUSPECT if health_probe_ok else CoreHealth.UNRESPONSIVE


@dataclass(slots=True)
class WorkerLeaseFence:
    """Prevents new Worker operation admission under a stale Core/power epoch."""

    power_epoch: int = 0
    core_lease_epoch: int = 0
    fresh: bool = False

    def on_power_resume(self, new_power_epoch: int) -> None:
        if new_power_epoch <= self.power_epoch:
            raise ValueError("power epoch must increase")
        self.power_epoch = new_power_epoch
        self.fresh = False

    def accept_core_lease(self, *, power_epoch: int, core_lease_epoch: int) -> None:
        if power_epoch != self.power_epoch:
            raise ValueError("Core lease is from a stale power epoch")
        if core_lease_epoch <= self.core_lease_epoch:
            raise ValueError("Core lease epoch must increase")
        self.core_lease_epoch = core_lease_epoch
        self.fresh = True

    @property
    def may_admit_new_operation(self) -> bool:
        return self.fresh
