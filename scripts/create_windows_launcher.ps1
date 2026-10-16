param(
    [switch]$Check,
    [string]$ShortcutPath,
    [string]$AppPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$shortcutPathWasSpecified = -not [string]::IsNullOrWhiteSpace($ShortcutPath)
if ([string]::IsNullOrWhiteSpace($AppPath)) {
    $AppPath = Join-Path $projectRoot "dist\MyVocabulary-current\MyVocabulary.exe"
}
$AppPath = [IO.Path]::GetFullPath($AppPath)
if ([string]::IsNullOrWhiteSpace($ShortcutPath)) {
    $ShortcutPath = Join-Path $projectRoot "我的词汇本.lnk"
}
$ShortcutPath = [IO.Path]::GetFullPath($ShortcutPath)
$shortcutPaths = @($ShortcutPath)
if (-not $shortcutPathWasSpecified) {
    $desktopPath = [Environment]::GetFolderPath('Desktop')
    if (-not [string]::IsNullOrWhiteSpace($desktopPath)) {
        $desktopShortcutPath = [IO.Path]::GetFullPath((Join-Path $desktopPath "我的词汇本.lnk"))
        if (-not [string]::Equals($desktopShortcutPath, $ShortcutPath, [StringComparison]::OrdinalIgnoreCase)) {
            $shortcutPaths += $desktopShortcutPath
        }
    }
}

function Assert-Equal {
    param([string]$Name, [string]$Actual, [string]$Expected)
    if (-not [string]::Equals($Actual, $Expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name 不匹配。实际：$Actual；预期：$Expected"
    }
}

if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
    throw "找不到桌面应用：$AppPath"
}

$shell = New-Object -ComObject WScript.Shell
if ($Check) {
    foreach ($currentShortcutPath in $shortcutPaths) {
        if (-not (Test-Path -LiteralPath $currentShortcutPath -PathType Leaf)) {
            throw "快捷方式不存在：$currentShortcutPath"
        }
        $shortcut = $shell.CreateShortcut($currentShortcutPath)
        Assert-Equal "目标程序" ([IO.Path]::GetFullPath($shortcut.TargetPath)) $AppPath
        Assert-Equal "工作目录" ([IO.Path]::GetFullPath($shortcut.WorkingDirectory)) ([IO.Path]::GetFullPath($projectRoot))
        if (-not [string]::IsNullOrEmpty($shortcut.Arguments)) {
            throw "启动参数应为空。实际：$($shortcut.Arguments)"
        }
        $actualIcon = ($shortcut.IconLocation -split ",")[0]
        Assert-Equal "图标" ([IO.Path]::GetFullPath($actualIcon)) $AppPath
        Write-Output "快捷方式验证通过：$currentShortcutPath"
    }
    exit 0
}

foreach ($currentShortcutPath in $shortcutPaths) {
    $shortcutDirectory = Split-Path -Parent $currentShortcutPath
    if (-not (Test-Path -LiteralPath $shortcutDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $shortcutDirectory -Force | Out-Null
    }
    $shortcut = $shell.CreateShortcut($currentShortcutPath)
    $shortcut.TargetPath = $AppPath
    $shortcut.Arguments = ""
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = "$AppPath,0"
    $shortcut.WindowStyle = 1
    $shortcut.Description = "打开 My Vocabulary / 我的词汇本桌面应用"
    $shortcut.Save()
    Write-Output "已创建快捷方式：$currentShortcutPath"
}
