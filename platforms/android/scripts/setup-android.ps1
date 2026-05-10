# agent-test-bench / Android (Win11 host) platform setup
#
# Run from inside the cloned repo as Administrator:
#   cd <repo-root>
#   powershell -ExecutionPolicy Bypass -File .\platforms\android\scripts\setup-android.ps1
#
# What this does:
#   1. verify Tailscale is logged in
#   2. verify / install platform-tools (adb) via winget
#   3. install Python 3.10+ if missing
#   4. create a Python venv inside server/ and install requirements
#   5. ask ADB connection mode (USB / Wireless / Hybrid) -> ~/.atb-android/config.toml
#   6. verify `adb devices` shows at least one authorized device
#   7. open firewall port 8768 only on the Tailscale interface
#   8. register Task Scheduler task MCP-AndroidGui (auto-start at logon)
#   9. start service and verify it listens
#
# Idempotent: re-run is safe.
#
# Note: this is the Windows-host setup. For macOS host see setup-android.sh.
#
# NOTE FOR CONTRIBUTORS: Keep this script ASCII / English only.
# Windows PowerShell 5.1 reads .ps1 files using the system code page
# (e.g. GBK on zh-CN Windows) unless a UTF-8 BOM is present, so any
# non-ASCII text here will be mojibake-parsed and break the script.

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

# Force UTF-8 for external command stdout.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

# Auto-discover paths.
$ScriptDir  = $PSScriptRoot
$AndroidDir = Split-Path -Parent $ScriptDir
$ServerDir  = Join-Path $AndroidDir "server"
$VenvDir    = Join-Path $ServerDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ServerPy   = Join-Path $ServerDir "android_mcp.py"
$ReqTxt     = Join-Path $ServerDir "requirements.txt"
$RepoRoot   = Split-Path -Parent (Split-Path -Parent $AndroidDir)
$RunUser    = $env:USERNAME
$ConfigDir  = Join-Path $env:USERPROFILE ".atb-android"
$ConfigPath = Join-Path $ConfigDir "config.toml"
$Port       = 8768
$TaskName   = "MCP-AndroidGui"

Write-Host "=== agent-test-bench / Android Bridge Setup (Win11 host) ===" -ForegroundColor Cyan
Write-Host "Repo  : $RepoRoot"
Write-Host "User  : $RunUser"
Write-Host ""

# ---------- 1. Tailscale ----------
Write-Host "[1/9] Tailscale" -ForegroundColor Cyan
$tsCmd = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $tsCmd) {
    Write-Host "  Tailscale CLI not found. Install via: winget install --id Tailscale.Tailscale -e" -ForegroundColor Yellow
    Write-Host "  Then login via the menubar / system tray, and re-run this script."
    exit 1
}
$tsStatus = & tailscale status --json 2>$null | ConvertFrom-Json
if ($null -eq $tsStatus -or $null -eq $tsStatus.Self -or [string]::IsNullOrEmpty($tsStatus.Self.HostName)) {
    Write-Host "  Tailscale not logged in." -ForegroundColor Yellow
    Write-Host "  Run: tailscale login   -- then re-run this script."
    exit 1
}
$TS_HOST = $tsStatus.Self.HostName
$TS_DNS  = $tsStatus.Self.DNSName -replace '\.$',''
Write-Host "  ok  hostname = $TS_HOST"
Write-Host "      fqdn     = $TS_DNS"

# ---------- 2. platform-tools (adb) ----------
Write-Host ""
Write-Host "[2/9] platform-tools (adb)" -ForegroundColor Cyan
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) {
    Write-Host "  adb not on PATH. Installing via winget..."
    winget install --id Google.PlatformTools -e --accept-package-agreements --accept-source-agreements
    # winget puts platform-tools in %LOCALAPPDATA%\Microsoft\WinGet\Packages\... or similar.
    # Refresh PATH for current session.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path","User")
    $adbCmd = Get-Command adb -ErrorAction SilentlyContinue
    if (-not $adbCmd) {
        Write-Host "  adb still not visible after winget install." -ForegroundColor Red
        Write-Host "  Open a new shell and re-run this script, or set ATB_ANDROID_ADB env var."
        exit 1
    }
}
$adbVersion = (& adb version | Select-Object -First 1)
Write-Host "  ok  $($adbCmd.Source)"
Write-Host "      $adbVersion"

# ---------- 3. Python 3.10+ ----------
Write-Host ""
Write-Host "[3/9] Python 3.10+" -ForegroundColor Cyan
$PythonExe = $null
foreach ($cand in @("python", "python3", "py")) {
    try {
        $verOutput = & $cand --version 2>&1
        if ($verOutput -match "Python\s+(\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 10) {
                $PythonExe = (Get-Command $cand).Source
                Write-Host "  ok  using $PythonExe (v$major.$minor)"
                break
            }
        }
    } catch {}
}
if (-not $PythonExe) {
    Write-Host "  No Python >=3.10 found. Installing via winget..."
    winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path","User")
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Host "  python still not visible. Open a new shell and re-run." -ForegroundColor Red
        exit 1
    }
    Write-Host "  ok  installed $PythonExe"
}

# ---------- 4. venv + deps ----------
Write-Host ""
Write-Host "[4/9] android MCP server venv + deps" -ForegroundColor Cyan
if (-not (Test-Path $VenvDir)) {
    Write-Host "  creating venv: $VenvDir"
    & $PythonExe -m venv $VenvDir
} else {
    Write-Host "  venv exists: $VenvDir"
}
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r $ReqTxt
Write-Host "  ok  deps installed"

# ---------- 5. ADB connection mode ----------
Write-Host ""
Write-Host "[5/9] ADB connection mode" -ForegroundColor Cyan
$existing = $null
if (Test-Path $ConfigPath) {
    $existing = (Get-Content $ConfigPath -Raw)
    Write-Host "  existing $ConfigPath found:"
    Write-Host $existing
    $reuse = Read-Host "  reuse it? [Y/n]"
    if ($reuse -ne "n" -and $reuse -ne "N") {
        Write-Host "  ok  using existing config"
    } else { $existing = $null }
}
if (-not $existing) {
    Write-Host "  Choose ADB connection mode:"
    Write-Host "    1) USB only             (cable always required; per-plug authorization on phone)"
    Write-Host "    2) Wireless Debugging   (Android 11+ / HarmonyOS 4 native pairing)"
    Write-Host "    3) Hybrid (USB enroll)  (Android 5-10 -- adb tcpip 5555; reconnect after each phone reboot)"
    do { $mode = Read-Host "  mode [1/2/3]" } while ($mode -notin @("1","2","3"))
    $modeName = switch ($mode) { "1" {"usb"} "2" {"wireless"} "3" {"hybrid"} }

    if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }
    $config = @"
# agent-test-bench / android-gui server config
# Generated by setup-android.ps1
mode = "$modeName"

[host]
os = "windows"
adb_path = "$($adbCmd.Source.Replace('\','\\'))"
"@
    if ($modeName -eq "wireless") {
        $config += @"

[wireless]
# After pairing, set device_address to "<phone-ip>:<port>"
# device_address = "192.168.1.42:5555"
"@
    }
    Set-Content -Path $ConfigPath -Value $config -Encoding UTF8
    Write-Host "  ok  wrote $ConfigPath (mode=$modeName)"
}

# ---------- 6. verify adb sees a device ----------
Write-Host ""
Write-Host "[6/9] adb devices" -ForegroundColor Cyan
$devicesOut = & adb devices -l
Write-Host $devicesOut
$devCount = ($devicesOut | Select-String -Pattern "`tdevice").Count
if ($devCount -lt 1) {
    Write-Host "  WARN: no authorized device. Plug in via USB and accept the prompt on the phone, OR pair via wireless." -ForegroundColor Yellow
    Write-Host "        Service will start anyway; tools will fail until a device appears."
}

# ---------- 7. Firewall: open port on Tailscale interface only ----------
Write-Host ""
Write-Host "[7/9] firewall (Tailscale interface only)" -ForegroundColor Cyan
$rule = Get-NetFirewallRule -DisplayName "MCP-AndroidGui-$Port" -ErrorAction SilentlyContinue
if ($rule) {
    Write-Host "  rule exists"
} else {
    New-NetFirewallRule -DisplayName "MCP-AndroidGui-$Port" `
        -Direction Inbound -Protocol TCP -LocalPort $Port `
        -Action Allow -InterfaceAlias "Tailscale" -ErrorAction SilentlyContinue | Out-Null
    Write-Host "  ok  added rule MCP-AndroidGui-$Port (TCP/$Port on Tailscale)"
}

# ---------- 8. Task Scheduler ----------
Write-Host ""
Write-Host "[8/9] Task Scheduler ($TaskName)" -ForegroundColor Cyan
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  unregistering old task"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
$Launcher = Join-Path $ScriptDir "_launch-android.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $RunUser
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserId $RunUser -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Host "  ok  registered $TaskName"

Start-ScheduledTask -TaskName $TaskName

# ---------- 9. verify port listening ----------
Write-Host ""
Write-Host "[9/9] verify" -ForegroundColor Cyan
Start-Sleep -Seconds 5
$attempts = 0
while ($attempts -lt 8) {
    $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listen) {
        Write-Host "  ok  android-gui listening on :$Port (pid=$($listen.OwningProcess | Select-Object -First 1))"
        break
    }
    Start-Sleep -Seconds 2
    $attempts++
}
if ($attempts -ge 8) {
    Write-Host "  WARN: $Port not listening after 16s. Check logs:" -ForegroundColor Yellow
    Write-Host "        Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object -Property *"
    Write-Host "        Get-Content `"$AndroidDir\logs\android-gui.log`" -Tail 50"
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host ""
Write-Host "Send these to the agent operator:"
Write-Host "  Tailscale hostname : $TS_HOST"
Write-Host "  android URL        : http://${TS_HOST}:${Port}/sse"
Write-Host ""
Write-Host "On the agent host:"
Write-Host "  python3 scripts\install-agent-side.py --platform android --hostname $TS_HOST"
Write-Host ""
Write-Host "Service control:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Stop-ScheduledTask  -TaskName $TaskName"
Write-Host "  Get-Content `"$AndroidDir\logs\android-gui.log`" -Tail 30"
