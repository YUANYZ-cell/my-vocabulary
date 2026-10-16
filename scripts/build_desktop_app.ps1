param([switch]$Check)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopProject = Join-Path $projectRoot "desktop\MyVocabulary.Desktop\MyVocabulary.Desktop.csproj"
$publishDirectory = Join-Path $projectRoot "dist\MyVocabulary-current"
$desktopApp = Join-Path $publishDirectory "MyVocabulary.exe"

if ($Check) {
    if (-not (Test-Path -LiteralPath $desktopApp -PathType Leaf)) {
        throw "桌面应用尚未构建：$desktopApp"
    }
    $item = Get-Item -LiteralPath $desktopApp
    Write-Output "桌面应用验证通过：$desktopApp"
    Write-Output "大小：$($item.Length) bytes"
    Write-Output "SHA256：$((Get-FileHash -Algorithm SHA256 -LiteralPath $desktopApp).Hash)"
    exit 0
}

if (-not (Get-Command "dotnet.exe" -ErrorAction SilentlyContinue)) {
    throw "未找到 .NET SDK，无法构建桌面应用。"
}

New-Item -ItemType Directory -Path $publishDirectory -Force | Out-Null
dotnet publish $desktopProject -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o $publishDirectory
if ($LASTEXITCODE -ne 0) {
    throw "桌面应用构建失败，退出码：$LASTEXITCODE"
}

& $PSCommandPath -Check
