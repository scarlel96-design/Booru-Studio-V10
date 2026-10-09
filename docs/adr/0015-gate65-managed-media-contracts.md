# ADR 0015 — Gate 6.5 managed-media contracts

## Status
Accepted before Sprint 7.

## Problem
DirectHTTP is EXACT-controlled by V10, while yt-dlp and later managed engines may own fragments,
protocol retries, merge steps and internal connections. Treating one managed operation as one exact
network permit or exposing engine-native objects to Core would make resource/retry/UI semantics
incorrect.

## Decision
- Add `ManagedNetworkEnvelope` with EXACT/CONFIGURABLE/BEST_EFFORT/OPAQUE control truth.
- Add `RetryEnvelope` whose outer x inner attempt product must fit a hard compound ceiling.
- Add `ExecutionCapabilityProfile` and `ManagedMediaExecutionPolicy` as the Core->Worker contract.
- Keep concrete managed engines Worker-owned.
- Add domain `MediaPresentationContract`; single media is INDIVIDUAL while playlist/channel/
  multi-input/gallery are explicit BATCH semantics.
- Keep every `TransferDescriptor` EPHEMERAL_ONLY and expose only a secret-free diagnostic view.

## Consequences
Sprint 7 can add yt-dlp without changing Core authority, Scheduler truthfulness, UI batch semantics or
secret durability. Compatibility mode may report BEST_EFFORT/OPAQUE instead of falsely claiming
DirectHTTP-level control.
