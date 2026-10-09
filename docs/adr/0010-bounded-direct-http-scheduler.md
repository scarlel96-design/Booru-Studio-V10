# ADR 0010 — Bounded DirectHTTP scheduler

## Status

Accepted for V10 Sprint 4.

## Decision

Keep the proven V9 custom DirectHTTP concurrency approach, but place it behind a bounded V10
scheduler/resource contract instead of replacing it with a generic external downloader.

Each scheduler worker owns one Requests Session. Tasks enter a bounded queue and must hold a hard
global network permit plus a per-host adaptive lease while the request is in flight. Capacity
shrink marks already-issued surplus permits DRAINING; they are not reallocated before release.

Range resume is permitted only with a durable sidecar and a usable If-Range validator. DirectHTTP
writes exclusively to application-owned staging. Final promotion remains a separate Core/FileCommit
transaction.

## Consequences

- small-file Booru/gallery workloads can retain real parallelism;
- hard network concurrency can be tested independently of configured thread count;
- huge task sets cannot allocate an unbounded Future list inside the scheduler;
- exact bandwidth limiting remains unsupported until a dedicated governor is implemented;
- Core-side durable RetryEpisode/RateLimitGate policy exists but cross-Run feedback is a later
  integration and is not falsely reported as complete in Sprint 4.
