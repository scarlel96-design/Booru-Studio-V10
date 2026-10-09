# Booru Studio V10 — Sprint 10 implementation report

## Result
Source scope: **COMPLETE** pending final archive seal. Windows executable gates remain explicitly open.

## Scope completed
- Production-target same-user QLocal UI/Core transport and generic envelope wire codec.
- Packaged UI IPC worker thread, asynchronous completion semantics and idempotent reconnect/replay.
- Raw Windows inherited-HANDLE Worker bootstrap with STARTUPINFOEX allow-list.
- Native Rust Supervisor source, suspended Core launch, Job Object assignment-before-resume and
  KILL_ON_JOB_CLOSE containment.
- Qt-event-loop heartbeat plus bounded same-user QLocal health probe and sleep-safe lease timing.
- Core->Worker lease that fences new operation admission if Core control disappears.
- Durable active Pause/Cancel forwarding and OBSERVED state settlement.
- FileCommitGrant fence preserving staging/resume state when control arrives after TRANSFER_STAGED.
- Booru Studio semantic design-system direction derived from Apple hierarchy/craft, One UI
  reachability/viewing-vs-interaction structure and familiar Windows desktop/settings IA.

## Important defects closed
1. Windows Worker launch previously passed a parent CRT fd number even though STARTUPINFOEX inherits an
   OS HANDLE. The child now receives the raw HANDLE and opens its own fd with `_open_osfhandle`.
2. A heartbeat emitted from an independent Python thread could remain alive while the Qt event loop was
   hung. Heartbeat is now event-loop driven.
3. A blocking named-pipe health read could hang the Supervisor. Probe readiness is bounded before read.
4. UI QLocal waits no longer intentionally block the GUI thread.
5. Ambiguous mutation reply loss reuses stable command identity instead of issuing a new logical command.
6. Sprint 9 active Pause/Cancel no longer stops at a DB intent; actual Worker observation is durable and
   atomically settles Run/Job state.

## Source verification
- `python -m compileall -q src tests tools` — PASS
- `PYTHONPATH=src pytest -q` — **242 passed** before packaging
- active Pause/Cancel/FileCommit-fence integration subset repeated 3x — PASS

## Platform boundary
This environment is Linux without the intended Windows Qt/Rust/frozen runtime. No claim is made that
Job Object, QLocal ACL, STARTUPINFOEX HANDLE inheritance, Rust Supervisor compilation or Frozen QML has
passed Windows E2E. `docs/windows-release-gates.md` lists the executable gates that remain mandatory.

## Next sprint readiness
After clean-room archive seal: **READY for Sprint 11 Packaging / Frozen Runtime / Installer**.
