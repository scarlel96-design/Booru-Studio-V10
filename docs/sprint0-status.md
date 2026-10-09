# Sprint 0 status

Implemented:

- repository/package skeleton
- opaque IDs
- UTC/monotonic Clock abstraction
- deterministic RandomSource
- normalized error taxonomy
- Job/Run/Item/Artifact domain entities
- lifecycle transition guards and invariants
- SQLite schema v1 skeleton covering the planned durable entities
- bounded single-writer DB Actor
- IPC envelopes and 4-byte length-prefixed JSON framing primitive
- Engine Adapter protocol contracts
- architecture import-boundary tests
- unit tests for the contracts above

Not part of Sprint 0:

- real network downloading
- QLocalSocket runtime
- Worker authentication
- Scheduler implementation
- QML UI
- gallery-dl / yt-dlp / FFmpeg / Playwright integrations
- native supervisor/updater

`uv.lock` requires dependency-index access and must be generated in a network-enabled build environment. No hand-authored lockfile is committed because an unverifiable lock is worse than an explicitly pending one.
