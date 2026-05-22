#!/usr/bin/env bash
# One-shot installer for agent-fleet.
#
# Usage:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh)"
#
# NOT `curl ... | bash`: bash piped from curl reads the script FROM stdin, so the
# interactive wizard can't read from stdin either.  The `bash -c "$(...)"` form
# puts the script in argv and leaves stdin = the user's terminal.
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
#   AGENT_FLEET_VERSION      default v0.8.3-alpha
#   AGENT_FLEET_REPO         default https://github.com/metahub-tech/agent-fleet
#   AGENT_FLEET_CLONE_DIR    default $HOME/agent-fleet  (only used if CWD not in a clone)
set -e

AGENT_FLEET_VERSION="${AGENT_FLEET_VERSION:-v0.8.3-alpha}"
AGENT_FLEET_REPO="${AGENT_FLEET_REPO:-https://github.com/metahub-tech/agent-fleet}"
AGENT_FLEET_CLONE_DIR="${AGENT_FLEET_CLONE_DIR:-$HOME/agent-fleet}"

echo "🚢 agent-fleet one-shot installer (target: ${AGENT_FLEET_VERSION})"

# Hard-fail on curl|bash invocation: bash piped from curl reads the script body
# from stdin, so the wizard's interactive prompts have nothing to read from
# (questionary dies with EOFError on the first key).  `exec </dev/tty` does not
# fix this -- once we redirect, bash itself can't read further script bytes.
# The only reliable form is `bash -c "$(curl ...)"`, which puts the script in
# argv and leaves stdin = terminal.
if [ ! -t 0 ]; then
    cat >&2 <<'ERROEOF'

ERROR: agent-fleet's installer is interactive but stdin is not a TTY.

  You probably invoked it as:
      curl -fsSL .../install.sh | bash       ← stdin is the pipe, not a terminal

  The wizard needs to read keystrokes for role selection, framework choice, etc.,
  but bash is itself reading the script from that same pipe.  Use this form
  instead (script in argv, stdin stays = terminal):

      bash -c "$(curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh)"

  Or, since v0.8.3-alpha already cloned the repo for you in a prior attempt:

      cd ~/agent-fleet
      uvx --from "git+https://github.com/metahub-tech/agent-fleet@v0.8.3-alpha#subdirectory=cli" agent-fleet setup

ERROEOF
    exit 1
fi

# ---------- 0. preflight: base tools on a fresh machine ----------
# A brand-new macOS box ships without git or brew (learned the hard way on a
# fresh mac mini). uv/coreutils/python all assume these exist. Check up front
# and print copy-paste install commands (incl. China mirrors) instead of
# failing cryptically three steps later.
preflight_missing=()
command -v curl >/dev/null 2>&1 || preflight_missing+=("curl")
command -v git  >/dev/null 2>&1 || preflight_missing+=("git")
if [[ "$(uname)" == "Darwin" ]]; then
    # brew is needed downstream by setup-macos.sh / setup-ios.sh (Tailscale,
    # python@3.12, coreutils). Check it here so the user fixes everything once.
    command -v brew >/dev/null 2>&1 || [ -x /opt/homebrew/bin/brew ] || [ -x /usr/local/bin/brew ] || preflight_missing+=("brew")
fi
if [ ${#preflight_missing[@]} -gt 0 ]; then
    echo ""
    echo "⚠️  缺少基础工具 / Missing base tools: ${preflight_missing[*]}"
    echo "    装好后重新跑本命令。Install these, then re-run."
    echo ""
    for tool in "${preflight_missing[@]}"; do
        case "$tool" in
            git)
                if [[ "$(uname)" == "Darwin" ]]; then
                    echo "  git  →  xcode-select --install        # 装 Command Line Tools（含 git）"
                else
                    echo "  git  →  sudo apt-get install -y git   # 或对应发行版的包管理器"
                fi
                ;;
            brew)
                echo "  brew →  官方:     /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                echo "          国内镜像: /bin/zsh -c \"\$(curl -fsSL https://gitee.com/cunkai/HomebrewCN/raw/master/Homebrew.sh)\""
                echo "          装完按提示执行 eval \"\$(/opt/homebrew/bin/brew shellenv)\" 让 brew 进 PATH"
                ;;
            curl)
                echo "  curl →  系统通常自带；若缺用包管理器装 (apt-get install -y curl)"
                ;;
        esac
    done
    echo ""
    exit 1
fi

# On Apple Silicon a freshly-installed brew may not be on PATH yet for this
# shell — source its shellenv so the steps below (and setup scripts) see it.
if [[ "$(uname)" == "Darwin" ]] && ! command -v brew >/dev/null 2>&1; then
    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
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
        # --force needed so retagged refs (common for alpha tags) overwrite the
        # local tag pointer instead of silently keeping the stale sha.
        git fetch --tags --force --quiet origin || true
        git checkout "${AGENT_FLEET_VERSION}" --quiet 2>/dev/null \
            || git checkout main --quiet 2>/dev/null \
            || true
        git pull --ff-only --quiet 2>/dev/null || true
    else
        if [ -e "$AGENT_FLEET_CLONE_DIR" ]; then
            # A non-clone dir at our default path is almost always leftover
            # from a previous install whose rm -rf was blocked by running
            # launchd / systemd services holding venv files open.  Stop our
            # services first (only our labels — cc.metahub.* and
            # agent-fleet-*), then clean up.  Users who pointed
            # AGENT_FLEET_CLONE_DIR at their own valuable path opted into us
            # managing it.
            echo "  ${AGENT_FLEET_CLONE_DIR} exists but isn't a clone — stopping our services + cleaning up"
            if [[ "$(uname)" == "Darwin" ]]; then
                for label in cc.metahub.mac-device cc.metahub.android-device; do
                    plist="$HOME/Library/LaunchAgents/${label}.plist"
                    [ -f "$plist" ] && launchctl unload "$plist" 2>/dev/null || true
                done
            elif [[ "$(uname)" == "Linux" ]]; then
                systemctl --user stop agent-fleet-android-device.service 2>/dev/null || true
            fi
            rm -rf "$AGENT_FLEET_CLONE_DIR"
        fi
        echo "  cloning ${AGENT_FLEET_REPO} (branch/tag ${AGENT_FLEET_VERSION}, shallow) ..."
        git clone --branch "${AGENT_FLEET_VERSION}" --depth 1 "${AGENT_FLEET_REPO}.git" "${AGENT_FLEET_CLONE_DIR}" 2>/dev/null \
            || git clone --depth 1 "${AGENT_FLEET_REPO}.git" "${AGENT_FLEET_CLONE_DIR}"
        cd "$AGENT_FLEET_CLONE_DIR"
    fi
    echo "  ok cwd is now $(pwd)"
fi

# ---------- 4. run the wizard ----------
# Use LOCAL cli path (./cli) instead of `git+url#subdirectory=cli`.  Reasons:
#   1. We already have the clone on disk from step 3, so re-fetching via uvx
#      is wasteful (two clones of the same repo, one by git, one by uv).
#   2. uv's bundled git client (libgit2) intermittently fails on Windows
#      with "× Failed to resolve --with requirement / Git operation failed"
#      where the system `git` CLI succeeds — our user hit this on first try.
#      Using a local path bypasses uv's git entirely.
echo "  Running: uvx --from \"$(pwd)/cli\" agent-fleet setup"
# uv caches built tools by package version, so a same-version source change (or a
# missed version bump) would silently reuse a stale build of the local cli. Clear
# our package's cache entry first so the installer always runs the current source.
uv cache clean agent-fleet >/dev/null 2>&1 || true
exec uvx --from "$(pwd)/cli" agent-fleet setup "$@"
