# Booru Studio V10 — Sprint 1 Implementation Report

## Scope completed

Sprint 1 builds directly on the complete Sprint 0 repository; it is not a detached patch.
The cumulative repository now implements the first durable application workflow.

Implemented:

1. Canonical JSON serialization/hash helper for durable command identity.
2. `CommandIdentity`, `CreateJobCommand`, `CreateJobResult` and JobRun request/result types.
3. Persistent Queue domain projection types.
4. Repository layer for Submission, Job, Queue, JobRun, command receipt and revision/event state.
5. Explicit `BEGIN IMMEDIATE` semantic write-transaction helper.
6. Atomic replay-safe `CREATE_JOB` transaction.
7. Request SHA-256 stored with command receipt; changed-payload command replay is rejected.
8. Submission + Job + QueueEntry + state revision + event + receipt commit atomically.
9. Atomic JobRun start transaction.
10. Job activation and queue removal occur in the same transaction as Run creation.
11. SQLite partial unique index prevents multiple open Runs for one Job.
12. Core `JobService` routes application reads/writes through the bounded DB Actor.
13. Storage target ID/generation domain invariant aligned with the SQLite constraint.
14. Restart/replay/rollback/concurrency integration tests.
15. Sprint 1 ADR/status/architecture documentation and version bump to `10.0.0.dev1`.

## Local validation performed

- `python -m compileall -q src tests`: PASS
- `pytest -q`: **33 passed**
- Sprint 0 regression suite: PASS as part of the same test run
- Unicode SQLite/database and JobRun payload fixtures: PASS
- durable queue after DB Actor restart: PASS
- lost-response command replay after restart: PASS
- changed-payload idempotency-key collision rejection: PASS
- failed create transaction leaves receipt/revision/queue unchanged: PASS
- one-open-Run-per-Job database constraint: PASS
- concurrent 64-command regression test: PASS; 64 unique Jobs, queue entries and sequential revisions
- additional 1,000-command concurrent stress run: PASS; `state_revision=1000`, queue size 1000, SQLite `integrity_check=ok`

## Correctness properties demonstrated in Sprint 1

- A committed `CREATE_JOB` response can be lost and safely replayed without duplicate Job creation.
- Replaying the same command does not increment `state_revision` again.
- A command identity cannot silently refer to a different payload.
- Job start cannot leave an ACTIVE Job and pending queue entry through a partial successful transaction.
- Job/Queue/Run data survives closing and reopening the DB Actor.

## Validation not claimed

This snapshot has not yet performed:

- Windows Frozen EXE E2E
- QLocalSocket runtime tests
- actual Worker spawn/authentication
- actual download or FileCommit filesystem mutation
- Scheduler concurrency/resource tests
- Windows Job Object/Supervisor tests
- updater/rollback tests

Those are later milestones and must not be inferred from the Sprint 1 source tests.

## Development-schema compatibility

The database is still a pre-release development schema. Sprint 1 validates restart
persistence for databases created by this snapshot. Cross-sprint schema migration is not
yet declared a production compatibility contract; that becomes a hard requirement once
the migration boundary is frozen.

## Environment limitation

`uv.lock` is still pending because this execution environment does not provide the
networked dependency-resolution workflow required to create and verify it. No fabricated
lockfile is included. `tools/bootstrap_dev.ps1` remains the intended Windows bootstrap.
