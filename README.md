# Booru Studio V10 — Sprint 10 product-UI source snapshot

This repository is the cumulative V10 implementation through **Sprint 10**. Sprint 0–6 + Gate 6.5
provides the durable domain/queue/FileCommit foundation, authenticated Worker boundary, real parallel
DirectHTTP execution, Qt/QML projection slice, gallery-dl/Booru discovery and locked managed-media
contracts. Sprint 7 adds the Worker-owned yt-dlp + FFmpeg media execution slice; Sprint 8 adds Static Web resolution and constrained Playwright/Edge Browser Assist.

## Implemented through Sprint 6

- Worker-owned `gallery-dl==1.32.9` resolver/discovery adapter; Core never imports it.
- Resolver probe + normalized Booru/Gallery discovery into durable DiscoveryCycle/Item state.
- SAFE / CONDITIONAL / UNSAFE DirectHTTP handoff classification.
- SAFE/CONDITIONAL gallery media reuses V10 DirectHTTP, `.part`/resume and crash-safe FileCommit.
- DataJob embedding suppresses stdout, preserves required private HTTP metadata ephemerally and treats
  captured gallery-dl exceptions as failures.
- Worker/Core discovery crossing is bounded to at most 500 normalized items per batch.
- Signed URLs, raw headers, cookies and child secret URLs are excluded from ordinary durable state.


## Sprint 7 media engine

- exact yt-dlp `2026.08.19` official release asset pin + SHA-256 and local `yt-dlp-ejs==0.8.0`;
- YouTube JS challenge runtime gate with supported Deno and runtime remote-component downloads disabled;
- normalized single media / playlist / channel discovery with durable SINGLE_MEDIA/COLLECTION_MEDIA
  classification and collection memberships;
- SIMPLE_DIRECT, CONTROLLED_MEDIA and COMPAT_MEDIA execution modes with truthful capability reporting;
- safe progressive resources reuse the proven DirectHTTP/resume/FileCommit path;
- separately addressable streams use DirectHTTP + minimal FFmpeg stream-copy + ffprobe verification;
- managed yt-dlp outputs are accepted only as contained regular files inside the Worker output root;
- format URLs, cookies, Authorization/raw headers, JS/player tokens and raw extractor dictionaries remain
  outside ordinary durable state.

## Sprint 8 Static Web / Browser Assist

- Static-first resolver for ordinary HTML media (`img`/`video`/`audio`/`source`, OpenGraph/Twitter, srcset and preload hints).
- Browser Assist runs only after Static discovery yields no usable media.
- Playwright 1.62.0 is pinned and uses installed Edge with a fresh non-persistent context, browser downloads disabled and Service Workers blocked.
- public-page derived localhost/private/link-local/reserved targets are blocked; private/LAN roots require explicit opt-in and same-origin confinement.
- Browser observations return to normal V10 descriptors and DirectHTTP/FileCommit rather than creating a second downloader.
- multi-media generic pages use durable `WEB_PAGE` collection semantics with opaque secret-free source identity.
- DirectHTTP revalidates Sprint-8 network scope across redirects.
- FFmpeg adds verified stream-copy remux for container-only postprocess.

## Gate 6.5 reinforcement

- `MediaPresentationContract`: single media is an INDIVIDUAL card; playlist/channel/multi-input/gallery
  are explicit BATCH collections. UI must not infer this from row count.
- `ExecutionCapabilityProfile`: managed engines report EXACT / CONFIGURABLE / BEST_EFFORT / OPAQUE /
  UNSUPPORTED control honestly.
- `ManagedNetworkEnvelope`: configurable engines get a bounded grant; OPAQUE engines do not claim an
  exact configured parallelism.
- `RetryEnvelope`: V10 outer attempts x external-engine inner attempts must fit a hard compound ceiling.
- `ManagedMediaExecutionPolicy`: ready-made Core->Worker policy envelope for Sprint 7 yt-dlp paths.
- Every `TransferDescriptor` is `EPHEMERAL_ONLY`; its diagnostic view strips URL secrets, header
  values and credential references.
- Contract-only updater state machine forbids `SUCCESS` until candidate health + committed current
  capsule pointer evidence exists.
- Machine-readable Windows/Frozen/Updater gate IDs include V9 filename-coupling, 100%-but-not-applied,
  hidden-helper-diagnostic and installed Worker self-spawn regressions.

## Cumulative source QA

Sprint 9 adds durable product controls, phase-aware job cards and local file actions. The final seal report records the exact cumulative/clean-room test count.

## Development setup

On a network-enabled 64-bit GIL-enabled CPython 3.13 Windows development machine:

```powershell
.\tools\bootstrap_dev.ps1
.\tools\qa.ps1
booru-studio-ui
```

`pyproject.toml` contains the exact Sprint 7 yt-dlp release asset + SHA-256/EJS pin and Sprint 8 `playwright==1.62.0`. `uv.lock` must be generated and verified in the network-enabled Windows build environment; this container cannot resolve external dependency hosts and no fabricated lock is included.

## Sprint 9 Product UI refinement

- durable Pause/Resume and Queue Move commands over the existing UI-Core envelope;
- queued Pause removes the reservation from FIFO and Resume returns it to the tail;
- running Pause remains a durable `PAUSE_REQUESTED` intent until the execution layer acknowledges it;
- committed output path + latest technical error evidence are projected for product UX;
- cards expose kind, phase/wait state, byte/file progress, technical failure evidence and file actions;
- postprocess/verify/reconcile remain visibly active after transfer reaches 100%;
- right-click Show in folder, explicit Open, Queue move controls and KO/EN parity are covered by regression tests.

## Sprint 10 Windows production-runtime source slice

- same-user QLocal UI/Core production transport and GUI-thread-independent packaged UI IPC;
- stable client/command identity across bounded reconnect/replay;
- raw inherited-HANDLE Worker bootstrap and STARTUPINFOEX allow-list;
- native Supervisor / Job Object source with assignment-before-resume and sleep-safe health fencing;
- event-loop heartbeat + bounded active QLocal health probe;
- Core->Worker operation lease;
- durable active Pause/Cancel forwarding -> Worker OBSERVED transaction -> atomic Run/Job settlement;
- FileCommitGrant fence after TRANSFER_STAGED;
- semantic QML design tokens and a locked Booru Studio design language derived from Apple, One UI and familiar Windows interaction/Settings principles.

## Next boundary

Sprint 11 packages this runtime as the Windows frozen/installed product: PyInstaller onedir/multipackage, QML/Qt resource packaging, exact runtime dependency checks, Inno Setup, candidate self-tests and install/repair gates.

## Validation boundary

Sprint 10 is source QA in this Linux environment. It does not claim Windows QLocal ACL,
STARTUPINFOEX, Job Object, Frozen QML/Worker behavior, live yt-dlp sites, installer or updater E2E.
Those are explicit later release gates rather than assumed successes.


## Sprint 10
Windows production-runtime source contracts and the Booru Studio design-language direction are now included. See `docs/sprint10-status.md` and `docs/design-system.md`.
