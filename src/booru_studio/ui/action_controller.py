from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActionState:
    can_submit: bool
    can_cancel: bool
    can_pause: bool = False
    can_resume: bool = False
    reason: str | None = None


class ActionController:
    """Combines synchronization, lifecycle and pending-command state for UI actions."""

    @staticmethod
    def evaluate(*, connected: bool, stale: bool, pending_command: bool, selected_lifecycle: str | None) -> ActionState:
        if not connected:
            return ActionState(False, False, reason="CORE_DISCONNECTED")
        if stale:
            return ActionState(False, False, reason="PROJECTION_STALE")
        if pending_command:
            return ActionState(False, False, reason="COMMAND_PENDING")
        can_cancel = selected_lifecycle in {"QUEUED", "ACTIVE", "WAITING", "PAUSED", "DRAINING"}
        can_pause = selected_lifecycle in {"QUEUED", "ACTIVE", "WAITING"}
        can_resume = selected_lifecycle == "PAUSED"
        return ActionState(True, can_cancel, can_pause, can_resume, None)
