# ADR 0021 — Pause/Cancel become authoritative only after Worker observation

## Status
Accepted in Sprint 10.

## Context
Sprint 9 made Pause/Cancel durable UI-Core commands, but an active Job cannot be reported as actually
paused/cancelled merely because the button press was committed. The Worker may still be transferring or
crossing a file-commit boundary.

## Decision
For an active Run:

1. UI/Core commits `PAUSE_REQUESTED` or `CANCEL_REQUESTED` durably and idempotently.
2. Core polls the authoritative Job intent and forwards it over the authenticated Core-Worker control lane.
3. Worker acknowledges receipt but continues only to a safe checkpoint.
4. Worker commits `PAUSE_OBSERVED` or `CANCEL_OBSERVED` through the durable Worker transaction lane.
5. The Worker transaction receipt and Job/Run transition commit in the same SQLite transaction.

`CANCEL_REQUESTED` supersedes an earlier pause. A staged transfer is registered as resumable before the
Core decides whether to grant FileCommit. If Pause/Cancel is pending, `FILE_COMMIT_GRANT` is withheld and
the staged bytes remain app-owned recovery/resume state. Once a FileCommitGrant has been issued, Core
does not inject control until that irreversible commit handshake reaches its next checkpoint.

## Consequences
- UI intent and actual execution state cannot be conflated.
- pause preserves resumable staging without promoting a final file after the durable request;
- cancel settles the observed Run/Job atomically;
- source E2E tests cover active pause, active cancel and the TRANSFER_STAGED→FileCommitGrant fence.
