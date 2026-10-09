$ErrorActionPreference = "Stop"
if (-not $IsWindows) { throw "Sprint 10 Windows runtime gate requires Windows." }
uv sync --extra dev --extra gui --extra engines
uv run python tools\sprint10_windows_handle_probe.py
uv run python tools\sprint10_windows_runtime_smoke.py
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Rust cargo is required for Native Supervisor gate." }
cargo test --manifest-path native\supervisor\Cargo.toml --release
cargo build --manifest-path native\supervisor\Cargo.toml --release
Write-Host "SPRINT10 WINDOWS RUNTIME SOURCE GATES: PASS"
