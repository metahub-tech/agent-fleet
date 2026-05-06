# Internal launcher for the desktop-commander MCP service.
#
# Invoked by Task Scheduler via:
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File _launch-desktop-commander.ps1
#
# Architecture: mcp-proxy (Python, sparfenyuk/mcp-proxy) bridges the
# stdio MCP server 'desktop-commander' (Node, npm-global) to a SSE endpoint
# at 0.0.0.0:8765/sse. Replaced the prior supergateway-based bridge after
# hitting four separate supergateway issues (IPv6-only bind, npx cache
# races, swallowed child stderr, and the show-stopper "Already connected
# to a transport" crash on every Claude Code SSE reconnect).
#
# Why mcp-proxy instead of supergateway:
#  - Native --sse-host flag binds 0.0.0.0 directly (no netsh portproxy).
#  - Reuses the same Python venv we already maintain for windows-gui.
#  - Designed to handle SSE clients reconnecting (supergateway was not).
#  - Python ecosystem has better logging hygiene than the npm chain.
#
# Output is appended to <repo>/platforms/windows/logs/desktop-commander.log
# using UTF-8 explicitly (avoids the PS5.1 default UTF-16 redirect that
# made the log unreadable in earlier versions).
#
# Not for direct user invocation.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$PlatformDir = Split-Path -Parent $PSScriptRoot
$ServerDir   = Join-Path $PlatformDir "server"
$VenvDir     = Join-Path $ServerDir ".venv"
$VenvPython  = Join-Path $VenvDir "Scripts\python.exe"
$LogsDir     = Join-Path $PlatformDir "logs"
$null = New-Item -ItemType Directory -Path $LogsDir -Force -ErrorAction SilentlyContinue
$Log = Join-Path $LogsDir "desktop-commander.log"

"=== $(Get-Date -Format o) launcher starting (pid=$PID) ===" |
    Out-File -FilePath $Log -Append -Encoding utf8

try {
    # mcp-proxy --sse-host 0.0.0.0 --sse-port 8765 -- desktop-commander
    # Append both stdout and stderr to the log via Tee-Object with explicit
    # UTF-8 (default redirect on PS5.1 would write UTF-16, mojibake-ing the
    # mixed-encoding log).
    & $VenvPython -m mcp_proxy `
        --sse-host 0.0.0.0 `
        --sse-port 8765 `
        --log-level INFO `
        -- desktop-commander 2>&1 |
        Tee-Object -FilePath $Log -Append | Out-Null
    $code = $LASTEXITCODE
    "$(Get-Date -Format o) mcp-proxy exited with code $code" |
        Out-File -FilePath $Log -Append -Encoding utf8
    exit $code
} catch {
    "$(Get-Date -Format o) launcher exception: $($_.Exception.Message)" |
        Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
}
