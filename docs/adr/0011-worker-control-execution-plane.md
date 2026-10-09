# ADR 0011 — Separate Worker Control and Execution planes

## Status

Accepted for V10 Sprint 4.

## Context

Running blocking Requests/gallery/media engine calls directly on the Worker IPC loop would prevent
Cancel, heartbeat, resource and transaction messages from being handled while the engine blocks.

## Decision

The Worker main/control thread owns the Core↔Worker connection. Blocking execution runs in a
separate execution thread/pool. The execution plane never reads IPC. Completed transfer results
cross a bounded in-process queue to the control plane, which performs the durable transaction and
FileCommit protocol.

For DirectHTTP the sequence is:

1. execution plane produces a staging result;
2. control plane sends durable `TRANSFER_STAGED` and waits for cumulative ACK;
3. Core independently registers the sidecar and creates PREPARED FileCommitIntent;
4. Core sends FILE_COMMIT_GRANT;
5. Worker performs only the granted filesystem operation and returns FILE_COMMIT_RESULT;
6. Core independently verifies/finalizes and returns FILE_COMMIT_ACK;
7. Worker removes the obsolete resume sidecar only after ACK.

Cancel is checked by the control plane before starting a new irreversible commit boundary.

## Consequences

- network/engine blocking cannot normally starve the Worker IPC loop;
- Core remains authority for durable state and FileCommit;
- already granted commit finalization is not destructively undone by a later Cancel;
- pathological interpreter/native hangs are still a later Supervisor/heartbeat containment concern.
