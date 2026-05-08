#!/usr/bin/env bash
# agent-test-bench / macOS platform setup
#
# Run from inside the cloned repo (no sudo needed; brew may prompt for it):
#   cd <repo-root>
#   bash platforms/macos/scripts/setup-macos.sh
#
# What this does (5 steps):
#   1. verify Tailscale installed and logged in
#   2. install Python 3.12 if missing (via Homebrew)
#   3. create a Python venv inside server/ and install requirements
#   4. install launchd plist (~/Library/LaunchAgents/) so the service
#      auto-starts at user login and is auto-restarted on crash
#      (KeepAlive=true gives us free restart-on-crash; no need for the
#      while-loop launcher hack we use on Windows)
#   5. start the service immediately and verify it listens on 8767
#
# Idempotent: re-run is safe.
#
# AFTER FIRST RUN: macOS will silently deny several capabilities until
# you grant them once in System Settings. See PERMISSIONS section at
# end of script output, or docs/platforms/macos.md section 5.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
LOGS_DIR="$PLATFORM_DIR/logs"
VENV_DIR="$SERVER_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3"
SERVER_PY="$SERVER_DIR/macos_gui_mcp.py"
REQ_TXT="$SERVER_DIR/requirements.txt"
LAUNCHER="$SCRIPT_DIR/_launch-macos-gui.sh"
PLIST_PATH="$HOME/Library/LaunchAgents/cc.metahub.macbox-gui.plist"
LABEL="cc.metahub.macbox-gui"

mkdir -p "$LOGS_DIR"

echo "=== agent-test-bench / macOS Bridge Setup ==="
echo "Repo  : $(cd "$PLATFORM_DIR/../.." && pwd)"
echo "User  : $(whoami)"
echo

# ---------- 1. Tailscale ----------
echo "[1/5] Tailscale"
if ! command -v tailscale >/dev/null 2>&1; then
    # Tailscale may be installed via Mac App Store (CLI not symlinked) or via brew cask
    if [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
        echo "  Tailscale.app found but 'tailscale' CLI not on PATH; brew is recommended for CLI access."
        echo "  Run: brew install --cask tailscale"
        echo "  Or:  add /Applications/Tailscale.app/Contents/MacOS to PATH."
        exit 1
    fi
    if ! command -v brew >/dev/null 2>&1; then
        echo "  Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    echo "  installing Tailscale via brew cask..."
    brew install --cask tailscale
    echo "  -> Open the Tailscale menubar icon, click Login, then re-run this script."
    exit 1
fi

if ! tailscale status >/dev/null 2>&1; then
    echo "  Tailscale CLI present but daemon not responding. Start the menubar app and login."
    exit 1
fi

TS_HOST="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Self",{}).get("HostName","?"))' 2>/dev/null || echo "?")"
TS_DNS="$(tailscale status --json 2>/dev/null  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Self",{}).get("DNSName","?").rstrip("."))' 2>/dev/null || echo "?")"
echo "  ok logged in"
echo "     hostname : $TS_HOST"
echo "     fqdn     : $TS_DNS"

# ---------- 2. Python 3.10+ ----------
echo
echo "[2/5] Python 3.10+"
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver="$($candidate -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
        major="${ver%%.*}"; minor="${ver#*.}"
        if [ "$major" = "3" ] && [ "$minor" -ge 10 ]; then
            PYTHON_BIN="$(command -v "$candidate")"
            echo "  ok using $PYTHON_BIN ($ver)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    if ! command -v brew >/dev/null 2>&1; then
        echo "  Homebrew not found and no python>=3.10 on PATH. Install from python.org or run brew first."
        exit 1
    fi
    echo "  installing python@3.12 via brew..."
    brew install python@3.12
    PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
    echo "  ok using $PYTHON_BIN"
fi

# ---------- 3. venv + deps ----------
echo
echo "[3/5] macbox-gui venv + deps"
if [ ! -d "$VENV_DIR" ]; then
    echo "  creating venv: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "  venv exists: $VENV_DIR"
fi

"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r "$REQ_TXT"
echo "  ok"

# ---------- 4. launchd plist ----------
echo
echo "[4/5] launchd plist (auto-start at login + restart on crash)"

# Make launcher executable
chmod +x "$LAUNCHER"

# Stop any existing instance so we can re-load the plist cleanly.
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true

mkdir -p "$(dirname "$PLIST_PATH")"
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$LAUNCHER</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <!-- KeepAlive: launchd auto-restarts the process if it exits.
       We use the dictionary form so we DON'T relaunch on clean exit
       code 0 (rare but possible) but DO relaunch on crashes. -->
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
    <key>Crashed</key>
    <true/>
  </dict>

  <!-- Throttle: don't relaunch faster than every 3 seconds -->
  <key>ThrottleInterval</key>
  <integer>3</integer>

  <key>StandardOutPath</key>
  <string>$LOGS_DIR/macos-gui.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS_DIR/macos-gui.log</string>

  <key>WorkingDirectory</key>
  <string>$SERVER_DIR</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>LC_ALL</key>
    <string>en_US.UTF-8</string>
  </dict>
</dict>
</plist>
EOF
echo "  wrote $PLIST_PATH"

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "  ok loaded"

# ---------- 5. start + verify ----------
echo
echo "[5/5] Verify"
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 5

attempts=0
while [ $attempts -lt 8 ]; do
    if lsof -nP -iTCP:8767 -sTCP:LISTEN >/dev/null 2>&1; then
        echo "  ok macbox-gui listening on 8767"
        break
    fi
    sleep 2
    attempts=$((attempts + 1))
done

if [ $attempts -ge 8 ]; then
    echo "  WARN macbox-gui not yet on 8767 after 16s"
    echo "  Check: tail $LOGS_DIR/macos-gui.log"
fi

echo
echo "=== Done ==="
echo
echo "Send these to the agent operator (or keep them yourself):"
echo
echo "  Tailscale hostname : $TS_HOST"
echo "  Tailscale FQDN     : $TS_DNS"
echo "  macbox-gui URL     : http://${TS_HOST}:8767/sse"
echo
echo "PERMISSIONS (one-time, manual; macOS won't grant them on its own):"
echo
echo "  System Settings > Privacy & Security > ..."
echo
echo "    [Accessibility]    add: $VENV_PY"
echo "    [Screen Recording] add: $VENV_PY"
echo "    [Automation]       expand python3 entry; tick System Events,"
echo "                        Finder, Safari, ... (whatever apps you script)"
echo
echo "  Without these, click / type / take_screenshot / run_applescript"
echo "  fail silently or with an OS error. Test by running:"
echo
echo "    curl -sN http://${TS_HOST}:8767/sse | head -1"
echo "    # then from agent: take_screenshot tool"
echo
echo "Service auto-starts at every login. Check status anytime:"
echo
echo "    launchctl list | grep macbox"
echo "    tail -f $LOGS_DIR/macos-gui.log"
