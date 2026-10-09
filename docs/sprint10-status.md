# Sprint 10 — Windows Production Runtime source milestone

Implemented source contracts:
- generic Envelope wire codec so UI-Core and Core-Worker can both use QLocal transport;
- event-driven same-user QLocal UI-Core server plus packaged `RemoteUiBackend`;
- packaged UI request/response work moved off the Qt GUI thread with stable command identity on reconnect/replay;
- Windows Worker bootstrap corrected to pass a raw inherited HANDLE, not a parent CRT fd identity;
- Native Rust Supervisor source owning a Job Object with `KILL_ON_JOB_CLOSE`; Core starts suspended,
  is assigned before resume, and the UI intentionally remains outside the containment tree;
- STARTUPINFOEX handle-list limits bootstrap/heartbeat HANDLE inheritance;
- sleep-safe Supervisor timing uses `QueryUnbiasedInterruptTime` plus power/Core lease fencing;
- hang termination requires missed event-loop heartbeat + live process + failed same-user QLocal
  `HEALTH_CHECK` + bounded grace, and the named-pipe probe itself is bounded;
- Core heartbeat is emitted by the Qt event loop rather than an independent Python heartbeat thread;
- Core->Worker lease closes new operation admission if Core control disappears;
- durable active `PAUSE_REQUESTED` / `CANCEL_REQUESTED` is forwarded to Worker and becomes authoritative
  only through `PAUSE_OBSERVED` / `CANCEL_OBSERVED` on the durable Worker transaction lane;
- `TRANSFER_STAGED` is fenced before `FILE_COMMIT_GRANT` when durable Pause/Cancel is pending;
- Apple/iOS/macOS + One UI + Windows 10/11 design principles are synthesized into one semantic-token
  Booru Studio design language rather than copied as four visual skins.

Source verification at Sprint 10 close: `compileall` PASS and **242 cumulative pytest tests PASS**,
including repeated active Pause/Cancel/FileCommit-fence source E2E. Exact final counts are restated in
the seal report after archive clean-room validation.

Not claimed in this Linux environment: compiled Rust Supervisor, Windows ACL behavior, real
STARTUPINFOEX inheritance, QLocal/Qt runtime, Frozen EXE/QML, Microsoft Defender interactions or Job
Object E2E. These remain executable Windows release gates.
