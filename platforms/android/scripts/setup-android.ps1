# agent-fleet / Android (Win11 host) platform setup
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
#   8. register Task Scheduler task MCP-AndroidDevice (auto-start at logon)
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

# Admin elevation no longer required at script level — see setup-windows.ps1
# for the same rationale.  Firewall rule creation is wrapped in try-catch.

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
$ServerPy   = Join-Path $ServerDir "android_device_mcp.py"
$ReqTxt     = Join-Path $ServerDir "requirements.txt"
$RepoRoot   = Split-Path -Parent (Split-Path -Parent $AndroidDir)
$RunUser    = $env:USERNAME
$ConfigDir  = Join-Path $env:USERPROFILE ".atb-android"
$ConfigPath = Join-Path $ConfigDir "config.toml"
$Port       = 8768
$TaskName   = "MCP-AndroidDevice"

Write-Host "=== agent-fleet / Android Bridge Setup (Win11 host) ===" -ForegroundColor Cyan
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
$TS_DNS  = $tsStatus.Self.DNSName -replace '\.$',''
# MagicDNS short name (first label of DNSName), not Self.HostName: HostName is
# the OS computer name and goes stale after an admin-console device rename —
# only DNSName tracks the rename, and that's what other tailnet nodes resolve.
$TS_HOST = ($TS_DNS -split '\.')[0]
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
# Priority:
#   1. ATB_ANDROID_REUSE_CONFIG=1  -> keep existing config, skip everything
#   2. ATB_ANDROID_MODE=<mode>     -> wizard already asked; use it non-interactively
#   3. interactive fallback        -> standalone run (no wizard); stdout is a real terminal
Write-Host ""
Write-Host "[5/9] ADB connection mode" -ForegroundColor Cyan

$modeName = $null
$reuseConfig = $false

if ($env:ATB_ANDROID_REUSE_CONFIG -eq "1") {
    if (Test-Path $ConfigPath) {
        Write-Host "  ok  reusing existing config $ConfigPath"
        $reuseConfig = $true
    } else {
        Write-Host "  ATB_ANDROID_REUSE_CONFIG=1 but $ConfigPath missing -- selecting mode instead" -ForegroundColor Yellow
    }
}

if (-not $reuseConfig) {
    if ($env:ATB_ANDROID_MODE) {
        $modeName = $env:ATB_ANDROID_MODE
        if ($modeName -notin @("usb", "wireless", "hybrid")) {
            Write-Host "  ERROR: ATB_ANDROID_MODE='$modeName' invalid (expected usb/wireless/hybrid)" -ForegroundColor Red
            exit 1
        }
        Write-Host "  using ADB mode from wizard: $modeName"
    } else {
        # interactive fallback -- standalone run
        if (Test-Path $ConfigPath) {
            Write-Host "  existing $ConfigPath found:"
            Get-Content $ConfigPath | ForEach-Object { Write-Host "    $_" }
            $reuse = Read-Host "  reuse it? [Y/n]"
            if ($reuse -ne "n" -and $reuse -ne "N") {
                Write-Host "  ok  using existing config"
                $reuseConfig = $true
            }
        }
        if (-not $reuseConfig) {
            Write-Host "  Choose ADB connection mode:"
            Write-Host "    1) USB only             (cable always required; per-plug authorization on phone)"
            Write-Host "    2) Wireless Debugging   (Android 11+ / HarmonyOS 4 native pairing)"
            Write-Host "    3) Hybrid (USB enroll)  (Android 5-10 -- adb tcpip 5555; reconnect after each phone reboot)"
            do { $m = Read-Host "  mode [1/2/3]" } while ($m -notin @("1", "2", "3"))
            $modeName = switch ($m) { "1" {"usb"} "2" {"wireless"} "3" {"hybrid"} }
        }
    }
}

if (-not $reuseConfig) {
    if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }
    $config = @"
# agent-fleet / android-device server config
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
# Firewall rule (only succeeds as admin — graceful skip otherwise).
try {
    $rule = Get-NetFirewallRule -DisplayName "MCP-AndroidDevice-$Port" -ErrorAction SilentlyContinue
    if ($rule) {
        Write-Host "  rule exists"
    } else {
        New-NetFirewallRule -DisplayName "MCP-AndroidDevice-$Port" `
            -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -InterfaceAlias "Tailscale" -ErrorAction Stop | Out-Null
        Write-Host "  ok  added rule MCP-AndroidDevice-$Port (TCP/$Port on Tailscale)"
    }
} catch {
    Write-Host "  WARN: could not create firewall rule (need admin)." -ForegroundColor Yellow
    Write-Host "        Skipping. Re-run from admin PowerShell if remote Tailscale nodes need TCP $Port." -ForegroundColor Yellow
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

# Migrate / cleanup: remove the legacy MCP-AndroidGui task if present.
# Wrap in try-catch — CIM cmdlets' non-terminating errors don't honor
# $ErrorActionPreference=Stop, so the misleading "removed legacy task"
# echo can fire even on Access denied.
$legacyAndroidTaskName = "MCP-AndroidGui"
$legacyTask = Get-ScheduledTask -TaskName $legacyAndroidTaskName -ErrorAction SilentlyContinue
if ($legacyTask) {
    try {
        Stop-ScheduledTask -TaskName $legacyAndroidTaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $legacyAndroidTaskName -Confirm:$false -ErrorAction Stop
        Write-Host "  removed legacy task $legacyAndroidTaskName" -ForegroundColor Yellow
    } catch {
        Write-Host "  ERROR: could not unregister legacy task $legacyAndroidTaskName" -ForegroundColor Red
        Write-Host "         (was originally admin-scoped; need admin PowerShell)" -ForegroundColor Red
        Write-Host "         Detail: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

try {
    Register-ScheduledTask -TaskName $TaskName `
        -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -ErrorAction Stop | Out-Null
    Write-Host "  ok  registered $TaskName"
} catch {
    Write-Host "  ERROR: Register-ScheduledTask failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "         Run this script from an admin PowerShell." -ForegroundColor Red
    exit 1
}

Start-ScheduledTask -TaskName $TaskName

# ---------- 9. verify port listening ----------
Write-Host ""
Write-Host "[9/9] verify" -ForegroundColor Cyan
Start-Sleep -Seconds 5
$attempts = 0
while ($attempts -lt 8) {
    $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listen) {
        Write-Host "  ok  android-device listening on :$Port (pid=$($listen.OwningProcess | Select-Object -First 1))"
        break
    }
    Start-Sleep -Seconds 2
    $attempts++
}
if ($attempts -ge 8) {
    Write-Host "  WARN: $Port not listening after 16s. Check logs:" -ForegroundColor Yellow
    Write-Host "        Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object -Property *"
    Write-Host "        Get-Content `"$AndroidDir\logs\android-device.log`" -Tail 50"
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host ""
Write-Host "Send these to the agent operator:"
Write-Host "  Tailscale hostname : $TS_HOST"
Write-Host "  android URL        : http://${TS_HOST}:${Port}/mcp"
Write-Host ""
Write-Host "On the agent host:"
Write-Host "  python3 scripts/install-agent-side.py --platform android-device --hostname $TS_HOST"
Write-Host ""
Write-Host "Service control:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Stop-ScheduledTask  -TaskName $TaskName"
Write-Host "  Get-Content `"$AndroidDir\logs\android-device.log`" -Tail 30"
