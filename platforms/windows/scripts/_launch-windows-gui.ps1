# Internal launcher for the Windows GUI MCP service.
#
# Invoked by Task Scheduler via:
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File _launch-windows-gui.ps1
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

try {
    & $Python $Server *>> $Log
    $code = $LASTEXITCODE
    "$(Get-Date -Format o) python exited with code $code" | Out-File -FilePath $Log -Append -Encoding utf8
    exit $code
} catch {
    "$(Get-Date -Format o) launcher exception: $($_.Exception.Message)" | Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
}
