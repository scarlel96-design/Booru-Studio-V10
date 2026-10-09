# Booru Studio V10 — Sprint 5 Final Implementation Report

## Completion audit

The earlier Sprint 5 seal already restored the complete Sprint 4 cumulative repository and added the
first UI projection slice. A final completion audit found several implementation-quality gaps inside
that slice even though the original 138-test suite passed:

1. `ActionController` existed but the running QML controller did not use stale/pending action state;
2. the Qt model had a separate stable-ID data structure but still reset the entire model on every
   projection refresh;
3. the development QML backend bypassed the final UI-Core v1 protocol and called Core services
   directly;
4. arbitrary HTTP URLs were pre-classified as `DIRECT_FILE` before a Resolver had inspected them;
5. Queue cancellation, bounded-history visibility and submit-failure input preservation were not
   surfaced cleanly;
6. the UI-Core boundary accepted more loosely shaped payloads than necessary and could surface
   implementation exception text;
7. no PySide6/QML offscreen runtime smoke command existed for the target Windows QA environment.

These issues are corrected in this final Sprint 5 snapshot.

## Final implemented scope

1. Core-owned revision-consistent Downloads / Queue / bounded History projection.
2. Durable Run/Job settlement path for coherent History entries.
3. UI-Core v1 snapshot/create/cancel protocol and Core session handler.
4. Source UI harness that uses the real UI-Core envelope/session path for every operation.
5. Bounded request fields and stable public UI error codes/messages at the Core trust boundary.
6. ProjectionStore monotonicity, stale tracking and duplicate stable-ID rejection.
7. Stable-ID `ProjectionListModel`: unchanged identity/order updates use `dataChanged`; structural
   changes alone reset the model.
8. QML Downloads / Queue / History / Settings shell with add, refresh and cancel actions.
9. Busy/stale UI action gating plus input retention when submit fails.
10. Queue cancellation and bounded-history indicator.
11. KO/EN runtime language switching and catalog parity.
12. URL persistence redaction, bidi/control display sanitization and PlainText remote rendering.
13. Resolver-correct submission semantics: URL jobs are persisted as `UNKNOWN` until classified.
14. Windows-oriented offscreen QML runtime smoke tool wired into the QA workflow.

## Final cumulative source QA

```text
python -m compileall -q src tests tools    PASS
pytest -q                                  143 passed
architecture import boundaries             PASS
```

The suite retains Sprint 0–4 regression and now additionally verifies:

- monotonic projection state and duplicate stable-ID rejection;
- persistent queue after DB Actor restart;
- settled JobRun -> bounded History projection;
- UI-Core create/snapshot/cancel round-trip;
- malformed UI-Core payload rejection without echoing untrusted values;
- source backend persistence/restart behavior over the real UI-Core protocol path;
- source backend idempotent close/reject-after-close behavior;
- URL jobs remaining Resolver-owned (`JobKind.UNKNOWN`);
- sensitive URL redaction and durable cancel intent;
- stale telemetry generation/run rejection;
- translation parity and KO/EN switching;
- QML primary surfaces, delegate reuse, action gating, Queue cancel and bounded-history indicator;
- stable-ID Qt model update path and PlainText requirements.

## Additional source UI-Core stress

A separate run through `SourceUiBackend` created 100 URL Jobs, cancelled 10 of them, persisted the
state, closed the backend, reopened the same Unicode-path SQLite database and refreshed the
projection.

```text
create jobs                       100
cancel intents                     10
final state revision              110
secret query values in display      0
restart persistence              PASS
elapsed in this container       ~0.34 s
```

This is a source-protocol sanity measurement, not a Windows GUI performance benchmark.

## Validation boundary

PySide6 is not installed in this Linux execution environment and package DNS access is unavailable,
so an executed QML runtime is not claimed here. `tools/sprint5_qml_smoke.py` is included for the
network-enabled Windows development gate after the GUI extra is installed. Windows QLocal/Frozen
process separation remains a later J.2 gate by design; the source harness remains explicitly
development-only.
