# Internal launcher for the Windows GUI MCP service.
#
# Invoked by Task Scheduler via:
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File _launch-win-device.ps1
#
# We deliberately use python.exe (not pythonw.exe). pythonw binds std{in,out,err}
# to NUL, which breaks uvicorn / FastMCP startup on Windows. Instead, the parent
# powershell.exe is launched with -WindowStyle Hidden by Task Scheduler; python.exe
# inherits that hidden console, so it has real std handles for uvicorn but no
# visible window for the user.
#
# All stdout / stderr is appended to <repo>/platforms/windows/logs/windows-gui.log
# so silent failures are debuggable.
#
# RESTART LOOP (since v0.2.1):
# Task Scheduler's -RestartCount only fires when the task action itself exits
# non-zero. But Windows can kill our python.exe externally (session lock,
# modern standby, log-off, OOM) producing exit code 1067 (ERROR_PROCESS_ABORTED)
# yet the task is then marked failed and never retries because the AtLogOn
# trigger doesn't re-fire on lock/unlock. To survive these system events we
# wrap python.exe in a launcher-internal while-loop that respawns it within
# a few seconds. Rapid-fail safety: if python crashes 3 times within 6
# seconds (config error, missing dep, port conflict) we give up so failures
# stay observable rather than thrashing forever.
#
# Not for direct user invocation.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$PlatformDir = Split-Path -Parent $PSScriptRoot
$ServerDir   = Join-Path $PlatformDir "server"
$LogsDir     = Join-Path $PlatformDir "logs"
$null = New-Item -ItemType Directory -Path $LogsDir -Force -ErrorAction SilentlyContinue

$Python = Join-Path $ServerDir ".venv\Scripts\python.exe"
$Server = Join-Path $ServerDir "windows_gui_mcp.py"
$Log    = Join-Path $LogsDir "windows-gui.log"

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

# Rapid-fail detection (config error vs benign external kill).
$rapidFailWindow = 6
$rapidFailLimit  = 3
$rapidFailCount  = 0
$rapidFailStart  = $null

try {
    while ($true) {
        $startedAt = Get-Date
        # *>&1 merges all streams to stdout; Out-File -Encoding utf8 forces UTF-8.
        # The naive `*>> $Log` shortcut writes UTF-16 LE on PowerShell 5.1
        # (Out-File's default encoding there), which mojibakes the log.
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
                "$(Get-Date -Format o) FATAL: python crashed $rapidFailCount times in $rapidFailWindow seconds -- giving up to keep failure observable" |
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
