#!/usr/bin/env bash
# One-shot installer for agent-fleet.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash
set -e

echo "🚢 agent-fleet one-shot installer"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv 未安装，正在装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv install completed but uv still not on PATH."
    echo "Open a new shell and run: uv tool run agent-fleet setup"
    exit 1
fi

echo "Running: uv tool run agent-fleet setup"
exec uv tool run agent-fleet setup "$@"
