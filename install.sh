#!/usr/bin/env bash
# One-shot installer for agent-fleet.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash
#
# Behavior:
#   1. Install uv if missing (via astral's official one-liner).
#   2. macOS 12 only: install coreutils (uv's wrapper uses realpath which isn't
#      on stock macOS 12 — see #2).
#   3. Run `uvx --from git+https://github.com/metahub-tech/agent-fleet@<TAG>` to
#      fetch and execute the agent-fleet setup wizard. Token-less since the
#      repo is public from v0.5.0-alpha onward.
#
# Pin the TAG below to a release version (or "main" for the bleeding edge).
set -e

AGENT_FLEET_VERSION="${AGENT_FLEET_VERSION:-v0.5.0-alpha}"
AGENT_FLEET_REPO="${AGENT_FLEET_REPO:-https://github.com/metahub-tech/agent-fleet}"

echo "🚢 agent-fleet one-shot installer (target: ${AGENT_FLEET_VERSION})"

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
    echo "  uv not installed; bootstrapping via astral.sh ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "  ERROR: uv install completed but uv still not on PATH."
    echo "         Open a new shell and re-run, or run manually:"
    echo "           uvx --from 'git+${AGENT_FLEET_REPO}@${AGENT_FLEET_VERSION}#subdirectory=cli' agent-fleet setup"
    exit 1
fi

# 2. macOS 12 coreutils workaround for uv wrapper realpath dependency
if [[ "$(uname)" == "Darwin" ]] && ! command -v realpath >/dev/null 2>&1; then
    echo "  detected macOS without realpath; installing coreutils via brew (uv wrapper needs it on macOS 12)"
    if command -v brew >/dev/null 2>&1; then
        brew install coreutils
    else
        echo "  WARN: brew not found; if the next step fails, install coreutils manually."
    fi
fi

URL="git+${AGENT_FLEET_REPO}@${AGENT_FLEET_VERSION}#subdirectory=cli"
echo "  Running: uvx --from \"${URL}\" agent-fleet setup"
exec uvx --from "${URL}" agent-fleet setup "$@"
