$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found on PATH.'
}

$probe = @'
import platform, struct, sys, sysconfig
ok = (
    sys.version_info[:2] == (3, 13)
    and struct.calcsize("P") * 8 == 64
    and sysconfig.get_config_var("Py_GIL_DISABLED") != 1
)
print(f"Python={sys.version.split()[0]} arch={platform.machine()} gil_disabled={sysconfig.get_config_var('Py_GIL_DISABLED')}")
raise SystemExit(0 if ok else 2)
'@

$probe | python -
if ($LASTEXITCODE -ne 0) {
    throw 'Booru Studio V10 production development baseline requires 64-bit GIL-enabled CPython 3.13.x.'
}

uv lock
uv sync --extra dev --extra gui --extra engines
Write-Host 'Development environment is ready.'
