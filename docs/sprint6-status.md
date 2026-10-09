# Sprint 6 Status — gallery-dl / Booru integration SEALED

Sprint 6 implements M6: **gallery-dl/Booru resolver + discovery + safe DirectHTTP handoff** on top of
the cumulative Sprint 0–5 repository. Concrete gallery-dl code remains Worker/Engine-owned; Core
receives only normalized discovery state and later authorizes normal Artifact/FileCommit work.

## Implemented scope

- Added V10 Probe/Discovery normalized contracts and handoff-safety modeling.
- Added a lazy `GalleryDlPythonBackend` pinned to `gallery-dl==1.32.9`.
- Added network-free extractor probe support without importing gallery-dl from Core.
- Embedded DataJob with `file=None` so JSON cannot corrupt Worker stdout/stdio IPC.
- Preserved private `_http_headers` / `_http_validate` only inside the Worker for handoff analysis.
- Treats DataJob `job.exception` as authoritative even though DataJob may return zero.
- Resolves gallery child extractors to a bounded depth and retains unresolved child URLs only in
  runtime memory.
- Normalizes discovered media into `NormalizedItemDescriptor` / `CandidateArtifact`.
- Classifies DirectHTTP handoff as SAFE / CONDITIONAL / UNSAFE.
- Forbids Cookie, Authorization and custom-validator dependent items from unsafe DirectHTTP handoff.
- Added Worker-owned `GalleryWorkerPipeline` and maximum 500-item Worker/Core batch boundary.
- Added durable DiscoveryCycle + Item ingestion without persisting raw media URLs, signed query
  strings, cookies or raw headers.
- Added one-way `UNKNOWN -> BOORU_GALLERY` Job classification.
- Added Item->Artifact ownership validation so an Item cannot be attached to another Job's Artifact.
- Connected SAFE/CONDITIONAL gallery items to the existing DirectHTTP -> Resume -> FileCommit path.
- Added a Windows/network development runtime gate for the exact gallery-dl version and built-in
  extractor registry.
- Added ADR 0014 describing engine ownership and handoff policy.
- Added `docs/updater-regression-risks.md` so the V8/V9 update failures become release-blocking
  acceptance tests when the V10 updater milestone begins.

## Cumulative source validation in this environment

```text
python -m compileall -q src tests tools    PASS
pytest -q                                  154 passed
architecture import boundaries             PASS
```

A separate 5,000-item gallery discovery/persistence stress sanity run produced:

```text
normalized/persisted items    5000
Worker/Core batches             10 x 500
SQLite integrity_check          ok
signed-token durable leak       false
state revision                  13
elapsed in this container       ~0.266 s
```

This is a local Linux source-runtime sanity measurement, not a Windows/site performance claim.

## Explicit validation boundary

The current container cannot install the optional gallery-dl wheel because outbound package DNS is
unavailable. Therefore real installed-package execution against gallery-dl 1.32.9 is **not claimed
here**. `tools/sprint6_gallery_runtime_smoke.py` is release/development gating code for a
network-enabled environment and verifies the exact pin plus network-free extractor registry.

Real Internet site E2E remains a Windows/network gate. In particular, Sprint 6 does not claim:

- authenticated Cookie/OAuth gallery-managed transfer for descriptors marked UNSAFE;
- final secure credential-store/credential-grant integration;
- full automatic Queue->Run scheduler dispatch from the packaged UI/Core processes;
- Windows QLocal/Frozen executable validation;
- yt-dlp, FFmpeg or Browser integration (Sprint 7+);
- App/Engine Pack installer/updater implementation.

The M6 contract is complete because unsupported/unsafe handoff is explicitly identified rather than
silently downgraded to an invalid DirectHTTP request.
