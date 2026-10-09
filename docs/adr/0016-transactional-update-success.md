# ADR 0016 — Transactional updater success semantics

## Status
Accepted as a future Updater release contract at Gate 6.5.

## Historical trigger
V8/V9 update flows demonstrated that UI progress/helper launch could look complete while the helper
rejected the real executable or the Qt shutdown handoff failed. Filename-prefix validation and hidden
helper diagnostics made the failure appear as a successful restart with the old build still present.

## Decision
The later V10 updater uses durable phases:

`AVAILABLE -> DOWNLOADING -> VERIFYING -> STAGED -> QUIESCING -> ACTIVATING -> HEALTH_CHECK -> COMMITTING -> SUCCESS`

`FAILED` may terminate any pre-success phase. `ROLLED_BACK` is legal only after activation begins.
`SUCCESS` is impossible without `UpdateCommitEvidence` proving:

- candidate identity/hash/version path is verified;
- candidate Core starts;
- DB opens/migration is healthy;
- UI protocol is healthy;
- installed candidate self-spawns/authenticates a Worker;
- compatible Engine Pack loads;
- current capsule pointer matches the candidate;
- previous capsule remains retained for recovery.

Download 100%, staging, helper process creation or parent exit are never success evidence.

## Architecture consequence
The production update mechanism remains side-by-side immutable App Capsules selected by a stable
launcher/current pointer. In-place replacement/filename identity is not the primary safety model.
