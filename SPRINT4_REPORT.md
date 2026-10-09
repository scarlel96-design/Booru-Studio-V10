# Booru Studio V10 — Sprint 4 Implementation & Seal Report

## Scope

Sprint 4 is the first cumulative V10 slice that performs actual network transfers. It extends the
sealed Sprint 3 repository rather than creating a separate program.

Implemented path:

```text
Core
  -> authenticated Worker process
  -> Worker Control Plane / DirectHTTP Execution Plane
  -> bounded ParallelTransferScheduler
  -> global + host network admission
  -> application-owned staging + resume sidecar
  -> durable TRANSFER_STAGED tx
  -> Core PREPARED FileCommitIntent
  -> Worker granted filesystem commit
  -> Core independent final verification
  -> COMMITTED Artifact/FileRecord
```

## Implemented components

### Scheduler

- `TransferPermitPool` with ACTIVE / DRAINING / RELEASED states.
- Hard capacity cannot be exceeded under contention.
- Shrinking a capacity never silently re-promotes an already-draining permit.
- `ParallelTransferScheduler` uses a bounded rolling queue and independent worker-local resources.
- Worker-factory failure cancels/fails queued work rather than silently losing a consumer.
- Actual network active/peak instrumentation is separate from configured parallelism.

### Network policy

- `HostAdaptiveLimiter` with conservative reset tolerance, repeated-reset reduction and gradual
  recovery.
- Nested exception-chain transient network classification including Windows-style reset codes.
- Bounded exponential retry/jitter policy.
- Core-side durable RateLimitGate and RetryEpisode persistence helpers.

The immediate Sprint 4 DirectHTTP request loop still owns its short request-level retry. Full
Worker->Core durable 429/retry policy feedback across Run restarts remains deliberately deferred.

### DirectHTTP

- One Requests Session per scheduler worker.
- Ambient `.netrc` credential injection disabled.
- Generic secret/hop-by-hop task headers stripped.
- Identity transfer encoding for byte-accurate resume semantics.
- Range/If-Range resume using a durable resume sidecar and usable validator.
- 206 Content-Range/validator validation.
- 200 after attempted resume safely replaces stale application-owned partial instead of appending.
- 416 protocol-clean reset/retry path.
- bounded 429 / 408 / 425 / 5xx / transient connection retry behavior.
- expected size and optional SHA-256 verification.
- network execution never writes directly to final destination path.

### Resume hardening

- If the `.part` is ahead of the last durable sidecar after a crash, recovery truncates safely to
  the last durable checkpoint.
- If the partial is shorter than its checkpoint, resume is rejected.
- Stale regular `.resume.json.tmp` files from a prior interrupted atomic sidecar write can be
  removed and replaced; non-regular/symlink temporary paths are rejected.

### Worker/Core integration

- START_RUN accepts a bounded generic `DIRECT_HTTP` execution plan.
- Worker IPC/control thread does not execute blocking Requests calls.
- Blocking network work runs in `DirectHttpExecutionPlane`.
- Completed transfers are emitted progressively through a bounded in-process queue.
- Core durably commits `TRANSFER_STAGED` before issuing a FileCommit grant.
- Core independently reads/registers resume information before PREPARED.
- Worker performs only a granted filesystem commit.
- Core independently verifies/finalizes the result before FILE_COMMIT_ACK.
- ResumeRecord is removed from SQLite at durable final commit; filesystem sidecar is removed only
  after ACK.
- Control-plane Cancel remains observable while a slow HTTP body is being read in the execution
  plane.

## Cumulative validation

Final pre-seal source validation:

```text
python -m compileall -q src tests     PASS
pytest -q                             117 passed
```

Architecture import-boundary tests confirm:

- Core does not import Requests or concrete engine adapters;
- Domain does not import Requests/concrete engines/framework/storage layers;
- UI does not import storage/Worker/concrete engine implementations.

`ruff` and `mypy` are declared as development dependencies but are not installed in this isolated
execution environment, so no successful lint/type-check claim is made here.

## Deterministic network tests

The local `ThreadingHTTPServer` fixture implements normal, slow, Range, validator-change, 429,
transport-reset and related paths.

Validated behaviors include:

1. **True parallel transfer**
   - 20 files;
   - configured/global capacity 10;
   - delayed requests overlap;
   - scheduler hard peak never exceeds 10;
   - release fixture expects observed peak >= 9;
   - all 20 results are independently committed through Sprint 2 FileCommit;
   - SQLite final state: 20 COMMITTED Artifacts, 20 FileRecords, 0 nonterminal commit intents,
     `integrity_check=ok`.

2. **Concurrency regression repeat**
   - the parallel + real Worker network E2E pair was repeated five consecutive rounds after
     increasing only the test server listen backlog;
   - all five rounds passed;
   - this avoids treating the stdlib TCP listen backlog as application serialization.

3. **Resume**
   - 4 MiB object with a durable 1 MiB local checkpoint;
   - exact Range + If-Range request observed;
   - checkpoint bytes reused;
   - final content/SHA exact.

4. **Source changed while resuming**
   - old validator + stale partial;
   - server returns a fresh full 200 representation;
   - stale partial is overwritten, never appended;
   - result reports zero actually reused bytes.

5. **HTTP 429**
   - first response 429 with bounded Retry-After;
   - second response succeeds;
   - transfer reports two attempts.

6. **Transport reset**
   - first connection deliberately closes;
   - transient classifier/adaptive limiter receives failure evidence;
   - bounded retry succeeds.

7. **Cancellation**
   - active slow transfer is cancelled;
   - no final file is promoted;
   - recoverable partial may remain in application staging.

8. **Real Worker subprocess DirectHTTP E2E**
   - real Python Worker process launched through the Sprint 3 private bootstrap/auth source path;
   - eight files executed at configured parallelism 4;
   - actual peak network activity reaches 4 in the deterministic fixture;
   - Worker durable transactions and Core FileCommit messages complete over the framed IPC
     harness;
   - final files match expected content;
   - WorkerSession reaches CLOSED and SQLite integrity is OK.

9. **Control-plane responsiveness**
   - Worker starts a deliberately slow DirectHTTP transfer on the execution plane;
   - Core sends CANCEL_RUN while blocking network I/O is active;
   - control plane returns Cancel acknowledgment/observation and exits cleanly;
   - no final file is committed.

10. **Durable network state helpers**
    - RateLimitGate survives service/DB Actor recreation;
    - RetryEpisode count/EXHAUSTED state survives service recreation.

## Test-fixture defect discovered during sealing

A repeated concurrency run once observed server peak 8 although the scheduler had admitted more
work. The cause was the Python stdlib TCPServer default listen backlog, not the V10 scheduler.
The release fixture now uses a dedicated test HTTP server with `request_queue_size = 64`, keeping
its network accept queue out of the measured bottleneck. Five consecutive repeat rounds then
passed. The hard application invariant remains `actual in-flight <= granted capacity`.

## Validation boundary / non-claims

This Sprint was validated in Linux with CPython 3.13, deterministic local HTTP, SQLite/filesystem
and a real Python Worker subprocess through the explicit source stdio transport.

It does **not** establish that the following J.2 Windows gates have passed:

- QLocalServer/QLocalSocket runtime and ACL behavior;
- STARTUPINFOEX inherited-HANDLE behavior;
- Frozen PyInstaller Worker resolution;
- Windows Job Object/native Supervisor containment;
- Windows NTFS/reparse edge behavior;
- Windows sleep/resume;
- installer/updater/Engine Pack packaging.

Also not implemented in Sprint 4:

- gallery-dl;
- yt-dlp;
- FFmpeg;
- Browser Assist;
- QML UI;
- exact bandwidth governor;
- complete cross-Run Core orchestration of durable retry/rate-limit feedback.

## Seal condition

Sprint 4 is ready to seal only after:

1. source caches are removed;
2. `SOURCE_MANIFEST.sha256` is regenerated from the final cumulative repository;
3. the complete Sprint 0–4 repository is archived;
4. archive SHA-256 is generated;
5. the archive is extracted into a clean directory;
6. source manifest is independently verified there;
7. `compileall` and all 117 tests pass on the extracted snapshot.

The external seal report records the outcome of those final steps.
