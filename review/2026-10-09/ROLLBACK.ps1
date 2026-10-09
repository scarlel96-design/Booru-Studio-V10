param(
    [Parameter(Mandatory = $true)][string]$TargetDir,
    [Parameter(Mandatory = $true)][string]$PatchFile
)

$ErrorActionPreference = 'Stop'
$git = 'C:\Program Files\Git\cmd\git.exe'
$target = (Resolve-Path -LiteralPath $TargetDir).Path
$patch = (Resolve-Path -LiteralPath $PatchFile).Path
& $git -c core.autocrlf=false -C $target apply --reverse --check $patch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $git -c core.autocrlf=false -C $target apply --reverse $patch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$manifest = Join-Path $target 'SOURCE_MANIFEST.sha256'
$contents = [System.IO.File]::ReadAllText($manifest, [System.Text.Encoding]::UTF8)
$contents = $contents -replace "`r?`n", "`r`n"
[System.IO.File]::WriteAllText($manifest, $contents, [System.Text.UTF8Encoding]::new($false))
Write-Output 'ROLLBACK_APPLIED'
