# Internal launcher for the Android GUI MCP service (Windows host).
#
# Invoked by Task Scheduler via:
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File _launch-android.ps1
#
# Same restart-loop pattern as the Windows GUI launcher: the bare
# Task Scheduler -RestartCount doesn't help when Windows kills python
# externally (session lock, modern standby, log-off). We wrap python
# in a while-loop with rapid-fail safety so the service auto-recovers.
#
# All stdout/stderr appends to <repo>/platforms/android/logs/android-device.log
# in UTF-8 (PowerShell 5.1's default file encoding is UTF-16 LE which
# mojibakes the log; we force utf8 explicitly).
#
# Not for direct user invocation. For ad-hoc CLI debugging:
#   .\_launch-android.ps1   (will run interactively in the foreground)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$PlatformDir = Split-Path -Parent $PSScriptRoot
$ServerDir   = Join-Path $PlatformDir "server"
$LogsDir     = Join-Path $PlatformDir "logs"
$null = New-Item -ItemType Directory -Path $LogsDir -Force -ErrorAction SilentlyContinue

$Python = Join-Path $ServerDir ".venv\Scripts\python.exe"
$Server = Join-Path $ServerDir "android_device_mcp.py"
$Log    = Join-Path $LogsDir "android-device.log"

"=== $(Get-Date -Format o) launcher starting (pid=$PID) ===" | Out-File -FilePath $Log -Append -Encoding utf8
"  python = $Python"  | Out-File -FilePath $Log -Append -Encoding utf8
"  server = $Server"  | Out-File -FilePath $Log -Append -Encoding utf8

if (-not (Test-Path $Python)) {
    "  ERROR: python.exe not found at $Python" | Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
}
if (-not (Test-Path $Server)) {
    "  ERROR: server script not found at $Server" | Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
}

# kill-stale：杀掉上一个 launcher 残留、仍在跑本 server 的 python。否则被重启 /
# periodic 触发拉起新实例时，旧进程仍占端口 → 新实例 bind 失败 exit 1 → rapid-fail 放弃。
# 本 launcher 此刻尚未起 python，不会误杀自己的子进程。
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Server*" } |
    ForEach-Object {
        "$(Get-Date -Format o) kill-stale: 杀掉残留 python pid=$($_.ProcessId)" | Out-File -FilePath $Log -Append -Encoding utf8
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Milliseconds 800

$rapidFailWindow = 6
$rapidFailLimit  = 3
$rapidFailCount  = 0
$rapidFailStart  = $null

try {
    while ($true) {
        $startedAt = Get-Date
        & $Python $Server *>&1 | Out-File -FilePath $Log -Append -Encoding utf8
        $code = $LASTEXITCODE
        $ranFor = ((Get-Date) - $startedAt).TotalSeconds
        "$(Get-Date -Format o) python exited code=$code (ran $([int]$ranFor)s) -- restarting in 3s" |
            Out-File -FilePath $Log -Append -Encoding utf8

        if ($ranFor -lt 2) {
            if (-not $rapidFailStart -or ((Get-Date) - $rapidFailStart).TotalSeconds -gt $rapidFailWindow) {
                $rapidFailStart = Get-Date
                $rapidFailCount = 0
            }
            $rapidFailCount++
            if ($rapidFailCount -ge $rapidFailLimit) {
                "$(Get-Date -Format o) FATAL: python crashed $rapidFailCount times in $rapidFailWindow seconds -- giving up" |
                    Out-File -FilePath $Log -Append -Encoding utf8
                exit 1
            }
        } else {
            $rapidFailCount = 0
        }

        Start-Sleep -Seconds 3
    }
} catch {
    "$(Get-Date -Format o) launcher exception: $($_.Exception.Message)" |
        Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
}
