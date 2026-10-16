param(
    [Parameter(Mandatory = $true)]
    [string]$StartScript
)

$ErrorActionPreference = "Stop"
$listener = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $listener) {
    exit 0
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
if (-not $process -or $process.Name -notin @("python.exe", "pythonw.exe")) {
    exit 2
}

$expectedStartScript = [IO.Path]::GetFullPath($StartScript)
if ([string]::IsNullOrWhiteSpace($process.CommandLine) -or
    $process.CommandLine.IndexOf($expectedStartScript, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
    exit 3
}

Stop-Process -Id $process.ProcessId -Force
Wait-Process -Id $process.ProcessId -Timeout 5 -ErrorAction SilentlyContinue
