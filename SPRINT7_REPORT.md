# Booru Studio V10 — Sprint 7 Media Engine Report

## Result
**SOURCE SCOPE COMPLETE.** Final archive seal is recorded separately after clean-room verification.

## Scope completed

- pinned Worker-owned yt-dlp 2026.08.19 source runtime and yt-dlp-ejs 0.8.0;
- Deno/JavaScript challenge runtime fail-closed contract for YouTube and no remote EJS component fetch;
- yt-dlp extractor probe, normalized single/playlist/channel discovery and safe metadata allow-list;
- durable `SINGLE_MEDIA` / `COLLECTION_MEDIA` classification plus collection memberships;
- SIMPLE_DIRECT / CONTROLLED_MEDIA / COMPAT_MEDIA execution planning with truthful capabilities;
- finite managed retry/concurrency translation from Gate 6.5 policy;
- Core Artifact identity/staging injection into media DirectHTTP;
- minimal FFmpeg stream-copy + ffprobe structural verification;
- managed output containment/symlink rejection;
- actual DirectHTTP -> FFmpeg -> Core FileCommit integration;
- postprocess-failure gate proving corrupt output cannot be committed.

## Important implementation corrections found during Sprint 7

1. A Core staging filename ends in `.part`. Passing that suffix directly to FFmpeg made muxer
   autodetection fail. FFmpeg now writes a sibling temporary file with the intended media container
   suffix, verifies it, then promotes it into the Core `.part` staging path.
2. A standalone media DirectHTTP handoff initially generated a temporary Artifact ID. The pipeline now
   accepts the Core-planned Artifact ID/generation/staging path so resume sidecar identity and durable
   commit remain one continuous artifact lineage.
3. The existing `collections` / `collection_memberships` schema had no Core media coordinator using it.
   Sprint 7 now persists playlist/channel grouping instead of leaving presentation semantics only in
   Worker memory.
4. A managed yt-dlp result is no longer trusted merely because yt-dlp returned a filename. Worker
   containment verifies the returned path is an existing regular file inside the dedicated output
   root before it can be offered as staged output.
5. YouTube's current EJS dependency is treated as executable/runtime supply chain. V10 uses the pinned
   local EJS package and deliberately does not enable npm/GitHub remote component downloads.

## Verification

```text
python -m compileall -q src tests tools    PASS
PYTHONPATH=src pytest -q                    191 passed
```

Real source-environment media integration:

```text
local HTTP video/audio                      PASS
DirectHTTP transfers                        PASS
FFmpeg 7.1.5 stream-copy merge              PASS
ffprobe video+audio verification             PASS
Core prepare/perform/finalize FileCommit    PASS
bad-media postprocess -> zero commit         PASS
```

Collection stress:

```text
items                                       5,000
batch size                                    500
batches                                        10
memberships                                 5,000
SQLite integrity_check                        ok
elapsed in this container                  ~0.166 s
```

Cumulative inherited process isolation remains covered by the Sprint 3 real Worker subprocess tests,
including ten sequential authenticated Worker lifecycles with no open session left behind. Concrete
media adapters remain Worker-only by architecture tests.

## Dependency/runtime validation boundary

The official latest stable release identified for this Sprint is yt-dlp 2026.08.19. The source pin
uses the official release tarball SHA-256. The current container cannot resolve external dependency
hosts, so `uv lock` and the actual yt-dlp/EJS/Deno runtime smoke cannot be executed here. The attempted
`uv lock` failed at DNS resolution before dependency installation; no fabricated lock is included.

FFmpeg and ffprobe are installed locally and their actual execution is included in tests. Live remote
media sites are deliberately not used as deterministic release tests.

## Deferred to later milestones

- Static Web / Browser Assist and advanced postprocess: Sprint 8;
- final media/UI detail and collection execution UX: Sprint 9;
- native Windows Supervisor / Job Object / production QLocal: Sprint 10;
- frozen packaging and installer: Sprint 11;
- immutable App/Engine Pack updater and rollback: Sprint 12;
- migration/reliability hardening: Sprint 13;
- Windows live/fault/soak RC gates: Sprint 14.
