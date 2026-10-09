# Engine dependency policy

## Authority

`pyproject.toml + uv.lock` is the Python dependency authority. Do not introduce a second dependency
truth such as hand-maintained `requirements.txt`, Pipfile or an updater-specific package list.
`uv.lock` is generated and verified on the intended network-enabled Windows build environment; it is
not fabricated in offline source QA.

## Engine packages

External engines are optional runtime capabilities owned by the Worker/Engine Pack layer. Core, UI,
Domain and Persistence never import their concrete packages.

- exact version pins are required inside the Engine extra / Engine Pack manifest;
- a new pin is accepted only after import/runtime smoke, normalizer fixtures and regression tests;
- source QA may run without optional engines; installed-runtime QA must fail closed when the exact pin
  is absent or mismatched;
- production/offline build inputs should come from a verified wheelhouse/artifact set with hashes;
- native tools such as FFmpeg/ffprobe are versioned Engine Pack components, not implicit PATH
  dependencies;
- one JobRun pins one immutable EnginePackId for its entire lifetime.

## Sprint 7 rule

Do not guess or predeclare a yt-dlp version in Gate 6.5. Sprint 7 must select an exact vetted build in
the network-enabled implementation environment, record it in `pyproject.toml`/lock/Engine Pack
metadata, and add a runtime exact-version gate comparable to gallery-dl 1.32.9.

## Sprint 8 rule

- Playwright Python is pinned exactly to `1.62.0` in the Engine dependency set.
- Production Browser Assist uses the installed Microsoft Edge `msedge` channel rather than downloading a private Playwright browser during normal runtime.
- Browser availability/version is fail-closed at the Windows QA/runtime gate; absence never weakens Static/known resolvers.
- No persistent Edge profile is imported into Booru Studio.
