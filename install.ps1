# One-shot installer for agent-fleet (Windows).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"
#
# Behavior:
#   1. Install uv if missing.
#   2. If CWD is not inside an agent-fleet clone, git-clone the repo (the wizard
#      shells out to platforms\<os>\scripts\setup-<os>.* and needs the tree on
#      disk).  Default clone location: $env:USERPROFILE\agent-fleet  (override
#      with $env:AGENT_FLEET_CLONE_DIR).
#   3. Run `uvx --from git+...@<TAG>#subdirectory=cli agent-fleet setup`.
#
# Env-var overrides:
#   AGENT_FLEET_VERSION      default v0.6.1-alpha
#   AGENT_FLEET_REPO         default https://github.com/metahub-tech/agent-fleet
#   AGENT_FLEET_CLONE_DIR    default $env:USERPROFILE\agent-fleet

$AGENT_FLEET_VERSION = if ($env:AGENT_FLEET_VERSION) { $env:AGENT_FLEET_VERSION } else { "v0.6.1-alpha" }
$AGENT_FLEET_REPO    = if ($env:AGENT_FLEET_REPO)    { $env:AGENT_FLEET_REPO }    else { "https://github.com/metahub-tech/agent-fleet" }
$AGENT_FLEET_CLONE_DIR = if ($env:AGENT_FLEET_CLONE_DIR) { $env:AGENT_FLEET_CLONE_DIR } else { Join-Path $env:USERPROFILE "agent-fleet" }

Write-Host "🚢 agent-fleet one-shot installer (target: $AGENT_FLEET_VERSION)"

# ---------- 1. uv ----------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  uv not installed; bootstrapping via astral.sh ..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  ERROR: uv install completed but uv still not on PATH."
    Write-Host "         Open a new shell and re-run."
    exit 1
}

# ---------- 2. ensure CWD is inside an agent-fleet clone ----------
# The wizard's installer step invokes <repo-root>\platforms\<os>\scripts\setup-<os>.* via Path.cwd().
$inClone = (Test-Path "platforms\windows\scripts\setup-windows.ps1") `
        -or (Test-Path "platforms\macos\scripts\setup-macos.sh") `
        -or (Test-Path "platforms\android\scripts\setup-android-linux.sh")

if (-not $inClone) {
    Write-Host "  CWD is not inside an agent-fleet clone; preparing one at $AGENT_FLEET_CLONE_DIR"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "  ERROR: git is required but not installed."
        Write-Host "         Install Git for Windows from https://git-scm.com/download/win and re-run."
        exit 1
    }
    if (Test-Path (Join-Path $AGENT_FLEET_CLONE_DIR ".git")) {
        Write-Host "  existing clone found; updating + checking out $AGENT_FLEET_VERSION"
        Set-Location $AGENT_FLEET_CLONE_DIR
        # --force needed so retagged refs (common for alpha tags) overwrite the
        # local tag pointer instead of silently keeping the stale sha.
        git fetch --tags --force --quiet origin 2>$null
        $checkoutOk = $false
        git checkout $AGENT_FLEET_VERSION --quiet 2>$null
        if ($LASTEXITCODE -eq 0) { $checkoutOk = $true }
        if (-not $checkoutOk) { git checkout main --quiet 2>$null }
        git pull --ff-only --quiet 2>$null
    } elseif (Test-Path $AGENT_FLEET_CLONE_DIR) {
        # A non-clone dir at our default path is almost always leftover from a
        # previous install whose Remove-Item was blocked by running Task
        # Scheduler tasks holding venv files open.  Stop our tasks first
        # (only our names — MCP-WinDevice / MCP-AndroidDevice), then clean up.
        Write-Host "  $AGENT_FLEET_CLONE_DIR exists but isn't a clone — stopping our tasks + cleaning up"
        foreach ($taskName in @("MCP-WinDevice", "MCP-AndroidDevice")) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
        Remove-Item -Recurse -Force $AGENT_FLEET_CLONE_DIR -ErrorAction SilentlyContinue
        if (Test-Path $AGENT_FLEET_CLONE_DIR) {
            Write-Host "  ERROR: could not remove $AGENT_FLEET_CLONE_DIR (running process still has it open?)."
            Write-Host "         Try: Unregister-ScheduledTask -TaskName MCP-WinDevice -Confirm:`$false; then re-run."
            exit 1
        }
        # Fall through to clone path
    }
    if (-not (Test-Path (Join-Path $AGENT_FLEET_CLONE_DIR ".git"))) {
        Write-Host "  cloning $AGENT_FLEET_REPO (branch/tag $AGENT_FLEET_VERSION, shallow) ..."
        git clone --branch $AGENT_FLEET_VERSION --depth 1 "$AGENT_FLEET_REPO.git" $AGENT_FLEET_CLONE_DIR 2>$null
        if ($LASTEXITCODE -ne 0) {
            git clone --depth 1 "$AGENT_FLEET_REPO.git" $AGENT_FLEET_CLONE_DIR
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  ERROR: git clone failed."
                exit 1
            }
        }
        Set-Location $AGENT_FLEET_CLONE_DIR
    }
    Write-Host "  ok cwd is now $(Get-Location)"
}

# ---------- 3. run the wizard ----------
$URL = "git+${AGENT_FLEET_REPO}@${AGENT_FLEET_VERSION}#subdirectory=cli"
Write-Host "  Running: uvx --from `"$URL`" agent-fleet setup"
uvx --from "$URL" agent-fleet setup @args
