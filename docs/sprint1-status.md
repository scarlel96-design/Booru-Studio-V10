# Sprint 1 status

## Implemented

- `CreateJobCommand` with client-scoped idempotency identity
- canonical JSON request hashing with SHA-256
- durable command receipts with original committed revision/result
- atomic Submission + Job + QueueEntry creation
- persistent queue listing after DB Actor restart
- `state_meta.state_revision` advancement exactly once per visible semantic transaction
- domain event append at the same committed revision
- changed-payload replay rejection for a reused command identity
- atomic JobRun start transaction
- Job `QUEUED -> ACTIVE` transition with pending-queue removal
- SQLite unique partial index enforcing one open Run per Job
- Core `JobService` that routes all reads/writes through the DB Actor
- Unicode path/title persistence fixtures
- concurrent create stress coverage through the bounded single-writer actor

## Deliberately not implemented yet

- queue reorder commands
- Run finish/suspend/recovery transitions
- Item/Artifact FileCommit transaction implementation
- QLocalSocket runtime or Worker authentication
- Scheduler and resource permits
- DirectHTTP or other media engines
- QML UI
- native Supervisor / packaging / updater

## Development-schema note

The V10 database remains pre-release development schema work. Sprint snapshots guarantee
restart persistence within the snapshot being tested; cross-sprint database migration is
not yet a production compatibility promise. Formal migration fixtures become mandatory
when the schema is frozen for the first compatibility boundary.
