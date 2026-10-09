# Booru Studio V10 — Sprint 8 Web Resolution / Browser Assist Report

## Result
**SOURCE SCOPE COMPLETE.** Final archive seal is recorded separately after clean-room verification.

## Scope completed
- pinned `playwright==1.62.0` in the Engine dependency set;
- added Static Web resolver with bounded HTML parsing and redirect/body/candidate ceilings;
- added network-scope policy that blocks public-page SSRF to localhost/private/link-local/etc and
  rejects mixed public/private DNS answers;
- split "user supplied" from "private network allowed": LAN roots are fail-closed unless an explicit
  opt-in is passed, and then remain exact-origin only;
- added Worker-owned Playwright/installed-Edge observer using a fresh context, blocked Service Workers,
  disabled browser downloads and route-level authorization;
- browser network + DOM observations are normalized and revalidated; Browser Assist is never a
  FileCommit owner;
- Static-first fallback means Browser Assist is invoked only after deterministic static discovery
  returns no media;
- added `WEB_PAGE` collection semantics and opaque durable webpage collection identities;
- added DirectHTTP redirect-time network-scope enforcement for web/browser-derived descriptors;
- added FFmpeg stream-copy remux with ffprobe structural verification;
- added exact-version/Edge runtime smoke gate for Windows development QA.

## Security invariants
- raw signed candidate URLs and browser request details remain Worker-memory objects only;
- diagnostics redact query/fragment/userinfo and never print the private-network root value;
- public page -> private target is denied at observation and candidate handoff, and redirects are
  checked again by DirectHTTP;
- no persistent browser profile, browser-owned download, CSP bypass or remote browser profile reuse;
- Service Workers are blocked because Playwright documents that they can interfere with request
  interception/visibility.

## Verification before seal
```text
python -m compileall -q src tests tools    PASS
PYTHONPATH=src pytest -q                    206 passed
```

Deterministic source integration includes:
- local Static HTML discovery with relative media and signed query tokens;
- `WEB_PAGE` durable collection persistence with zero signed-token leakage into SQLite;
- Static -> Browser fallback contract using a fake Browser backend;
- DirectHTTP private-origin redirect rejection;
- real FFmpeg 7.1.5 remux + ffprobe verification.

## Platform/runtime boundary
The current container has Playwright 1.57.0, not the Sprint-8 pin 1.62.0, and no installed Microsoft
Edge channel. The Sprint-8 runtime smoke therefore correctly fails closed here and is not reported as
an executed Edge E2E. PyPI identifies 1.62.0 (released 2026-07-31) as the latest Playwright Python
release at implementation time. The Windows QA script requires the exact package and installed Edge.

## Static analysis boundary
`ruff` is not installed in this container, so the attempted `ruff check src tests tools` could not be
executed here. `tools/qa.ps1` still requires ruff and mypy in the network-enabled Windows development
environment via the dev extra. No static-analysis PASS is claimed from this container.
