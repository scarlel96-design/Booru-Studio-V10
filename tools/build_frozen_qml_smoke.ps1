param(
    [Parameter(Mandatory = $true)] [string] $Python,
    [string] $OutputRoot = "dist\qml-smoke"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root $OutputRoot
$build = Join-Path $root "build\qml-smoke"
$spec = Join-Path $root "build\qml-smoke-spec"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name "BooruStudioQmlSmoke" `
    --paths (Join-Path $root "src") `
    --distpath $dist `
    --workpath $build `
    --specpath $spec `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtQml `
    --hidden-import PySide6.QtQuick `
    --add-data "$(Join-Path $root 'src\booru_studio\ui\qml');booru_studio\ui\qml" `
    --add-data "$(Join-Path $root 'src\booru_studio\ui\translations');booru_studio\ui\translations" `
    (Join-Path $root "tools\sprint5_qml_smoke.py")
exit $LASTEXITCODE
