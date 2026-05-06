# Internal launcher for the desktop-commander MCP service.
#
# Invoked by Task Scheduler via:
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File _launch-desktop-commander.ps1
#
# Why a separate file: cmd.exe / npx / node are console apps; running them
# directly from Task Scheduler shows a CMD window. Wrapping in a hidden
# powershell.exe -WindowStyle Hidden suppresses the window. Doing this via
# inline -Command argument is brittle due to nested-quote escaping, so the
# launcher lives in its own file.
#
# Not for direct user invocation.

$ErrorActionPreference = "Continue"

# Match the encoding setup of setup-windows.ps1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

& npx -y supergateway `
    --stdio "npx -y @wonderwhy-er/desktop-commander" `
    --port 8765 `
    --baseUrl http://0.0.0.0:8765 `
    --ssePath /sse `
    --messagePath /message
