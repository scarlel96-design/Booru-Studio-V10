$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found on PATH. Run tools\bootstrap_dev.ps1 first.'
}

uv run python -m compileall -q src tests tools
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run ruff check src tests tools
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run python -m mypy src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run python -c "import PySide6"
if ($LASTEXITCODE -eq 0) {
    uv run python tools\sprint5_qml_smoke.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    throw 'PySide6 GUI extra is missing; Sprint 5 QML runtime smoke gate cannot run.'
}

Write-Host '[QA] Sprint 5 QML runtime smoke passed.'

Write-Host '[QA] Sprint 6 gallery-dl runtime smoke'
uv run python tools\sprint6_gallery_runtime_smoke.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '[QA] Sprint 7 yt-dlp + FFmpeg runtime smoke'
uv run python tools\sprint7_media_runtime_smoke.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '[QA] Sprint 8 Playwright + installed Edge runtime/security smoke'
uv run python tools\sprint8_browser_runtime_smoke.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '[QA] Sprint 10 Windows QLocal/HANDLE/Native Supervisor gates'
& tools\sprint10_windows_runtime_smoke.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'Sprint 10 cumulative QA passed, including QML, engines, browser, Windows QLocal/HANDLE and Native Supervisor source gates.' 
