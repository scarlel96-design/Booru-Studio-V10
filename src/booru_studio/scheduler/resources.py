from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum


class PermitState(StrEnum):
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class PermitSnapshot:
    target_capacity: int
    issued: int
    active: int
    draining: int
    peak_issued: int


class TransferPermit:
    __slots__ = ("_pool", "permit_id", "_released")

    def __init__(self, pool: "TransferPermitPool", permit_id: int) -> None:
        self._pool = pool
        self.permit_id = permit_id
        self._released = False

    @property
    def state(self) -> PermitState:
        return self._pool.state_of(self.permit_id)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._pool.release(self.permit_id)

    def __enter__(self) -> "TransferPermit":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class TransferPermitPool:
    """Hard-cap transfer permits with safe shrink/drain semantics.

    A capacity decrease never makes already-issued capacity magically reusable.
    Existing permits above the new target become DRAINING and remain counted until
    their owners release them. New permits are admitted only when total issued is
    strictly below the current target.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._target = int(capacity)
        self._condition = threading.Condition()
        self._next_id = 1
        self._states: dict[int, PermitState] = {}
        self._peak_issued = 0

    @property
    def capacity(self) -> int:
        with self._condition:
            return self._target

    def snapshot(self) -> PermitSnapshot:
        with self._condition:
            values = tuple(self._states.values())
            active = sum(1 for state in values if state is PermitState.ACTIVE)
            draining = sum(1 for state in values if state is PermitState.DRAINING)
            return PermitSnapshot(
                target_capacity=self._target,
                issued=active + draining,
                active=active,
                draining=draining,
                peak_issued=self._peak_issued,
            )

    def state_of(self, permit_id: int) -> PermitState:
        with self._condition:
            return self._states.get(permit_id, PermitState.RELEASED)

    def resize(self, capacity: int) -> PermitSnapshot:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        with self._condition:
            self._target = int(capacity)
            self._rebalance_locked()
            self._condition.notify_all()
            return self.snapshot()

    def _rebalance_locked(self) -> None:
        # DRAINING is monotonic for an issued lease: once the coordinator has
        # asked an owner to drain, a later unrelated release must not silently
        # reactivate that lease. Shrinks only add more draining leases.
        issued_ids = sorted(self._states)
        desired_draining = max(0, len(issued_ids) - self._target)
        current_draining = sum(
            1 for state in self._states.values() if state is PermitState.DRAINING
        )
        to_mark = max(0, desired_draining - current_draining)
        if to_mark:
            candidates = [
                permit_id for permit_id in reversed(issued_ids)
                if self._states[permit_id] is PermitState.ACTIVE
            ]
            for permit_id in candidates[:to_mark]:
                self._states[permit_id] = PermitState.DRAINING

    def acquire(
        self,
        cancel_event: threading.Event | None = None,
        *,
        poll_interval_s: float = 0.05,
        timeout_s: float | None = None,
    ) -> TransferPermit:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be positive")
        deadline = None if timeout_s is None else time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while len(self._states) >= self._target:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("permit acquisition cancelled")
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("permit acquisition timed out")
                    wait_for = min(poll_interval_s, remaining)
                else:
                    wait_for = poll_interval_s
                self._condition.wait(wait_for)
            permit_id = self._next_id
            self._next_id += 1
            self._states[permit_id] = PermitState.ACTIVE
            self._peak_issued = max(self._peak_issued, len(self._states))
            return TransferPermit(self, permit_id)

    def release(self, permit_id: int) -> None:
        with self._condition:
            if permit_id not in self._states:
                return
            del self._states[permit_id]
            self._condition.notify_all()
