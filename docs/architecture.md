# V10 Architecture Guardrails — through Sprint 8

## Dependency direction

`common -> domain -> persistence/scheduler/engine contracts -> core/worker -> ui`

Domain must not import Qt, SQLite or concrete engines. Core must not import gallery-dl,
yt-dlp, Requests, Playwright or `engine.adapters`. UI must not own SQLite/Worker/Engine state.
Sprint 4 architecture tests enforce the concrete-engine/Requests restrictions for Core/Domain/UI.

## Durable state and commands

One bounded DB Actor owns the normal SQLite writer connection. Mutating commands use durable
idempotency receipts. `state_meta.state_revision` advances once per UI-visible semantic
transaction, not once per changed row.

## File commit boundary

`PREPARE -> durable PREPARED -> GRANTED -> filesystem mutation -> RESULT -> Core verify -> durable COMMITTED -> ACK`

DirectHTTP writes only to the Artifact staging path. No final filesystem promotion is allowed
when PREPARED could not be committed. Already committed finalization can be replayed without a
second FileRecord or second FILE_COMMITTED revision. Ambiguous recovery preserves candidate user
files for review.

## Scheduler and network execution

Sprint 4 introduces one bounded `ParallelTransferScheduler` execution slice. A logical transfer
must hold both the global transfer permit and the host lease before becoming in-flight. Global
permit states are ACTIVE/DRAINING/RELEASED; capacity shrink never turns an in-use draining unit
into free capacity.

DirectHTTP workers own independent Requests Sessions. The scheduler queue is bounded and worker
factory/runtime failures are surfaced to futures rather than silently losing consumers. Actual
in-flight concurrency is instrumented separately from configured parallelism.

Rate-limit and RetryEpisode persistence helpers are Core-side durable state. The Sprint 4
DirectHTTP worker still performs the immediate per-request retry loop locally; cross-Run durable
retry/rate-limit orchestration is intentionally not claimed complete until the later scheduler/
Core policy wiring is implemented.

## Core↔Worker process boundary

A Worker remains bound to one Run/Job/EnginePack/generation/PID/session. Bootstrap secret material
travels through a private inherited pipe/handle rather than command-line/environment. The protocol
uses mutual challenge-response before START_RUN. Durable Worker mutations use a monotonic
transaction lane and cumulative ACK after SQLite commit.

For a `DIRECT_HTTP` execution plan, the Worker main/control thread owns IPC while a separate
execution thread owns the bounded transfer scheduler. Completed transfers are progressively handed
back to the control plane. The control plane first durably records `TRANSFER_STAGED`, then Core
creates the PREPARED FileCommitIntent, then Worker performs the granted filesystem commit, and Core
independently finalizes/ACKs it.

Production transport target remains QLocalServer/QLocalSocket. Linux Sprint 4 QA exercises the
exact framed protocol over the explicit stdio source harness with real HTTP execution; this is not
a substitute for the later Windows Frozen QLocal/HANDLE gate.


## UI projection boundary

Sprint 5 adds a Core-owned revision-pinned projection. UI consumes Downloads, Queue and bounded
History rows through protocol DTOs and maintains a non-authoritative ProjectionStore. Transient
telemetry is fenced by Run/generation and is discarded independently from durable projection
state. QML renders projected remote text as PlainText.

The source QML harness may host Core services in-process for development only; production remains
UI process -> QLocal IPC -> Core process.

## Gate 6.5 managed-media boundary

Sprint 7 managed media must consume `ManagedMediaExecutionPolicy` rather than silently inheriting
DirectHTTP assumptions. Internal network control is explicitly EXACT/CONFIGURABLE/BEST_EFFORT/
OPAQUE, and external-engine inner attempts multiplied by V10 outer attempts must remain under the
`RetryEnvelope` hard compound ceiling. Single media vs collection presentation is authoritative
domain semantics, not a UI row-count heuristic.

`TransferDescriptor` is `EPHEMERAL_ONLY`: Persistence must not import the secret-bearing engine
runtime contracts. Diagnostic representations strip userinfo/query/fragment and all header values.

## Gate 6.5 updater boundary

Updater implementation is still deferred, but success semantics are already contractual. A future
side-by-side candidate is not successful until installed-candidate Core/DB/UI protocol/Worker
self-spawn/EnginePack/migration health is verified and the stable launcher current pointer is
committed while the previous capsule remains recoverable. UI progress and helper launch are never
authoritative update state.



## Sprint 7 media execution boundary

yt-dlp and FFmpeg remain concrete Worker-owned capabilities. Core owns only normalized media
semantics, collection membership, managed resource/retry policy and Artifact/FileCommit state.
SIMPLE_DIRECT reuses V10 DirectHTTP; CONTROLLED_MEDIA uses DirectHTTP for independently addressable
streams and V10-owned ffmpeg/ffprobe verification; COMPAT_MEDIA grants yt-dlp only the control level
that can actually be enforced.

YouTube JavaScript challenge support is part of the Engine runtime identity. The source dependency
uses a pinned local `yt-dlp-ejs` package and does not enable yt-dlp remote component downloads. A
supported Deno runtime is required for YouTube, while the final immutable Deno binary identity remains
a later Engine Pack packaging gate.

Collection presentation is persisted through `JobKind.COLLECTION_MEDIA`, `collections` and
`collection_memberships`; a single media source is `SINGLE_MEDIA` and cannot be converted to a batch
merely because the UI uses list controls. Engine format URLs and credentials are never collection
state.

A Core Artifact staging path may end in `.part`; FFmpeg therefore writes through a temporary file with
the intended container suffix, probes the media structure, and only then promotes the verified bytes
into Core staging. Final namespace mutation still belongs exclusively to the existing FileCommit
protocol.

## Sprint 8 web/browser boundary

- Unknown web pages resolve Static-first; Browser Assist is fallback-only.
- Concrete Playwright imports remain Worker/engine-owned.
- Browser Assist emits normalized candidates and never owns durable completion/FileCommit.
- Browser contexts are fresh/non-persistent; downloads disabled; Service Workers blocked; CSP bypass disabled.
- Public-page derived private-network targets are denied. LAN/private roots require an explicit opt-in and exact-origin confinement.
- Sprint-8 network-scope metadata is ephemeral and is rechecked by DirectHTTP on redirects.
- Generic multi-media pages use `WEB_PAGE` collection semantics rather than pretending to be gallery/playlist sources.
