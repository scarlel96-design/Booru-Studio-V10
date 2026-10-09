# Sprint 4 status

## Goal

Prove the first complete real-network vertical slice without weakening the durable boundaries
created in Sprint 0–3:

`Core -> authenticated Worker -> bounded Scheduler -> DirectHTTP -> staging -> durable tx -> PREPARED FileCommit -> final file`

## Completed

- global transfer permit pool with hard capacity and DRAINING shrink semantics;
- per-host adaptive limiter;
- bounded rolling worker scheduler;
- bounded retry/transport-reset classification;
- Core-side durable RetryEpisode and RateLimitGate repositories/services;
- DirectHTTP Range/If-Range transfer implementation;
- crash-safe sidecar checkpoint recovery;
- Worker Control Plane / Execution Plane separation;
- progressive staged completion and FileCommit transaction messages;
- real local HTTP + real Python Worker subprocess E2E;
- cancellation while blocking network transfer is active;
- cumulative source regression suite: 117 tests.

## Explicitly deferred

- final Core SchedulerCoordinator admission across multiple Jobs;
- exact bandwidth governor;
- complete durable 429/retry policy feedback from Worker across Run restart;
- gallery-dl / yt-dlp / FFmpeg / Browser;
- QML UI;
- Windows Frozen/QLocal/HANDLE/runtime verification;
- native Supervisor/Job Object;
- updater/Engine Pack lifecycle.

## Next planned implementation slice

Sprint 5 introduces the minimum UI Projection path for Downloads / Queue / History on top of the
now-real Core/Worker/DirectHTTP execution slice. It must consume Core projection state rather than
owning download authority in QML.
