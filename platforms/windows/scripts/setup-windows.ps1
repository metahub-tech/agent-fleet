# agent-test-bench / Windows platform setup
#
# Run from inside the cloned repo as Administrator:
#   cd <repo-root>
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\setup-windows.ps1
#
# What this does:
#   1. verify Tailscale is logged in
#   2. install Python 3.12 + Node.js LTS if missing
#   3. create a Python venv inside server/ and install requirements
#   4. open firewall ports 8765 / 8766 only on the Tailscale interface
#   5. register Task Scheduler tasks for the two MCP services (auto-start at logon)
#   6. start services and verify they listen
#
# Idempotent: re-run is safe.
#
# NOTE FOR CONTRIBUTORS: Keep this script ASCII / English only.
# Windows PowerShell 5.1 reads .ps1 files using the system code page
# (e.g. GBK on zh-CN Windows) unless a UTF-8 BOM is present, so any
# non-ASCII text here will be mojibake-parsed and break the script.
# Localized output belongs in docs, not in this file.

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

# Force UTF-8 for external command stdout. Windows PowerShell 5.1 defaults to the system
# OEM code page (GBK on zh-CN, etc.), which mangles non-ASCII characters in tool output.
# Notably 'tailscale status --json' embeds account display names that may contain Chinese.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

# Auto-discover paths relative to this script (works no matter where the repo lives)
$ScriptDir  = $PSScriptRoot
$WindowsDir = Split-Path -Parent $ScriptDir
$ServerDir  = Join-Path $WindowsDir "server"
$VenvDir    = Join-Path $ServerDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ServerPy   = Join-Path $ServerDir "windows_gui_mcp.py"
$ReqTxt     = Join-Path $ServerDir "requirements.txt"
$RepoRoot   = Split-Path -Parent (Split-Path -Parent $WindowsDir)
$RunUser    = $env:USERNAME

Write-Host "=== agent-test-bench / Windows Bridge Setup ===" -ForegroundColor Cyan
Write-Host "Repo  : $RepoRoot"
Write-Host "User  : $RunUser"
Write-Host ""

# ---------- 1. Tailscale ----------
Write-Host "[1/6] Tailscale" -ForegroundColor Yellow
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Host "  installing Tailscale..."
    winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
    Write-Host "  -> Open the Tailscale tray icon, click Login, then come back." -ForegroundColor Magenta
    Read-Host "  Press Enter to continue"
}
$tsRaw = tailscale status --json 2>$null
if (-not $tsRaw) {
    Write-Host "  'tailscale status --json' returned nothing. Is the Tailscale service running?" -ForegroundColor Red
    exit 1
}
try {
    $tsStatus = $tsRaw | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-Host "  Failed to parse 'tailscale status --json':" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  This usually means a console encoding mismatch. If you are on PowerShell 5.1," -ForegroundColor Red
    Write-Host "  consider upgrading to PowerShell 7+: winget install Microsoft.PowerShell" -ForegroundColor Red
    exit 1
}
if (-not $tsStatus.Self -or -not $tsStatus.Self.HostName) {
    Write-Host "  Tailscale is not logged in. Open the tray icon, click Login, then re-run this script." -ForegroundColor Red
    exit 1
}
$tsHost = $tsStatus.Self.HostName
$tsDNS  = $tsStatus.Self.DNSName.TrimEnd('.')
Write-Host "  ok logged in"
Write-Host "     hostname : $tsHost"
Write-Host "     fqdn     : $tsDNS"

# ---------- 2. Python 3.10+ ----------
Write-Host ""
Write-Host "[2/6] Python 3.10+" -ForegroundColor Yellow
function Test-PythonOk {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { return $false }
    $v = (python --version 2>&1)
    if ($v -match "Python (\d+)\.(\d+)\.") {
        return ([int]$Matches[1] -gt 3) -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10)
    }
    return $false
}
if (Test-PythonOk) {
    Write-Host "  ok $((python --version 2>&1))"
} else {
    Write-Host "  installing Python 3.12..."
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Test-PythonOk)) {
        Write-Host "  Python installed but not on PATH; open a new PowerShell and re-run this script." -ForegroundColor Red
        exit 1
    }
    Write-Host "  ok $((python --version 2>&1))"
}

# ---------- 3. Node.js LTS ----------
Write-Host ""
Write-Host "[3/6] Node.js LTS" -ForegroundColor Yellow
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "  installing Node.js LTS..."
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path","User")
}
Write-Host "  ok node $(node -v)"

# ---------- 4. Python venv + dependencies ----------
Write-Host ""
Write-Host "[4/6] GUI MCP venv + deps" -ForegroundColor Yellow
if (-not (Test-Path $VenvDir)) {
    Write-Host "  creating venv: $VenvDir"
    python -m venv $VenvDir
} else {
    Write-Host "  venv exists: $VenvDir"
}
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r $ReqTxt
Write-Host "  ok"

# ---------- 5. Firewall (Tailscale interface only) ----------
Write-Host ""
Write-Host "[5/6] Firewall" -ForegroundColor Yellow
$tsAdapter = Get-NetAdapter | Where-Object { $_.InterfaceDescription -like "*Tailscale*" } | Select-Object -First 1

# Clean old rules first (idempotent re-run)
Get-NetFirewallRule -DisplayName "MCP DesktopCommander*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName "MCP WindowsGui*"        -ErrorAction SilentlyContinue | Remove-NetFirewallRule

if ($tsAdapter) {
    New-NetFirewallRule -DisplayName "MCP DesktopCommander (Tailscale)" `
        -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow `
        -InterfaceAlias $tsAdapter.Name | Out-Null
    New-NetFirewallRule -DisplayName "MCP WindowsGui (Tailscale)" `
        -Direction Inbound -Protocol TCP -LocalPort 8766 -Action Allow `
        -InterfaceAlias $tsAdapter.Name | Out-Null
    Write-Host "  ok 8765/8766 allowed on $($tsAdapter.Name)"
} else {
    Write-Warning "  Tailscale interface not found. Allowing all interfaces (insecure); re-run this script after Tailscale is up to tighten."
    New-NetFirewallRule -DisplayName "MCP DesktopCommander (TEMP-ALL)" `
        -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow | Out-Null
    New-NetFirewallRule -DisplayName "MCP WindowsGui (TEMP-ALL)" `
        -Direction Inbound -Protocol TCP -LocalPort 8766 -Action Allow | Out-Null
}

# ---------- 6. Task Scheduler ----------
Write-Host ""
Write-Host "[6/6] Auto-start tasks (run at logon for $RunUser)" -ForegroundColor Yellow

$dcAction = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument '/c npx -y supergateway --stdio "npx -y @wonderwhy-er/desktop-commander" --port 8765 --baseUrl http://0.0.0.0:8765 --ssePath /sse --messagePath /message'
$dcTrigger = New-ScheduledTaskTrigger -AtLogOn -User $RunUser
$dcSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MCP-DesktopCommander" -Action $dcAction -Trigger $dcTrigger `
    -Settings $dcSettings -RunLevel Highest -User $RunUser -Force | Out-Null

$guiAction = New-ScheduledTaskAction `
    -Execute  $VenvPython `
    -Argument $ServerPy `
    -WorkingDirectory $ServerDir
$guiTrigger = New-ScheduledTaskTrigger -AtLogOn -User $RunUser
$guiSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MCP-WindowsGui" -Action $guiAction -Trigger $guiTrigger `
    -Settings $guiSettings -RunLevel Highest -User $RunUser -Force | Out-Null
Write-Host "  ok MCP-DesktopCommander, MCP-WindowsGui registered"

# ---------- Start now & verify ----------
Write-Host ""
Write-Host "=== Starting services (first run may take 30-60s while npx downloads packages) ===" -ForegroundColor Cyan
Start-ScheduledTask -TaskName "MCP-DesktopCommander"
Start-ScheduledTask -TaskName "MCP-WindowsGui"

$deadline = (Get-Date).AddSeconds(60)
$dcOk = $false; $guiOk = $false
while ((Get-Date) -lt $deadline -and -not ($dcOk -and $guiOk)) {
    Start-Sleep -Seconds 3
    $dcOk  = $null -ne (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
    $guiOk = $null -ne (Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)
}
if ($dcOk)  { Write-Host "  ok desktop-commander listening on 8765" -ForegroundColor Green }
else        { Write-Host "  WARN desktop-commander not yet on 8765 (run: Get-ScheduledTaskInfo MCP-DesktopCommander)" -ForegroundColor Yellow }
if ($guiOk) { Write-Host "  ok windows-gui        listening on 8766" -ForegroundColor Green }
else        { Write-Host "  WARN windows-gui not yet on 8766 (run: Get-ScheduledTaskInfo MCP-WindowsGui)"             -ForegroundColor Yellow }

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host ""
Write-Host "Send these to the agent operator (or keep them yourself):"
Write-Host ""
Write-Host "  Tailscale hostname    : $tsHost"
Write-Host "  Tailscale FQDN        : $tsDNS"
Write-Host "  desktop-commander URL : http://${tsHost}:8765/sse"
Write-Host "  windows-gui URL       : http://${tsHost}:8766/sse"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  - Agent host config : see docs/agent-host-setup.md"
Write-Host "  - GUI tests require '$RunUser' to remain logged in. Enable auto-login"
Write-Host "    after reboot via 'netplwiz' (uncheck 'Users must enter a user name and password')."
