# Sprint 3 status

## Implemented

- CoreInstanceId / WorkerSessionId and single-use random Worker endpoints
- private bounded Worker bootstrap bound to Run/Job/EnginePack/generation/PID
- POSIX inherited-fd harness and Windows STARTUPINFOEX handle-list production source path
- mutual HMAC-SHA256 authentication and HKDF directional session keys
- strict Core↔Worker protocol v1 and framed transport abstraction
- production-target user-only QLocal adapter plus explicit source-only stdio harness
- durable worker_sessions and worker_tx_receipts
- monotonic Worker transaction lane and cumulative ACK
- exact replay acceptance, changed-content conflict and gap rejection
- atomic Worker side effect + receipt + sequence commit
- replay-safe durable CANCEL_JOB / CANCEL_REQUESTED
- real source subprocess E2E and 25-process lifecycle stress

## Sealed source validation

- cumulative source suite: 96 passing tests
- 25 CLOSED WorkerSessions / 50 durable tx receipts / 0 open sessions
- SQLite integrity_check=ok

## Deliberately not implemented yet

- real HTTP/network execution plane and Scheduler/resource permits
- gallery-dl / yt-dlp / FFmpeg / Browser execution
- UI↔Core QLocal protocol and QML UI
- native Launcher/Supervisor/Job Object
- Frozen executable spawn and updater/rollback

## Boundary

Production QLocal and Windows inherited-HANDLE implementations require the later Windows
PySide/Frozen gate before they can be called runtime-validated.
