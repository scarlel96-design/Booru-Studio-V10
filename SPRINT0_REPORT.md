# Booru Studio V10 — Sprint 0 Implementation Report

## Scope completed

Sprint 0 established the first code-level contract layer for the A.4–J.2 design baseline.

Implemented:

1. Python package/repository structure.
2. Opaque UUID-backed IDs.
3. UTC/monotonic Clock abstraction.
4. Deterministic RandomSource abstraction.
5. Normalized ErrorCode / ErrorConfidence / ErrorInstance.
6. Domain enums and entities for Submission, Job, JobRun, Item, Artifact.
7. Transition guards and domain invariants.
8. SQLite schema v1 skeleton with WAL/FULL/foreign-key/STRICT rules.
9. Composite StorageTargetId + generation persistence boundary.
10. Bounded single-writer DB Actor.
11. IPC protocol-family/plane/version envelope types.
12. 4-byte big-endian length-prefixed UTF-8 JSON framing primitive.
13. Engine adapter contract types, capabilities and TransferDescriptor.
14. Architecture import-boundary tests.
15. Initial ADRs and architecture documentation.
16. PowerShell bootstrap/QA scripts for a Windows development environment.

## Local validation performed

- `python -m compileall -q src tests`: PASS
- `pytest -q`: **22 passed**
- SQLite schema creation: PASS
- Unicode SQLite path fixture: PASS
- StorageTarget generation foreign-key guard: PASS
- IPC split/multiple frame decoding: PASS
- Architecture dependency boundary checks: PASS

## Validation not claimed

This Sprint 0 artifact has **not** yet performed:

- Windows Frozen EXE E2E
- QLocalSocket runtime tests
- actual Worker spawn/authentication
- actual media transfer
- Scheduler concurrency tests
- Windows Job Object/Supervisor tests
- updater/rollback tests

Those belong to later milestones.

## Environment limitation

`uv lock` could not be generated in the current execution environment because external package-index DNS/network access is unavailable. The repository intentionally does not contain a fabricated lockfile. Run `tools/bootstrap_dev.ps1` on the network-enabled Windows development machine to generate `uv.lock` and install the development environment.
