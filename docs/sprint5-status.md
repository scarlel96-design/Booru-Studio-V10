# Sprint 5 Status — UI Projection Slice FINAL

Sprint 5 is the first V10 user-interface slice. It connects the durable Core model to a Qt/QML
presentation architecture without moving authority into QML. The Sprint 5 implementation scope is
now closed; Windows/Frozen-runtime validation remains a later J.2 platform gate rather than an
unfinished Sprint 5 feature.

## Final implemented scope

- Core-owned, state-revision-pinned projection snapshots.
- Separate Downloads, persistent Queue and bounded History projections.
- Durable JobRun settlement so completed work enters History coherently.
- UI-Core v1 protocol for snapshot/create/cancel operations.
- Development source harness now routes every request through the real UI-Core v1 envelope and
  `CoreUiSession`; it no longer bypasses the protocol by calling JobService directly.
- ProjectionStore revision-regression rejection, duplicate-ID rejection and stale-state tracking.
- Stable-ID Qt model backing; data-only updates emit `dataChanged` instead of resetting the entire
  QML model when row identity/order is unchanged.
- Transient run/generation-fenced telemetry overlay remains separate from durable projection state.
- Qt Quick/QML shell with Downloads / Queue / History / Settings navigation.
- Add-to-Queue, refresh, cancel from Downloads and Queue, busy/stale action gating and command
  failure behavior that preserves the input field when submission fails.
- Bounded-history indicator when more settled rows exist than the initial 200-row projection page.
- KO/EN runtime language switch baseline and translation-key parity checks.
- Plain-text rendering for projected remote text, URL persistence redaction and bidi/control display
  sanitization.
- UI-Core request validation with bounded text fields and non-secret-bearing public error responses.
- URL submissions remain `JobKind.UNKNOWN` until the later Resolver classifies them; an arbitrary
  HTTP page is no longer incorrectly pre-classified as `DIRECT_FILE` by the UI harness.
- Windows QA script includes an offscreen PySide6/QML runtime smoke gate after GUI dependencies are
  installed.

## Source validation completed here

```text
python -m compileall -q src tests tools    PASS
pytest -q                                  143 passed
source UI-Core stress: 100 create + 10 cancel + restart persistence    PASS
```

## Platform validation boundary

The current Linux container does not have PySide6 and cannot fetch it because external package DNS
is unavailable. Therefore an executed Qt/QML runtime is not claimed in this environment. The new
`tools/sprint5_qml_smoke.py` gate is intended to run automatically in the network-enabled Windows
development environment after `tools/bootstrap_dev.ps1` installs the GUI extra.

The following are still later architecture/release gates, not missing Sprint 5 scope:

- Windows QLocalServer/QLocalSocket runtime and ACL behavior;
- STARTUPINFOEX handle inheritance and Frozen executable behavior;
- Native Supervisor / Job Object;
- final packaged UI-process -> QLocal -> Core-process host;
- later product features such as automatic scheduler dispatch, pause/resume UI, open/reveal file,
  rich item detail, full History keyset continuation and final commercial visual polish.
