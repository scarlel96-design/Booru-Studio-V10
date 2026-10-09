# ADR 0019 — Native Windows Supervisor owns Core containment

## Status
Accepted in Sprint 10.

## Context
The UI must be restartable without killing downloads, while Core/Worker/FFmpeg/engine descendants must
not survive an abandoned production runtime. Python-only process-tree cleanup is not strong enough to
be the sole containment boundary on Windows.

## Decision
A small native Supervisor owns the Core Job Object. Core is created suspended, assigned to the Job
Object before first execution, then resumed. `KILL_ON_JOB_CLOSE` is the last-resort orphan guarantee.
UI remains outside this Job Object and talks to Core over same-user QLocal IPC.

Supervisor hang decisions require all of the following rather than heartbeat alone:

1. the Core process is still alive;
2. event-loop heartbeat is missed across the bounded lease;
3. the same-user QLocal `HEALTH_CHECK` also fails;
4. bounded grace expires.

Lease aging uses Windows unbiased interrupt time so sleep/hibernate is not counted as active hang time.

## Consequences
- UI crash/relaunch does not terminate active downloads.
- Supervisor/Core loss cannot intentionally leave Worker/FFmpeg descendants orphaned.
- Windows Job Object, ACL, sleep/resume and frozen-process behavior remain executable release gates;
  Linux source QA is not evidence that those gates passed.
