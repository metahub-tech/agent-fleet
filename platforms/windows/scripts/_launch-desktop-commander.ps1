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

# Restart loop. mcp-proxy 0.11 ties the stdio backend (desktop-commander)
# lifetime to the SSE client session: when the SSE client disconnects, the
# stdio child exits cleanly and mcp-proxy's AsyncExitStack tears down the
# whole proxy with exit code 0. Task Scheduler's -RestartCount only fires
# on non-zero exit, so a benign Claude Code reconnect leaves the service
# permanently dead. We wrap the proxy in our own loop here.
#
# Bail out only if the proxy fails fast (>=3 quick exits within 6 seconds),
# which indicates a real config/dependency error rather than a benign
# client-disconnect cycle.
$rapidFailWindow = 6
$rapidFailLimit  = 3
$rapidFailCount  = 0
$rapidFailStart  = $null

try {
    while ($true) {
        # Use --host/--port (the canonical names). The deprecated aliases
        # --sse-host/--sse-port are silently ignored in mcp-proxy 0.11.0 and
        # the proxy falls back to bind 127.0.0.1:<random>.
        $startedAt = Get-Date
        & $VenvPython -m mcp_proxy `
            --host 0.0.0.0 `
            --port 8765 `
            --log-level INFO `
            -- desktop-commander 2>&1 |
            Tee-Object -FilePath $Log -Append | Out-Null
        $code = $LASTEXITCODE
        $ranFor = ((Get-Date) - $startedAt).TotalSeconds
        "$(Get-Date -Format o) mcp-proxy exited code=$code (ran $([int]$ranFor)s) -- restarting in 3s" |
            Out-File -FilePath $Log -Append -Encoding utf8

        if ($ranFor -lt 2) {
            if (-not $rapidFailStart -or ((Get-Date) - $rapidFailStart).TotalSeconds -gt $rapidFailWindow) {
                $rapidFailStart = Get-Date
                $rapidFailCount = 0
            }
            $rapidFailCount++
            if ($rapidFailCount -ge $rapidFailLimit) {
                "$(Get-Date -Format o) FATAL: mcp-proxy crashed $rapidFailCount times in $rapidFailWindow seconds -- giving up" |
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
