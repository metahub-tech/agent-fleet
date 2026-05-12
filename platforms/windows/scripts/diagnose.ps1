# agent-test-bench / Windows MCP service diagnostic
#
# Read-only checks for triaging "the agent host cannot reach my MCP service."
# Does not require Administrator. Run from anywhere inside the cloned repo:
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\diagnose.ps1
#
# Paste the full output back to the agent operator for triage.
#
# Single-service since v0.2.0 (was 8765 + 8766; now only 8766 win-device).
# Section 0a checks for legacy 8765 / MCP-DesktopCommander leftovers.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

function Section($title) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
}

# ---------- 0. Tailscale daemon (must be up for anything else to matter) ----------
Section "0. Tailscale daemon (READ THIS FIRST)"
$tsService = Get-Service Tailscale -ErrorAction SilentlyContinue
if (-not $tsService) {
    Write-Host "  ERROR: Tailscale service not installed" -ForegroundColor Red
} elseif ($tsService.Status -ne "Running") {
    Write-Host ("  ERROR: Tailscale service is {0} (not Running). Start it: Start-Service Tailscale" -f $tsService.Status) -ForegroundColor Red
    Write-Host  "         Make it auto-start to survive reboots: Set-Service Tailscale -StartupType Automatic" -ForegroundColor Yellow
} else {
    Write-Host ("  ok service Running ({0})" -f $tsService.StartType)
}
$tsStatus = tailscale status 2>$null
if (-not $tsStatus) {
    Write-Host "  ERROR: 'tailscale status' returned nothing -- daemon down or not logged in" -ForegroundColor Red
} else {
    $tsStatus | Select-Object -First 3 | ForEach-Object { Write-Host "  $_" }
}

# ---------- 0a. Legacy stack leftover check ----------
Section "0a. Legacy desktop-commander / mcp-proxy leftover check"
$legacyTask = Get-ScheduledTask -TaskName "MCP-DesktopCommander" -ErrorAction SilentlyContinue
if ($legacyTask) {
    Write-Host "  WARN  legacy task MCP-DesktopCommander still exists -- run setup-windows.ps1 to clean up" -ForegroundColor Yellow
} else {
    Write-Host "  ok no legacy MCP-DesktopCommander task"
}
$legacy8765 = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($legacy8765) {
    Write-Host "  WARN  port 8765 still has a listener -- legacy stack not fully removed" -ForegroundColor Yellow
} else {
    Write-Host "  ok port 8765 not listening (consolidated into 8766)"
}
$legacyProxy = netsh interface portproxy show v4tov6 2>&1
if ($legacyProxy -match "8765") {
    Write-Host "  WARN  legacy v4tov6 portproxy entry for 8765 still present -- run setup-windows.ps1 to clean" -ForegroundColor Yellow
} else {
    Write-Host "  ok no legacy v4tov6 portproxy entries"
}

# ---------- 1. Listening address ----------
Section "1. Listening address (KEY: LocalAddress should be 0.0.0.0)"
$listeners = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "  No process is listening on 8766. win-device service is not running." -ForegroundColor Red
} else {
    $listeners | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
}

# ---------- 2. Owning process ----------
Section "2. Owning process details"
if ($listeners) {
    $listeners | ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            Port = $_.LocalPort
            Addr = $_.LocalAddress
            PID  = $_.OwningProcess
            Name = if ($p) { $p.ProcessName } else { "?" }
            Path = if ($p) { $p.Path } else { "?" }
        }
    } | Format-Table -AutoSize -Wrap
}

# ---------- 3. Localhost self-test ----------
Section "3. Localhost self-test (127.0.0.1)"
$r = Test-NetConnection -ComputerName 127.0.0.1 -Port 8766 -WarningAction SilentlyContinue -InformationLevel Quiet
$color = if ($r) { "Green" } else { "Red" }
Write-Host ("  127.0.0.1:8766 -> {0}" -f $r) -ForegroundColor $color

# ---------- 4. Tailscale IP self-test ----------
Section "4. Tailscale IP self-test (this Windows host's own Tailscale IPv4)"
$tsIp = $null
try {
    $tsIp = (tailscale status --json 2>$null | ConvertFrom-Json -ErrorAction Stop).Self.TailscaleIPs |
            Where-Object { $_ -notmatch ':' } | Select-Object -First 1
} catch {
    Write-Host "  Could not parse 'tailscale status --json': $($_.Exception.Message)" -ForegroundColor Yellow
}
if (-not $tsIp) {
    Write-Host "  Tailscale IPv4 unknown. Skipping section 4." -ForegroundColor Yellow
} else {
    Write-Host "  Tailscale IPv4: $tsIp"
    $r = Test-NetConnection -ComputerName $tsIp -Port 8766 -WarningAction SilentlyContinue -InformationLevel Quiet
    $color = if ($r) { "Green" } else { "Red" }
    Write-Host ("  {0}:8766 -> {1}" -f $tsIp, $r) -ForegroundColor $color
}

# ---------- 5. Firewall rules ----------
Section "5. MCP firewall rules"
$rules = Get-NetFirewallRule -DisplayName "MCP*" -ErrorAction SilentlyContinue
if (-not $rules) {
    Write-Host "  No firewall rules matching 'MCP*'." -ForegroundColor Red
} else {
    $rules | ForEach-Object {
        $port  = ($_ | Get-NetFirewallPortFilter).LocalPort
        $remoteAddr = ($_ | Get-NetFirewallAddressFilter).RemoteAddress
        if (-not $remoteAddr) { $remoteAddr = "(any)" }
        [PSCustomObject]@{
            Name      = $_.DisplayName
            Enabled   = $_.Enabled
            Action    = $_.Action
            Direction = $_.Direction
            Port      = $port
            RemoteIP  = ($remoteAddr -join ",")
        }
    } | Format-Table -AutoSize -Wrap
}

# ---------- 6. Tailscale adapter ----------
Section "6. Tailscale network adapter"
$adapters = Get-NetAdapter | Where-Object { $_.InterfaceDescription -like "*Tailscale*" }
if (-not $adapters) {
    Write-Host "  No adapter with InterfaceDescription matching '*Tailscale*'." -ForegroundColor Red
    Write-Host "  All adapters:"
    Get-NetAdapter | Select-Object Name, InterfaceDescription, Status | Format-Table -AutoSize -Wrap
} else {
    $adapters | Select-Object Name, InterfaceDescription, Status, MacAddress | Format-Table -AutoSize -Wrap
}

# ---------- 7. Scheduled task ----------
Section "7. Scheduled task last run result"
$info = Get-ScheduledTaskInfo -TaskName "MCP-WinDevice" -ErrorAction SilentlyContinue
if ($info) {
    [PSCustomObject]@{
        Task               = "MCP-WinDevice"
        LastRunTime        = $info.LastRunTime
        LastTaskResult     = $info.LastTaskResult
        NumberOfMissedRuns = $info.NumberOfMissedRuns
    } | Format-List
} else {
    Write-Host "  WARN MCP-WinDevice task not registered. Run setup-windows.ps1." -ForegroundColor Yellow
}

# ---------- 8. Service log tail ----------
Section "8. Service log tail (last 30 lines)"
$logsDir = Join-Path (Split-Path -Parent $PSScriptRoot) "logs"
$log = Join-Path $logsDir "win-device.log"
Write-Host "  -- $log --" -ForegroundColor Yellow
if (Test-Path $log) {
    Get-Content -Path $log -Tail 30
} else {
    Write-Host "  (no log file yet -- service has not started even once)"
}

# ---------- 9. Recent Task Scheduler events ----------
Section "9. Recent Task Scheduler events for MCP-WinDevice"
try {
    Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 100 -ErrorAction Stop |
        Where-Object { $_.Message -match "MCP-WinDevice" } |
        Select-Object -First 8 -Property TimeCreated, Id, LevelDisplayName, @{Name="MessageHead"; Expression={ ($_.Message -split "`n")[0] }} |
        Format-Table -AutoSize -Wrap
} catch {
    Write-Host "  Could not read Task Scheduler operational log: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  Try running this script in an elevated PowerShell to access it." -ForegroundColor Yellow
}

# ---------- Summary ----------
Section "Summary -- read this first"
Write-Host "  Quick triage:"
Write-Host "    section 1 LocalAddress = 127.0.0.1   -> server bound to localhost only (server bug)"
Write-Host "    section 1 LocalAddress = 0.0.0.0     -> server bound to all interfaces (good)"
Write-Host "    section 3 = False                    -> service is not actually running"
Write-Host "    section 3 = True, section 4 = False  -> Windows firewall is blocking inbound"
Write-Host "    sections 3 and 4 both True           -> service healthy; problem is on agent side"
Write-Host "    section 0a has WARN                  -> legacy stack not fully cleaned, run setup-windows.ps1"
Write-Host ""
Write-Host "  Paste the entire output above back to the agent operator."
