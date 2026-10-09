
## V10 Sprint 9 — Product UI refinement

- Added durable/idempotent Pause, Resume and Queue Move UI-Core commands.
- Added FIFO-safe queued pause/resume and transactional queue reordering.
- Added committed-file path and latest error evidence to Core projection.
- Added Open/Show in folder actions, right-click file menu and missing-path fail-closed behavior.
- Added phase-aware progress, kind badges, bytes/files/error details and lifecycle controls.
- Expanded KO/EN translation parity and Windows QML smoke contracts.

# Changelog

## V10 Sprint 8 — Static Web / Browser Assist

- Added bounded Static HTML media discovery with signed-URL-safe normalization.
- Added explicit network-scope policy, mixed-DNS rejection and opt-in-only LAN roots.
- Added Worker-owned Playwright 1.62.0 / installed Edge Browser Assist.
- Browser contexts are non-persistent with downloads disabled, CSP intact, Service Workers blocked and request routing enforced.
- Added Static-first -> Browser fallback and revalidation of Browser DOM/network media candidates.
- Added generic `WEB_PAGE` collection semantics and secret-free opaque collection identities.
- Extended ephemeral TransferDescriptor with network-scope policy metadata; diagnostic output never exposes root URL values.
- Added DirectHTTP redirect-time scope checks to prevent Browser/Static handoff SSRF through redirects.
- Added verified FFmpeg stream-copy remux.
- Added Windows Playwright/Edge runtime/security smoke gate and ADR 0018.
- Cumulative source regression: 206 passing tests before seal.

## V10 Sprint 7 — yt-dlp / media execution

- Pinned the official yt-dlp 2026.08.19 release asset by SHA-256 and yt-dlp-ejs 0.8.0.
- Added fail-closed YouTube Deno/EJS runtime checks and disabled runtime remote EJS downloads.
- Added Worker-owned yt-dlp probe, normalization, single/playlist/channel discovery and error mapping.
- Added durable SINGLE_MEDIA/COLLECTION_MEDIA classification and collection memberships.
- Added SIMPLE_DIRECT / CONTROLLED_MEDIA / COMPAT_MEDIA planning with truthful capabilities.
- Reused DirectHTTP/resume/FileCommit for handoff-safe progressive media.
- Added minimal FFmpeg stream-copy merge and ffprobe structural verification for controlled media.
- Connected Core-planned Artifact IDs/staging paths to media transfer and postprocess output.
- Added managed-output path containment and symlink rejection.
- Added postprocess failure gates preventing corrupt files from acquiring FileCommitIntent/FileRecord.
- Added real local-HTTP + FFmpeg + Core FileCommit integration and 5,000-item collection stress.
- Cumulative source regression: 191 passing tests before seal.

## V10 Gate 6.5 — Sprint 7 readiness reinforcement

- Locked single-media INDIVIDUAL vs playlist/channel/multi-input/gallery BATCH presentation semantics.
- Added managed-engine control truth levels, pause/resume semantics and ExecutionCapabilityProfile.
- Added ManagedNetworkEnvelope and compound RetryEnvelope.
- Added ManagedMediaExecutionPolicy as the Sprint-7 Core->Worker policy contract.
- Marked TransferDescriptor EPHEMERAL_ONLY and added secret-free diagnostic representation.
- Added contract-only transactional updater phase/success evidence model.
- Added machine-readable Windows/Frozen/Updater Gate 6.5 scenario matrix.
- Added architecture gates preventing Persistence from depending on secret-bearing engine runtime contracts.
- Preserved pyproject/uv as the sole Python dependency authority; no guessed yt-dlp pin was introduced.
- Added ADR 0015/0016, dependency policy, Windows release matrix and Gate 6.5 readiness documentation.
- Cumulative source regression: 169 passing tests.

## V10 Sprint 6 — gallery-dl / Booru integration

- Added Worker-owned gallery-dl 1.32.9 resolver/discovery adapter.
- Added ProbeResult, NormalizedItemDescriptor, CandidateArtifact and DiscoveryResult contracts.
- Added SAFE / CONDITIONAL / UNSAFE TransferDescriptor handoff classification.
- Connected safe gallery discovery to existing DirectHTTP + Resume + FileCommit.
- Added durable DiscoveryCycle/Item batches and one-way UNKNOWN -> BOORU_GALLERY classification.
- Prevented signed URLs, Cookies, raw headers and queued child secrets from entering ordinary SQLite state.
- Corrected gallery-dl DataJob embedding: no stdout JSON, private HTTP metadata retained only ephemerally, captured exceptions treated as errors.
- Added Worker-owned GalleryWorkerPipeline with <=500-item crossing batches.
- Added exact gallery-dl runtime smoke gate and ADR 0014.
- Added future updater regression gates based on V8/V9 helper/handoff/migration failures.
- Cumulative source regression: 154 passing tests.

## V10 Sprint 5 — UI projection slice

- Restored the sealed Sprint 4 repository after detecting that the initial Sprint 5 directory
  contained only copied documentation and no implementation.
- Added Core-owned revision-consistent UI projection snapshots.
- Added bounded History initial page and persistent Queue/Downloads projections.
- Added atomic JobRun/Job settlement for History.
- Added UI-Core v1 snapshot/create/cancel protocol and Core session handler.
- Added ProjectionStore, ActionController, stable-ID list backing and TelemetryOverlay.
- Added PySide6 QAbstractListModel adapter and Qt Quick/QML application shell.
- Added Add-to-Queue, durable cancel intent, refresh and KO/EN language switching baseline.
- Added URL persistence redaction, bidi/control display sanitization and PlainText rendering.
- Cumulative source regression: 138 passing tests before seal.

## V10 Sprint 4 — DirectHTTP execution slice

- Bounded true-parallel DirectHTTP scheduling, durable retry/rate-limit state, Range/If-Range
  resume, adaptive network behavior and Worker/Core FileCommit integration.

## V10 Sprint 3

- Private Worker bootstrap, mutual authentication, durable Worker transaction lane and cancel.

## V10 Sprint 2

- Artifact/PathClaim/Resume/FileCommit crash-safety and recovery.

## V10 Sprint 1

- Persistent Submission/Job/Queue/JobRun and idempotent command receipts.

## V10 Sprint 0

- Repository foundations, typed IDs, domain, DB Actor, schema and IPC contracts.

### Sprint 5 finalization pass

- Routed the source QML backend through the real UI-Core v1 envelope and CoreUiSession path.
- Preserved Resolver ownership by storing unclassified URL jobs as `UNKNOWN`, not `DIRECT_FILE`.
- Added UI-Core payload bounds and public error sanitization.
- Enforced duplicate stable-ID rejection in ProjectionStore.
- Changed Qt projection refreshes to emit `dataChanged` for identity-stable rows instead of resetting every model.
- Wired pending/stale action state into the GUI and preserved input text on failed submission.
- Added Queue cancellation and bounded-History visibility.
- Added KO/EN status strings and final translation parity coverage.
- Added an offscreen PySide6/QML smoke gate for Windows development QA.
- Raised cumulative source regression from 138 to 143 passing tests.


## V10 Sprint 10 — Windows Production Runtime source slice

- Added production same-user QLocal UI/Core source transport and generic envelope wire codec.
- Moved packaged UI IPC request/response off the Qt GUI thread and retained stable command identity across reconnect/replay.
- Corrected Windows Worker bootstrap from parent CRT-fd identity to raw inherited HANDLE + child `_open_osfhandle`.
- Added Native Rust Supervisor source, Job Object KILL_ON_JOB_CLOSE, suspended Core assignment-before-resume and bounded health probing.
- Bound heartbeat to the Qt event loop and used sleep-safe unbiased Windows timing for hang leases.
- Added Core->Worker operation lease fencing.
- Forwarded durable active Pause/Cancel to Worker and atomically applied PAUSE_OBSERVED/CANCEL_OBSERVED with the Worker transaction receipt.
- Fenced TRANSFER_STAGED before FILE_COMMIT_GRANT when durable control is pending.
- Added semantic QML design tokens and locked the Apple/One UI/Windows design-language synthesis.
- Cumulative source regression: 242 passing tests before archive seal.
