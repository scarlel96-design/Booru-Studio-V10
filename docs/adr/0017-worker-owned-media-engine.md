# ADR 0017 — Worker-owned yt-dlp media engine and verified postprocess

## Status
Accepted for Sprint 7.

## Problem
Video/audio sources need yt-dlp's extractor compatibility and sometimes its managed HLS/DASH/media
pipeline, while V10 must retain truthful scheduler control, secret isolation, crash-safe FileCommit
and the single-video-vs-collection product semantics fixed at Gate 6.5.

## Decision

- yt-dlp is a concrete Worker-owned adapter; Core/UI/Persistence/Domain cannot import it.
- Raw yt-dlp dictionaries are normalized before crossing any V10 domain boundary.
- The stable source dependency is pinned to the official `2026.08.19` release asset with SHA-256;
  `yt-dlp-ejs==0.8.0` is local and remote EJS downloads are disabled.
- YouTube requires a supported Deno runtime; the final packaged Deno identity belongs to immutable
  Engine Pack work rather than ad-hoc runtime self-update.
- media execution chooses exactly one of SIMPLE_DIRECT / CONTROLLED_MEDIA / COMPAT_MEDIA.
- SAFE/CONDITIONAL progressive resources reuse DirectHTTP. UNSAFE descriptors never do.
- CONTROLLED_MEDIA reuses DirectHTTP for addressable streams, then performs V10-owned FFmpeg
  stream-copy and ffprobe verification before FileCommit.
- COMPAT_MEDIA lets yt-dlp own the required pipeline but reports BEST_EFFORT/CONFIGURABLE/OPAQUE
  semantics honestly and validates every returned path stays inside the Worker output root.
- Playlist/channel presentation is durable collection state; a single video is not a synthetic batch.

## Security / durability impact
Signed format URLs, headers, cookies, JS tokens and runtime component locators remain ephemeral.
Managed output path escape/symlink behavior is rejected. FFmpeg output cannot enter the final namespace
until ffprobe succeeds and the existing Core FileCommit protocol independently verifies the staged
bytes.

## Retry / resource impact
Gate 6.5 RetryEnvelope and ManagedNetworkEnvelope remain authoritative. yt-dlp internal retry knobs
are finite and the adapter does not enable infinite retry or remote executable components.

## Deferred
Browser fallback, advanced transcoding, native Job Object containment, packaged runtime identity,
installer/updater and live Windows E2E remain later milestones.
