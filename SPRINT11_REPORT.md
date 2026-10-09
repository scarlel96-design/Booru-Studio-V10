# Sprint 11 Reconstruction Report

## Implemented in this worktree

- Immutable `app-manifest.json` contract with path, case-collision, reserved-name, inventory,
  hash, size, symlink/reparse-point, and entrypoint validation.
- Atomic launcher-owned `install-state.json` store with temporary write, file flush and replace.
- Stable Launcher endpoint handoff: the Launcher creates a single endpoint and supplies it to
  the native Supervisor, which passes the same endpoint to Core.
- Capsule manifest generator, locked Cargo dependency inventory, per-user Inno Setup installer
  source, and explicit Core/Worker Python entrypoints.

## Verification in this environment

- `python -m compileall -q src tests tools`: PASS.
- `pytest -q tests/unit/test_sprint11_capsule_contract.py`: 2 passed.
- `cargo test` in `native/supervisor`: 1 passed.
- Frozen PyInstaller onedir QML smoke: PASS (`BooruStudioQmlSmoke.exe`, exit 0).
- Frozen-QML resource path contract: 2 passed.

## Gate status

Sprint 11 packaging reconstruction is **PARTIAL**. The Frozen QML smoke is now verified, but the
actual build used installed CPython 3.12 / PyInstaller 6.22.1 rather than the required sealed
CPython 3.13.15 toolchain, and the full source suite remains unsealed.

The full source suite is **NOT PASS** in the current Windows/Python 3.12 harness: 14 failed,
217 passed, 13 skipped. The failures predate this Sprint 11 change and include Windows-invalid
`os.fsync()` calls on read-only handles, platform path-separator expectation, and locale-default
UTF-8 decoding. Gate 11.5 reconstruction and Sprint 12 remain unstarted.
