# agent-fleet / Windows platform setup
#
# Run from inside the cloned repo as Administrator:
#   cd <repo-root>
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\setup-windows.ps1
#
# What this does (5 steps):
#   1. verify Tailscale is logged in
#   2. install Python 3.12 if missing
#   3. create a Python venv inside server/ and install requirements
#   4. open firewall port 8766 only on the Tailscale interface
#   5. register Task Scheduler task MCP-WinDevice (auto-start at logon)
#   6. start service and verify it listens
#
# Idempotent: re-run is safe.
#
# History note: earlier versions had a second service MCP-DesktopCommander
# on port 8765 (mcp-proxy + npm desktop-commander). That stack hit several
# single-client / npm cache / network issues, so it was consolidated into
# MCP-WinDevice (FastMCP, multi-client native). This script will clean
# up old artifacts (npm globals, scheduled task, firewall rule, portproxy)
# if they exist from previous runs.
#
# NOTE FOR CONTRIBUTORS: Keep this script ASCII / English only.
# Windows PowerShell 5.1 reads .ps1 files using the system code page
# (e.g. GBK on zh-CN Windows) unless a UTF-8 BOM is present, so any
# non-ASCII text here will be mojibake-parsed and break the script.
# Localized output belongs in docs, not in this file.

# Admin elevation is NO LONGER required at the script level.  The script
# runs entirely with current-user permissions EXCEPT for one optional
# step: `New-NetFirewallRule` (for inbound 8766 from Tailscale).  That
# call is now wrapped in try-catch with a graceful WARN — if you skip
# admin and the firewall rule fails, the only impact is that other
# Tailscale nodes might be blocked by Windows Defender Firewall (Private
# profile usually allows by default, so often a non-issue).  To get the
# firewall rule installed, re-run install.ps1 from an admin PowerShell.

$ErrorActionPreference = "Stop"

# Force UTF-8 for external command stdout. Windows PowerShell 5.1 defaults to
# the system OEM code page (GBK on zh-CN, etc.), which mangles non-ASCII in
# tool output. 'tailscale status --json' embeds account display names that
# may contain CJK.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

# Auto-discover paths relative to this script (works from any clone location).
$ScriptDir  = $PSScriptRoot
$WindowsDir = Split-Path -Parent $ScriptDir
$ServerDir  = Join-Path $WindowsDir "server"
$VenvDir    = Join-Path $ServerDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ServerPy   = Join-Path $ServerDir "win_device_mcp.py"
$ReqTxt     = Join-Path $ServerDir "requirements.txt"
$RepoRoot   = Split-Path -Parent (Split-Path -Parent $WindowsDir)
$RunUser    = $env:USERNAME

Write-Host "=== agent-fleet / Windows Bridge Setup ===" -ForegroundColor Cyan
Write-Host "Repo  : $RepoRoot"
Write-Host "User  : $RunUser"
Write-Host ""

# ---------- 0. Cleanup legacy desktop-commander / mcp-proxy stack ----------
# Older versions of this repo ran a second MCP service on port 8765 backed by
# the npm package @wonderwhy-er/desktop-commander wrapped by mcp-proxy. We've
# folded those tools into win_device_mcp.py; remove the old artifacts.

Write-Host "[0/5] Cleanup legacy MCP-DesktopCommander stack (if present)" -ForegroundColor DarkYellow
Stop-ScheduledTask -TaskName "MCP-DesktopCommander" -ErrorAction SilentlyContinue
$dcTask = Get-ScheduledTask -TaskName "MCP-DesktopCommander" -ErrorAction SilentlyContinue
if ($dcTask) {
    Unregister-ScheduledTask -TaskName "MCP-DesktopCommander" -Confirm:$false
    Write-Host "  removed scheduled task MCP-DesktopCommander"
}
Get-NetFirewallRule -DisplayName "MCP DesktopCommander*" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-NetFirewallRule -InputObject $_
    Write-Host "  removed firewall rule $($_.DisplayName)"
}
$null = netsh interface portproxy delete v4tov6 listenport=8765 listenaddress=0.0.0.0 2>$null
if (Get-Command desktop-commander -ErrorAction SilentlyContinue) {
    Write-Host "  uninstalling old npm package @wonderwhy-er/desktop-commander..."
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & npm uninstall -g @wonderwhy-er/desktop-commander *>&1 | Out-Null
    $ErrorActionPreference = $prevEAP
}
if (Get-Command supergateway -ErrorAction SilentlyContinue) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & npm uninstall -g supergateway *>&1 | Out-Null
    $ErrorActionPreference = $prevEAP
    Write-Host "  uninstalled stale supergateway global"
}
$DcLauncher = Join-Path $ScriptDir "_launch-desktop-commander.ps1"
if (Test-Path $DcLauncher) {
    Remove-Item $DcLauncher -Force
    Write-Host "  removed _launch-desktop-commander.ps1"
}
Write-Host "  ok"

# ---------- 1. Tailscale ----------
Write-Host ""
Write-Host "[1/5] Tailscale" -ForegroundColor Yellow
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Host "  installing Tailscale..."
    winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
    Write-Host "  -> Open the Tailscale tray icon, click Login, then come back." -ForegroundColor Magenta
    if ($env:ATB_WIZARD_MANAGED -eq "1") {
        # Under the wizard, stdout is a pipe — a Read-Host prompt would hang
        # invisibly. Exit cleanly instead; the wizard surfaces the rc=1 and the
        # message above tells the user to log in to Tailscale and re-run.
        Write-Host "  Tailscale was just installed. Log in via the tray icon, then re-run the wizard." -ForegroundColor Yellow
        exit 1
    }
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
$tsDNS  = $tsStatus.Self.DNSName.TrimEnd('.')
# MagicDNS short name (first label of DNSName), not Self.HostName: HostName is
# the OS computer name and goes stale after an admin-console device rename —
# only DNSName tracks the rename, and that's what other tailnet nodes resolve.
$tsHost = ($tsDNS -split '\.')[0]
Write-Host "  ok logged in"
Write-Host "     hostname : $tsHost"
Write-Host "     fqdn     : $tsDNS"

# ---------- 2. Python 3.10+ ----------
Write-Host ""
Write-Host "[2/5] Python 3.10+" -ForegroundColor Yellow
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

# ---------- 3. Python venv + dependencies ----------
Write-Host ""
Write-Host "[3/5] win-device venv + deps" -ForegroundColor Yellow
if (-not (Test-Path $VenvDir)) {
    Write-Host "  creating venv: $VenvDir"
    python -m venv $VenvDir
} else {
    Write-Host "  venv exists: $VenvDir"
}
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r $ReqTxt
Write-Host "  ok"

# ---------- 4. Firewall ----------
Write-Host ""
Write-Host "[4/5] Firewall" -ForegroundColor Yellow

# Firewall rule (only succeeds as admin — gracefully degrade for non-admin).
# Filter by Tailscale's CGNAT IPv4 (100.64.0.0/10) and Tailscale ULA IPv6
# prefix (fd7a:115c:a1e0::/48). IP-range matching survives Tailscale service
# restarts (interface GUID changes) and is tighter than adapter binding.
$tsRanges = @("100.64.0.0/10", "fd7a:115c:a1e0::/48")
try {
    Get-NetFirewallRule -DisplayName "MCP WindowsGui*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "MCP WinDevice (Tailscale)" `
        -Direction Inbound -Protocol TCP -LocalPort 8766 -Action Allow `
        -RemoteAddress $tsRanges -ErrorAction Stop | Out-Null
    Write-Host "  ok 8766 allowed from Tailscale IPv4 100.64.0.0/10 + IPv6 fd7a:115c:a1e0::/48"
} catch {
    Write-Host "  WARN: could not create firewall rule (need admin PowerShell)." -ForegroundColor Yellow
    Write-Host "        Skipping.  If another Tailscale node can't reach this PC on 8766," -ForegroundColor Yellow
    Write-Host "        re-run install.ps1 from an admin PowerShell, OR add manually:" -ForegroundColor Yellow
    Write-Host "          New-NetFirewallRule -DisplayName 'MCP WinDevice (Tailscale)' \`" -ForegroundColor Yellow
    Write-Host "            -Direction Inbound -Protocol TCP -LocalPort 8766 -Action Allow \`" -ForegroundColor Yellow
    Write-Host "            -RemoteAddress 100.64.0.0/10,fd7a:115c:a1e0::/48" -ForegroundColor Yellow
}

# ---------- 5. Task Scheduler ----------
Write-Host ""
Write-Host "[5/5] Auto-start task (run at logon for $RunUser, hidden)" -ForegroundColor Yellow

# Stop existing instance so we can re-register cleanly.
Stop-ScheduledTask -TaskName "MCP-WinDevice" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Kill leftover python.exe holding port 8766 (from prior visible-window run
# or stale launcher).
# IMPORTANT: filter by process name -- never blanket-kill listeners on a port
# because system-level listeners (svchost-hosted services) would crash all
# co-hosted services.
$ourProcessNames = @("python", "powershell", "cmd")
Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $owner = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and ($ourProcessNames -contains $owner.Name)) {
        try { Stop-Process -Id $owner.Id -Force -ErrorAction Stop } catch {}
    }
}

$GuiLauncher = Join-Path $ScriptDir "_launch-win-device.ps1"
if (-not (Test-Path $GuiLauncher)) {
    Write-Host "  ERROR: launcher missing: $GuiLauncher" -ForegroundColor Red
    exit 1
}

$commonSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew

$guiAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$GuiLauncher`""

# Migrate / cleanup: remove the legacy MCP-WindowsGui task if present.
# CIM cmdlets emit non-terminating errors by default that don't trip
# $ErrorActionPreference="Stop", so we must wrap explicitly to know if
# the unregister actually worked (instead of misleadingly echoing "removed").
$legacyTaskName = "MCP-WindowsGui"
$legacyTask = Get-ScheduledTask -TaskName $legacyTaskName -ErrorAction SilentlyContinue
if ($legacyTask) {
    try {
        Stop-ScheduledTask -TaskName $legacyTaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $legacyTaskName -Confirm:$false -ErrorAction Stop
        Write-Host "  removed legacy task $legacyTaskName" -ForegroundColor Yellow
    } catch {
        Write-Host "  ERROR: could not unregister legacy task $legacyTaskName" -ForegroundColor Red
        Write-Host "         (was originally admin-scoped; need admin PowerShell)" -ForegroundColor Red
        Write-Host "         Detail: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

try {
    # 登录自启 + 每 5 分钟 self-heal 兜底（锁屏/休眠/注销后整条 launcher 死掉时，
    # AtLogOn 不重触发；周期触发器在 ~5min 内重新拉起，配合 launcher kill-stale 避端口冲突）。
    $winTriggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $RunUser),
        (New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue))
    )
    Register-ScheduledTask -TaskName "MCP-WinDevice" -Action $guiAction `
        -Trigger $winTriggers `
        -Settings $commonSettings -RunLevel Highest -User $RunUser -Force `
        -ErrorAction Stop | Out-Null
    Write-Host "  ok MCP-WinDevice registered (hidden, logged, auto-restart on failure)"
} catch {
    Write-Host "  ERROR: Register-ScheduledTask failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "         Run this script from an admin PowerShell." -ForegroundColor Red
    exit 1
}

# ---------- Start now & verify ----------
Write-Host ""
Write-Host "=== Starting service ===" -ForegroundColor Cyan
Start-ScheduledTask -TaskName "MCP-WinDevice"

$deadline = (Get-Date).AddSeconds(30)
$guiOk = $false
while ((Get-Date) -lt $deadline -and -not $guiOk) {
    Start-Sleep -Seconds 2
    $guiOk = $null -ne (Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)
}
if ($guiOk) {
    Write-Host "  ok win-device listening on 8766" -ForegroundColor Green
} else {
    Write-Host "  WARN win-device not yet on 8766 (run: Get-ScheduledTaskInfo MCP-WinDevice)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host ""
Write-Host "Send these to the agent operator (or keep them yourself):"
Write-Host ""
Write-Host "  Tailscale hostname : $tsHost"
Write-Host "  Tailscale FQDN     : $tsDNS"
Write-Host "  win-device URL      : http://${tsHost}:8766/mcp"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  - Agent host config : see docs/agent-host-setup.md"
Write-Host "  - GUI tests require '$RunUser' to remain logged in. Enable auto-login"
Write-Host "    after reboot via 'netplwiz' (uncheck 'Users must enter a user name and password')."
