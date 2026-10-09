# V10 Updater Regression Risks inherited from V8/V9

This document is an implementation gate for the later Packaging/Updater milestones. It is **not**
implemented in Sprint 6, but the historical failures must not be rediscovered after packaging work
begins.

## Historical failures to reproduce in tests

1. **Target executable name coupling** — a V9 helper accepted only a `boorustudio_v8*` target name,
   so a fully staged update reached 100% and the helper then rejected the real V9 executable.
2. **Hidden helper diagnostics** — detached helper stdout/stderr made the UI look successful while
   replacement had already failed.
3. **Qt shutdown handoff deadlock** — the V8.2.1 GUI could remain in an installing state and refuse
   the close event required by the helper.
4. **Migration manifest/version mismatch** — bridge packages must be validated by the *installed*
   version's validator, not by assumptions in the new builder.
5. **Self-spawn health after replacement** — successful `--version-json` is insufficient if the
   installed frozen executable cannot spawn its own Worker child.

## V10 acceptance contract for the future Updater milestone

- Never authorize replacement by filename prefix. Bind the target to product identity + current
  capsule identity + cryptographic hash.
- Persist update state separately from UI progress and distinguish `STAGED`, `HANDOFF_STARTED`,
  `PARENT_EXITED`, `REPLACED`, `HEALTHY`, `ROLLED_BACK`.
- Helper failures must have a durable, redacted diagnostic channel visible on next launch.
- Parent shutdown must be a tested protocol, not a best-effort GUI `quit()` side effect.
- Verify old target hash before mutation and new target hash/version/build after mutation.
- Run installed-location health probes including Core start, Worker self-spawn/auth and clean exit
  before committing the new capsule.
- On any pre-commit failure, leave or restore the previous immutable capsule and relaunch it.
- Bridge/migration packages must be tested against the actual prior validator in a compatibility
  matrix.

These conditions become release-blocking tests when V10 reaches its Packaging/Updater milestones.

## Gate 6.5 formalization

The contract-only implementation now lives in `booru_studio.update.contracts`. The future updater
may not invent a different success definition. Its durable normal path is:

`AVAILABLE -> DOWNLOADING -> VERIFYING -> STAGED -> QUIESCING -> ACTIVATING -> HEALTH_CHECK -> COMMITTING -> SUCCESS`.

`SUCCESS` requires healthy-candidate + committed-current-pointer evidence. The machine-readable
release matrix in `booru_studio.reliability.release_gates` includes the historical filename-coupling,
100%-but-not-applied, hidden-diagnostic and frozen Worker self-spawn regressions.

