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
#   3. If CWD is not inside an agent-fleet clone, git-clone the repo (the wizard
#      shells out to platforms/<os>/scripts/setup-<os>.sh and needs the tree on
#      disk).  Default clone location: $HOME/agent-fleet  (override with
#      AGENT_FLEET_CLONE_DIR).
#   4. Run `uvx --from git+...@<TAG>#subdirectory=cli agent-fleet setup`.
#
# Env-var overrides:
#   AGENT_FLEET_VERSION      default v0.5.0-alpha
#   AGENT_FLEET_REPO         default https://github.com/metahub-tech/agent-fleet
#   AGENT_FLEET_CLONE_DIR    default $HOME/agent-fleet  (only used if CWD not in a clone)
set -e

AGENT_FLEET_VERSION="${AGENT_FLEET_VERSION:-v0.5.0-alpha}"
AGENT_FLEET_REPO="${AGENT_FLEET_REPO:-https://github.com/metahub-tech/agent-fleet}"
AGENT_FLEET_CLONE_DIR="${AGENT_FLEET_CLONE_DIR:-$HOME/agent-fleet}"

echo "🚢 agent-fleet one-shot installer (target: ${AGENT_FLEET_VERSION})"

# When invoked via `curl ... | bash`, stdin is the pipe from curl (already EOF
# after the script bytes are consumed), so the wizard's interactive prompts
# would die with EOFError.  Re-bind stdin to the controlling terminal so
# questionary / prompt_toolkit can read keystrokes.
if [ ! -t 0 ] && [ -r /dev/tty ]; then
    exec </dev/tty
fi

# ---------- 1. uv ----------
if ! command -v uv >/dev/null 2>&1; then
    echo "  uv not installed; bootstrapping via astral.sh ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "  ERROR: uv install completed but uv still not on PATH."
    echo "         Open a new shell and re-run."
    exit 1
fi

# ---------- 2. macOS 12 coreutils workaround ----------
if [[ "$(uname)" == "Darwin" ]] && ! command -v realpath >/dev/null 2>&1; then
    echo "  detected macOS without realpath; installing coreutils via brew (uv wrapper needs it on macOS 12)"
    if command -v brew >/dev/null 2>&1; then
        brew install coreutils
    else
        echo "  WARN: brew not found; if the next step fails, install coreutils manually."
    fi
fi

# ---------- 3. ensure CWD is inside an agent-fleet clone ----------
# The wizard's installer step invokes <repo-root>/platforms/<os>/scripts/setup-<os>.sh
# via Path.cwd().  Without a clone, that path doesn't exist.
if [ ! -f "platforms/macos/scripts/setup-macos.sh" ] && [ ! -f "platforms/windows/scripts/setup-windows.ps1" ] && [ ! -f "platforms/android/scripts/setup-android-linux.sh" ]; then
    echo "  CWD is not inside an agent-fleet clone; preparing one at ${AGENT_FLEET_CLONE_DIR}"
    if ! command -v git >/dev/null 2>&1; then
        echo "  ERROR: git is required but not installed."
        if [[ "$(uname)" == "Darwin" ]]; then
            echo "         Install via:  xcode-select --install"
        else
            echo "         Install via your package manager (e.g. apt-get install git)."
        fi
        exit 1
    fi
    if [ -d "$AGENT_FLEET_CLONE_DIR/.git" ]; then
        echo "  existing clone found; updating + checking out ${AGENT_FLEET_VERSION}"
        cd "$AGENT_FLEET_CLONE_DIR"
        git fetch --tags --quiet origin || true
        git checkout "${AGENT_FLEET_VERSION}" --quiet 2>/dev/null \
            || git checkout main --quiet 2>/dev/null \
            || true
        git pull --ff-only --quiet 2>/dev/null || true
    else
        if [ -e "$AGENT_FLEET_CLONE_DIR" ]; then
            echo "  ERROR: ${AGENT_FLEET_CLONE_DIR} exists but is not a git clone."
            echo "         Remove it or set AGENT_FLEET_CLONE_DIR to a different path."
            exit 1
        fi
        echo "  cloning ${AGENT_FLEET_REPO} (branch/tag ${AGENT_FLEET_VERSION}, shallow) ..."
        git clone --branch "${AGENT_FLEET_VERSION}" --depth 1 "${AGENT_FLEET_REPO}.git" "${AGENT_FLEET_CLONE_DIR}" 2>/dev/null \
            || git clone --depth 1 "${AGENT_FLEET_REPO}.git" "${AGENT_FLEET_CLONE_DIR}"
        cd "$AGENT_FLEET_CLONE_DIR"
    fi
    echo "  ok cwd is now $(pwd)"
fi

# ---------- 4. run the wizard ----------
URL="git+${AGENT_FLEET_REPO}@${AGENT_FLEET_VERSION}#subdirectory=cli"
echo "  Running: uvx --from \"${URL}\" agent-fleet setup"
exec uvx --from "${URL}" agent-fleet setup "$@"
