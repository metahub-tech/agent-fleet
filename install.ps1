# One-shot installer for agent-fleet (Windows).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"
#
# Pin AGENT_FLEET_VERSION below or override via env var to choose a release.

$AGENT_FLEET_VERSION = if ($env:AGENT_FLEET_VERSION) { $env:AGENT_FLEET_VERSION } else { "v0.5.0-alpha" }
$AGENT_FLEET_REPO = if ($env:AGENT_FLEET_REPO) { $env:AGENT_FLEET_REPO } else { "https://github.com/metahub-tech/agent-fleet" }

Write-Host "🚢 agent-fleet one-shot installer (target: $AGENT_FLEET_VERSION)"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  uv not installed; bootstrapping via astral.sh ..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  ERROR: uv install completed but uv still not on PATH."
    Write-Host "         Open a new shell and re-run, or run manually:"
    Write-Host "           uvx --from `"git+$AGENT_FLEET_REPO@$AGENT_FLEET_VERSION#subdirectory=cli`" agent-fleet setup"
    exit 1
}

$URL = "git+${AGENT_FLEET_REPO}@${AGENT_FLEET_VERSION}#subdirectory=cli"
Write-Host "  Running: uvx --from `"$URL`" agent-fleet setup"
uvx --from "$URL" agent-fleet setup @args
