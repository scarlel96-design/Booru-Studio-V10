# Sprint 7 start plan — Media Engine

Gate 6.5 intentionally leaves no design question that must be answered before coding begins.
Implement Sprint 7 in this order.

## 1. Exact engine pin and runtime gate

- Select the exact yt-dlp build in the network-enabled Windows implementation environment.
- Add the exact pin to `pyproject.toml` Engine extras and generate/verify `uv.lock`.
- Add an installed-runtime version/import smoke gate; mismatch is `ENGINE_PROTOCOL_ERROR` or
  `ENGINE_UNAVAILABLE`, never silent fallback.
- Keep yt-dlp import lazy and under `engine.adapters/...` / Worker ownership only.

## 2. Resolver / normalizer

- Probe URL support without downloading media.
- Normalize yt-dlp output into V10-owned descriptors; never expose raw extractor dictionaries to
  Domain/Core/UI/IPC.
- Remove cookies, headers, signed format URLs, JS/player tokens and private extractor objects from
  durable/diagnostic metadata.
- Preserve stable source identity, title, uploader/date/duration/dimensions and collection membership
  only through bounded V10 fields.

## 3. Presentation semantics

- Single media URL -> `MediaPresentationContract.single_media()` -> standalone card.
- Playlist -> `playlist()` -> Batch.
- Channel -> `channel()` -> Batch.
- Multiple submitted URLs -> `multi_input()` -> Batch.
- Do not synthesize Batch 1 for a single video.

## 4. Execution planning

Classify each normalized media plan into one truthful path:

1. `SIMPLE_DIRECT`: progressive resource, no merge/fragment requirement, handoff-safe ephemeral
   TransferDescriptor -> existing DirectHTTP.
2. `CONTROLLED_MEDIA`: yt-dlp resolution/transfer plus V10-owned minimal FFmpeg/ffprobe step where the
   engine exposes enough control.
3. `COMPAT_MEDIA`: yt-dlp manages the required pipeline; capability profile must report only the
   control V10 actually has.

An UNSAFE TransferDescriptor never enters DirectHTTP.

## 5. Scheduler / retry contract

- Core builds `ManagedMediaExecutionPolicy`.
- Derive yt-dlp internal retry knobs from the `RetryEnvelope`; never enable infinite retry.
- CONFIGURABLE/BEST_EFFORT/OPAQUE network paths consume the `ManagedNetworkEnvelope` honestly.
- Persist V10 outer RetryEpisode state independently from engine-local transient attempts.

## 6. Cancellation / pause

- cooperative cancellation first;
- observe at extractor/fragment/progress boundaries when available;
- bounded grace period;
- Worker termination remains the containment fallback;
- report `RESTART_PHASE`/`ENGINE_MANAGED` semantics rather than promising DirectHTTP checkpoint pause.

## 7. Minimum Sprint 7 FFmpeg boundary

Only implement the minimum merge/remux/probe needed by CONTROLLED_MEDIA. Advanced transcoding,
Browser capture and general postprocess UX remain Sprint 8.

## 8. Sprint 7 Exit Gate

Before sealing Sprint 7, at minimum prove:

- Sprint 0–6 + Gate 6.5 regression all pass;
- single video is not a batch;
- playlist/channel identity remains stable when counts are lazy/missing;
- format URLs/cookies/headers never appear in SQLite or public diagnostics;
- retry product cannot exceed Gate 6.5 compound ceiling;
- managed parallelism is never reported EXACT when it is not exact;
- cancellation cannot wedge the next queued Job;
- safe progressive handoff reuses DirectHTTP/FileCommit correctly;
- controlled merge/probe failure never produces a committed corrupt artifact;
- Worker crash cannot become Core crash.
