# One-shot installer for agent-fleet (Windows).
# Usage:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"

Write-Host "🚢 agent-fleet one-shot installer"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv 未安装，正在装..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: uv install completed but uv still not on PATH."
    Write-Host "Open a new shell and run: uv tool run agent-fleet setup"
    exit 1
}

Write-Host "Running: uv tool run agent-fleet setup"
uv tool run agent-fleet setup
