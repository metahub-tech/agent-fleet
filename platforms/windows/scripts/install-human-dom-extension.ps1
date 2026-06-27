# install-human-dom-extension.ps1
#
# One-time install of the human_dom Chrome extension into a real Chrome profile
# (Developer mode -> Load unpacked).
#
# Profile-routed: each profile gets its own extension copy with the bridge PORT
# and profile_id baked into content.js, so multiple profiles never cross-wire.
# Install target dir: %USERPROFILE%\.fleet\human-dom-ext\<profile_id>\
#
# Usage (run from inside the cloned repo, or with an absolute path):
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\install-human-dom-extension.ps1
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\install-human-dom-extension.ps1 "<PROFILE>"
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\install-human-dom-extension.ps1 "<PROFILE>" <MCP_PORT>
#
# <PROFILE> is the same profile string passed to human_dom_locate. Omit it to
# target the default everyday Chrome (profile_id=default).
#
# <MCP_PORT> is optional and defaults to 8766. If the server was started with a
# non-default --port, pass that mcp_port as the second argument so this script
# reads the matching portfile (and bakes the correct bridge port into the copy).
#
# NOTE FOR CONTRIBUTORS: Keep this script ASCII / English only.
# Windows PowerShell 5.1 reads .ps1 files using the system code page (e.g. GBK
# on zh-CN Windows) unless a UTF-8 BOM is present, so any non-ASCII text here
# would be mojibake-parsed and break the script. Localized output belongs in docs.

# NOTE: do not name this parameter $Profile -- PowerShell has a built-in
# automatic variable $PROFILE (case-insensitive), and a param named $Profile
# would shadow/pollute it, especially when this script is dot-sourced.
param(
    [string]$ChromeProfile = "",
    [int]$McpPort = 8766
)

$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

# Auto-discover repo root relative to this script (works from any clone location).
$ScriptDir  = $PSScriptRoot
$WindowsDir = Split-Path -Parent $ScriptDir
$RepoRoot   = Split-Path -Parent (Split-Path -Parent $WindowsDir)
$CommonDir  = Join-Path $RepoRoot "platforms\common"

# win server default mcp_port (matches Task 9 server default_port); overridable via
# the second arg. Bridge port fallback when the persisted port file is absent =
# mcp_port + 13.
$FleetDir = Join-Path $env:USERPROFILE ".fleet"
$PortFile = Join-Path $FleetDir "dom-bridge-$McpPort.port"

# Resolve a Python launcher: prefer `python`, fall back to the `py` launcher.
function Get-PythonExe {
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
    if (Get-Command py -ErrorAction SilentlyContinue)     { return "py" }
    Write-Host "  ERROR: Python not found on PATH (need python or py launcher)." -ForegroundColor Red
    Write-Host "         Install Python 3.10+ or run setup-windows.ps1 first." -ForegroundColor Red
    exit 1
}
$PyExe = Get-PythonExe

# 1. Compute profile_id ("" -> "default"); install and locate share this logic.
$ProfileId = & $PyExe -c "import sys; sys.path.insert(0, sys.argv[2]); from capabilities.human_dom._ident import human_dom_profile_id; print(human_dom_profile_id(sys.argv[1]))" "$ChromeProfile" "$CommonDir"
if ($LASTEXITCODE -ne 0 -or -not $ProfileId) {
    Write-Host "  ERROR: failed to compute profile_id." -ForegroundColor Red
    exit 1
}
$ProfileId = $ProfileId.Trim()

# 2. Compute bridge_port: prefer the port persisted by the server at startup;
#    fall back to mcp_port + 13 when the file is absent or holds garbage
#    (e.g. a half-written value from a crashed server).
$BridgePort = $McpPort + 13
if (Test-Path $PortFile) {
    $raw = (Get-Content $PortFile -Raw).Trim()
    if ($raw -match '^\d+$') { $BridgePort = [int]$raw }
}

$ExtOut = Join-Path (Join-Path $FleetDir "human-dom-ext") $ProfileId

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  agent-fleet human_dom extension - per-profile install" -ForegroundColor Cyan
Write-Host "====================================================="
Write-Host ""
if ($ChromeProfile) { Write-Host "Target profile : $ChromeProfile" }
else                { Write-Host "Target profile : (default everyday Chrome)" }
Write-Host "profile_id     : $ProfileId"
Write-Host "bridge PORT    : $BridgePort"
Write-Host ""

# 3. Generate the per-profile extension copy (bakes PORT + profile_id, writes meta.json).
#    Use `$null = ...` (not `| Out-Null`) to discard stdout: piping to Out-Null
#    resets $LASTEXITCODE in Windows PowerShell 5.1, which would mask a Python failure.
$null = & $PyExe -c "import sys; sys.path.insert(0, sys.argv[4]); from capabilities.human_dom._setup import prepare_extension; print(prepare_extension(sys.argv[1], int(sys.argv[2]), sys.argv[3]))" `
    "$ExtOut" "$BridgePort" "$ProfileId" "$CommonDir"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: prepare_extension failed." -ForegroundColor Red
    exit 1
}

Write-Host "Extension dir generated (select this dir in Load unpacked):"
Write-Host "  $ExtOut"
Write-Host ""
Write-Host "Steps:"
Write-Host "  1. Open the target Chrome profile (the one human_dom should drive)"
Write-Host "  2. Type  chrome://extensions  in the address bar and press Enter"
Write-Host "  3. Turn on the 'Developer mode' toggle (top right)"
Write-Host "  4. Click 'Load unpacked'"
Write-Host "  5. Select the extension dir listed above, click Open"
Write-Host "  6. 'agent-fleet human_dom locator' appears in the list = installed"
Write-Host ""
Write-Host "Notes:"
Write-Host "  - The extension only reads the DOM; it never clicks/edits the page."
Write-Host "  - PORT and profile_id are baked into this copy; no need to edit content.js."
Write-Host "  - Once loaded, the profile auto-activates it on every launch."
Write-Host ""

# Open the extension dir in Explorer to make the folder easy to select
# (allowed to fail in a non-GUI / headless context).
try { explorer "$ExtOut" } catch {}

# Write the global marker (kept for compatibility: the server statically checks
# whether human_dom has been bootstrapped).
New-Item -ItemType Directory -Force -Path $FleetDir | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $FleetDir "human-dom-ready") | Out-Null

Write-Host "Wrote marker ~/.fleet/human-dom-ready." -ForegroundColor Green
Write-Host ""
Write-Host "After loading the extension:"
Write-Host "  - Reconnect win-device (/mcp reconnect or restart the server); human_dom is enabled."
Write-Host "  - Multiple profiles: re-run this step for each profile, passing the matching"
Write-Host "    PROFILE string, e.g.:"
Write-Host "      powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\install-human-dom-extension.ps1 `"<other PROFILE>`""
