# Internal launcher for the desktop-commander MCP service.
#
# Invoked by Task Scheduler via:
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File _launch-desktop-commander.ps1
#
# All stdout / stderr is appended to <repo>/platforms/windows/logs/desktop-commander.log
# so silent failures are debuggable.
#
# Not for direct user invocation.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$PlatformDir = Split-Path -Parent $PSScriptRoot
$LogsDir     = Join-Path $PlatformDir "logs"
$null = New-Item -ItemType Directory -Path $LogsDir -Force -ErrorAction SilentlyContinue
$Log = Join-Path $LogsDir "desktop-commander.log"

"=== $(Get-Date -Format o) launcher starting (pid=$PID) ===" | Out-File -FilePath $Log -Append -Encoding utf8

try {
    # Use globally installed binaries (npm -g via setup-windows.ps1) instead of
    # 'npx -y'. 'npx -y' extracts into a per-run cache that races with itself
    # when Task Scheduler retries fast (ENOTEMPTY rename errors).
    & supergateway `
        --stdio "desktop-commander" `
        --port 8765 `
        --baseUrl http://0.0.0.0:8765 `
        --ssePath /sse `
        --messagePath /message `
        --healthEndpoint /healthz `
        --logLevel info *>> $Log
    $code = $LASTEXITCODE
    "$(Get-Date -Format o) supergateway exited with code $code" | Out-File -FilePath $Log -Append -Encoding utf8
    exit $code
} catch {
    "$(Get-Date -Format o) launcher exception: $($_.Exception.Message)" | Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
}
