# Booru Studio V10 — Sprint 6 Implementation Report

## Goal

Implement Milestone M6 from the V10 implementation specification: gallery-dl/Booru
resolver/discovery/direct handoff, while preserving Core authority, durable queue/file semantics and
secret-handling boundaries.

## Architecture delivered

```text
Booru/Gallery input
        ↓
Job Worker
        ↓
GalleryWorkerPipeline
        ↓
GalleryDlAdapter (gallery-dl 1.32.9 pin)
        ↓
NormalizedItemDescriptor
        ↓  <= 500 items per durable crossing
DiscoveryCycle / Items
        ↓
Artifact + PathClaim
        ↓
HandoffSafety
  SAFE / CONDITIONAL ──→ DirectHTTP ─→ .part/Resume ─→ FileCommit
  UNSAFE ──────────────→ refuse DirectHTTP; managed session path required
```

## Significant hardening found during implementation

Official gallery-dl DataJob behavior required three corrections before it was suitable for Worker
embedding:

1. DataJob defaults its output file to stdout. Worker stdout may be an IPC channel, so Sprint 6 uses
   `file=None` and regression-tests this requirement.
2. DataJob's normal filtered output can omit private `_http_headers` information needed to determine
   Referer/Cookie/custom-header transfer requirements. Sprint 6 enables private data only inside a
   scoped Worker config context and then applies a strict durable allow-list.
3. DataJob captures extractor exceptions in `job.exception` and can still return zero. Sprint 6
   treats the explicit exception field/error record as authoritative rather than equating zero with
   success.

## Security / durability properties

- No Core import of gallery-dl or concrete gallery adapter modules.
- No raw signed media URL, Cookie, Authorization value, raw headers or child secret URL accepted by
  DiscoveryService durable APIs.
- Unsafe session-dependent descriptor cannot be handed to DirectHTTP.
- Extractor-provided filenames are forced to one safe path segment before PathClaim.
- Artifact planning validates that a discovered Item belongs to the same Job.
- Discovery batch sequence is contiguous and cycles are explicitly sealed.
- Existing FileCommit ownership and independent Core verification remain authoritative.

## QA

```text
compileall                                PASS
pytest cumulative                          154 passed
Sprint 0-5 regression                     PASS
Sprint 6 adapter tests                    PASS
Sprint 6 gallery discovery/FileCommit E2E PASS
Worker ownership/batch tests              PASS
architecture import boundaries            PASS
```

Additional deterministic local E2E confirms a Referer-dependent signed URL can travel only through
the ephemeral transfer plan to the real local HTTP server while the signed token does not appear in
SQLite. A Cookie-dependent candidate is classified UNSAFE and rejected before DirectHTTP handoff.

The 5,000-item stress sanity run completed 10 x 500-item durable batches with
`integrity_check=ok` and no signed-token leakage into SQLite.

## External runtime validation boundary

The repository pins `gallery-dl==1.32.9`. PyPI metadata identifies that release as Python 3.13
compatible. This container cannot fetch/install the wheel because package DNS is unavailable, so an
installed upstream runtime success is not asserted here. `tools/sprint6_gallery_runtime_smoke.py`
will fail closed on a missing/mismatched gallery-dl and verifies a built-in Danbooru extractor in a
network-enabled dev/build environment.

## V9.1.5 updater regression carried forward

Sprint 6 does not implement the V10 updater. It does add a release-gate document capturing the
historical failures: filename-coupled helper authorization, hidden helper errors, Qt shutdown
handoff deadlock, migration validator mismatch and post-replacement Worker self-spawn failure.
Those must be reproduced as tests before a V10 update package can be considered releasable.
