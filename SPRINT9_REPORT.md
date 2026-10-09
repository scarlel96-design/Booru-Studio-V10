# Booru Studio V10 — Sprint 9 UI/UX Product Refinement Report

## Result
**SOURCE SCOPE COMPLETE pending final archive seal.**

## Scope completed
- added idempotent UI/Core `PAUSE_JOB`, `RESUME_JOB` and `MOVE_QUEUE_JOB` command paths;
- queued pause/resume semantics preserve durable FIFO behavior and state revisions;
- queue reordering preserves `UNIQUE(sort_key)` by using a disjoint temporary key space inside one transaction;
- projection now exposes a latest committed file path and latest bounded operation error/native code;
- added safe platform file-open and reveal actions with missing-file fail-closed behavior;
- upgraded JobCard to kind/phase/wait/bytes/files/error presentation with pause/resume/cancel/file actions;
- postprocess/verify/reconcile remain indeterminate-active after transfer reaches 100%, avoiding the old "100% but frozen" UX;
- added right-click Open/Show in folder menu and Queue up/down controls;
- expanded KO/EN catalogs with exact parity;
- updated the Windows offscreen QML smoke controller for every new QML-visible slot.

## Preserved boundaries
- QML still consumes Core projections and commands; it does not import SQLite, Workers or concrete engines.
- Running-job pause is a durable intent, not a false claim that a Worker has already checkpointed.
- File paths are projected only from committed `file_records`; missing paths are not delegated to the OS shell.
- No raw signed source URL/cookie/header is added to the UI projection.

## Verification
Final cumulative and clean-room counts are recorded in the seal report.
