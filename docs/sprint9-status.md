# Sprint 9 status — UI/UX product refinement

Sprint 9 turns the projection shell into a product-facing control surface without moving engine or
Worker ownership into QML.

Implemented:

- durable/idempotent Pause, Resume and Queue Move commands over UI-Core v1;
- queued Pause becomes authoritative `PAUSED` immediately and leaves the persistent queue;
- Resume returns a paused reservation to the durable FIFO tail;
- active/waiting Pause remains a durable `PAUSE_REQUESTED` intent for the execution layer to observe;
- queue move-up/move-down is transactionally normalized under the unique sort-key invariant;
- projection exposes the latest committed local file path plus bounded latest technical error evidence;
- downloaded-file open and Explorer/folder reveal actions use argv-based OS dispatch, never shell text;
- Job cards show kind, phase/wait reason, files/bytes, technical error evidence and lifecycle controls;
- postprocess/verify/reconcile phases remain visibly active even when transfer bytes have reached 100%;
- right-click file actions, keyboard-accessible buttons and KO/EN catalog parity are retained.

Boundary:

- Sprint 9 does not claim that an already-running Worker has executed a pause handshake. The durable
  `PAUSE_REQUESTED` intent is the Core contract; production Worker/Supervisor observation belongs to
  the Windows runtime integration milestone.
- Source UI uses the in-process protocol harness. Production QLocal/Windows frozen validation remains
  a later platform gate.
