# Sprint 7 — Media Engine status

Status: **SOURCE SCOPE COMPLETE / READY TO SEAL**.

Sprint 7 adds the Worker-owned media execution slice on top of the sealed Sprint 6 + Gate 6.5
contracts. It does not move Browser fallback, native Windows Supervisor, packaging or updater runtime
into this milestone.

## Implemented

### yt-dlp runtime boundary

- exact stable yt-dlp source pin: `2026.08.19`, fetched from the official release tarball by URL and
  SHA-256 in the Engine extra;
- `yt-dlp-ejs==0.8.0` pinned locally; runtime remote EJS downloads are disabled;
- YouTube extraction/download fails closed unless a supported Deno runtime is present; source floor is
  Deno 2.3.0 and the later immutable Engine Pack remains responsible for the final packaged Deno pin;
- imports stay lazy and Worker/engine-owned; Core/UI/Persistence/Domain never import yt-dlp;
- Python API uses `extract_info(..., download=False)` for analysis and calls `sanitize_info()` only as
  a serializability API check after V10's own allow-listing. Raw extractor dictionaries do not cross
  into Domain/Core/UI.

### media discovery and durable semantics

- single media -> `SINGLE_MEDIA` + `INDIVIDUAL`;
- playlist/channel -> `COLLECTION_MEDIA` + explicit collection kind;
- normalized collection source key/title and memberships are persisted using the existing collection
  schema;
- discovery crossing remains bounded to <=500 normalized items per batch;
- signed media URLs, cookies, Authorization/raw headers and format dictionaries remain runtime-only;
- individual media is rejected if discovery offers more than one item, preventing synthetic Batch 1
  semantics from reappearing.

### execution paths

1. **SIMPLE_DIRECT** — one progressive audio+video resource with SAFE/CONDITIONAL handoff uses the
   existing DirectHTTP/Range/resume/FileCommit path. Core-provided Artifact ID and staging path are
   preserved in the resume sidecar.
2. **CONTROLLED_MEDIA** — separately addressable video/audio resources use existing DirectHTTP, then
   a minimal V10 FFmpeg stream-copy merge. ffprobe must structurally verify both video and audio
   before the staged file can enter Core FileCommit.
3. **COMPAT_MEDIA** — fragmented/manifest/secret-bound/otherwise unsafe media stays in yt-dlp-managed
   execution. Returned paths are accepted only if they are regular files contained by the Worker
   output directory.

### resource / retry / cancellation

- Gate 6.5 `ManagedMediaExecutionPolicy` is translated into finite yt-dlp retry knobs;
- fragment concurrency is configured only when the managed network envelope is not OPAQUE;
- remote executable components are disabled by default;
- cancellation is observed by yt-dlp progress hooks and FFmpeg process termination; Worker process
  containment remains the hard fallback in later native Windows Supervisor gates;
- COMPAT mode never claims DirectHTTP-equivalent exactness unless the upstream capability is actually
  exact.

### FFmpeg / ffprobe

Sprint 7 deliberately implements only stream-copy merge and structural probe. Advanced transcoding,
Browser capture and general postprocess UX remain Sprint 8.

A Core Artifact staging path ends in `.part`, so FFmpeg writes through a temporary file with an
explicit media container suffix and only then atomically promotes the verified result into the Core
staging path. This avoids relying on `.part` for FFmpeg muxer inference.

## Source verification

Final pre-seal source run:

```text
python -m compileall -q src tests tools    PASS
PYTHONPATH=src pytest -q                    191 passed
```

Additional deterministic source probes:

```text
5,000 normalized media items
10 x 500-item durable batches
5,000 collection memberships
SQLite integrity_check = ok
elapsed in this container ~= 0.166 s
```

The controlled-media integration test uses this container's real FFmpeg/ffprobe runtime and a real
local HTTP server to prove:

```text
video DirectHTTP + audio DirectHTTP
-> FFmpeg stream-copy merge
-> ffprobe video+audio verification
-> Core Artifact staging
-> PREPARE / perform_commit / Core final verification
-> FileRecord COMMITTED
```

A corrupt audio input is also injected and proves there is no FileCommitIntent/FileRecord/final file
on postprocess failure.

## Environment boundary

This Linux container does not have yt-dlp, yt-dlp-ejs or Deno installed and outbound dependency DNS
is unavailable. `uv lock` therefore cannot be generated or the actual pinned yt-dlp runtime smoke
executed here. The repository includes `tools/sprint7_media_runtime_smoke.py`; on the intended
network-enabled Windows development environment it fails closed on yt-dlp/EJS/Deno mismatch and also
checks FFmpeg/ffprobe plus the extractor registry.

Accordingly Sprint 7 does **not** claim live-site YouTube certification, Windows Frozen media E2E,
QLocal production transport, Job Object containment, packaged Deno/FFmpeg, installer or updater E2E.
Those remain explicit later gates.
