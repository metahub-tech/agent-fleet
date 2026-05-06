# agent-test-bench / Windows MCP service diagnostic
#
# Read-only checks for triaging "the agent host cannot reach my MCP services."
# Does not require Administrator. Run from anywhere inside the cloned repo:
#   powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\diagnose.ps1
#
# Paste the full output back to the agent operator for triage.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

function Section($title) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
}

# ---------- 1. Listening addresses ----------
Section "1. Actual listening addresses (KEY: LocalAddress should be 0.0.0.0)"
$listeners = Get-NetTCPConnection -LocalPort 8765,8766 -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "  No process is listening on 8765 or 8766. Services are not running." -ForegroundColor Red
} else {
    $listeners | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
}

# ---------- 2. Owning processes ----------
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
foreach ($port in 8765,8766) {
    $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet
    $color = if ($r) { "Green" } else { "Red" }
    Write-Host ("  127.0.0.1:{0,-5} -> {1}" -f $port, $r) -ForegroundColor $color
}

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
    foreach ($port in 8765,8766) {
        $r = Test-NetConnection -ComputerName $tsIp -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet
        $color = if ($r) { "Green" } else { "Red" }
        Write-Host ("  {0}:{1,-5} -> {2}" -f $tsIp, $port, $r) -ForegroundColor $color
    }
}

# ---------- 5. Firewall rules ----------
Section "5. MCP firewall rules"
$rules = Get-NetFirewallRule -DisplayName "MCP*" -ErrorAction SilentlyContinue
if (-not $rules) {
    Write-Host "  No firewall rules matching 'MCP*'." -ForegroundColor Red
} else {
    $rules | ForEach-Object {
        $port  = ($_ | Get-NetFirewallPortFilter).LocalPort
        $iface = ($_ | Get-NetFirewallInterfaceFilter).InterfaceAlias
        if (-not $iface) { $iface = "(any)" }
        [PSCustomObject]@{
            Name      = $_.DisplayName
            Enabled   = $_.Enabled
            Action    = $_.Action
            Direction = $_.Direction
            Profile   = $_.Profile
            Port      = $port
            Interface = $iface
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

# ---------- 7. Tailscale daemon ----------
Section "7. Tailscale status (head)"
& tailscale status 2>$null | Select-Object -First 5

# ---------- 8. Scheduled tasks ----------
Section "8. Scheduled task last run result"
"MCP-DesktopCommander","MCP-WindowsGui" | ForEach-Object {
    $info = Get-ScheduledTaskInfo -TaskName $_ -ErrorAction SilentlyContinue
    if ($info) {
        [PSCustomObject]@{
            Task               = $_
            LastRunTime        = $info.LastRunTime
            LastTaskResult     = $info.LastTaskResult
            NumberOfMissedRuns = $info.NumberOfMissedRuns
        }
    }
} | Format-Table -AutoSize

# ---------- Summary ----------
Section "Summary -- read this first"
Write-Host "  Quick triage:"
Write-Host "    section 1 LocalAddress = 127.0.0.1   -> server bound to localhost only (server bug)"
Write-Host "    section 1 LocalAddress = 0.0.0.0     -> server bound to all interfaces (good)"
Write-Host "    section 3 = False                    -> service is not actually running"
Write-Host "    section 3 = True, section 4 = False  -> Windows firewall is blocking inbound"
Write-Host "    section 5 Interface != section 6 Name -> firewall rule attached to wrong NIC"
Write-Host "    sections 3 and 4 both True           -> services healthy; problem is on agent side"
Write-Host ""
Write-Host "  Paste the entire output above back to the agent operator."
