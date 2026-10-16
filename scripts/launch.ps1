$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopApp = Join-Path $projectRoot "dist\MyVocabulary-current\MyVocabulary.exe"
if (-not (Test-Path -LiteralPath $desktopApp -PathType Leaf)) {
    throw "桌面应用尚未构建。请先运行 scripts\build_desktop_app.ps1。"
}

Start-Process -FilePath $desktopApp -WorkingDirectory $projectRoot
