#!/usr/bin/env bash
# agent-fleet / iOS platform setup (macOS host)
#
# Run from inside the cloned repo (no sudo; brew refuses root):
#   cd <repo-root>
#   bash platforms/ios/scripts/setup-ios.sh
#
# What this does (6 steps):
#   1. verify Tailscale installed and logged in
#   2. require brew python@3.12 (macOS system Python 3.9.6 can't run fastmcp)
#   3. create a Python venv inside server/ and install requirements
#   4. install launchd plist (~/Library/LaunchAgents/) so the service
#      auto-starts at user login and is auto-restarted on crash
#      (KeepAlive=true gives free restart-on-crash; no while-loop needed)
#   5. start the service immediately and verify it listens on 8769
#
# Idempotent: re-run is safe.
#
# IMPORTANT: WebDriverAgent (WDA) must be built and deployed to each device
# via Xcode BEFORE ios-device tools will work. This script only manages the
# ios-device MCP server (venv + launchd). For WDA setup see:
#   docs/platforms/ios.md

set -euo pipefail

# Friendly failure trap. set -e otherwise dies silently which is brutal for
# first-time setup. With this trap the user at least sees WHICH step exploded.
trap 'rc=$?; echo; echo "ERROR: setup-ios.sh failed at line $LINENO (exit=$rc)" >&2; echo "       Last step header was: $LAST_STEP" >&2; echo "       See docs/platforms/ios.md for common fixes." >&2; exit $rc' ERR
LAST_STEP="(before any step)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
LOGS_DIR="$PLATFORM_DIR/logs"
VENV_DIR="$SERVER_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3"
SERVER_PY="$SERVER_DIR/ios_device_mcp.py"
LAUNCHER="$SCRIPT_DIR/_launch-ios.sh"
PLIST_PATH="$HOME/Library/LaunchAgents/cc.metahub.ios-device.plist"
LABEL="cc.metahub.ios-device"
PORT=8769

mkdir -p "$LOGS_DIR"

echo "=== agent-fleet / iOS Bridge Setup (macOS host) ==="
echo "Repo  : $(cd "$PLATFORM_DIR/../.." && pwd)"
echo "User  : $(whoami)"
echo

# ---------- 0. brew dir permission preflight ----------
LAST_STEP="[0/6] brew dir permission preflight"
echo "$LAST_STEP"
if command -v brew >/dev/null 2>&1; then
    BREW_PREFIX="$(brew --prefix)"
    NEED_CHOWN=()
    for d in \
        "$BREW_PREFIX/share/man/man1" \
        "$BREW_PREFIX/share/man/man8" \
        "$BREW_PREFIX/lib" \
        "$BREW_PREFIX/Cellar" \
        "$BREW_PREFIX/var/homebrew"; do
        if [ -d "$d" ] && [ ! -w "$d" ]; then
            NEED_CHOWN+=("$d")
        fi
    done
    if [ ${#NEED_CHOWN[@]} -gt 0 ]; then
        echo "  ERROR: these brew directories are not writable by $(whoami):"
        for d in "${NEED_CHOWN[@]}"; do echo "    $d"; done
        echo
        echo "  Fix (one-liner; takes ownership of brew prefix):"
        echo "    sudo chown -R $(whoami) $BREW_PREFIX/share $BREW_PREFIX/lib $BREW_PREFIX/Cellar $BREW_PREFIX/var/homebrew"
        echo
        echo "  DO NOT re-run this script with sudo -- brew will refuse."
        exit 1
    fi
    echo "  ok brew prefix writable: $BREW_PREFIX"
else
    echo "  Homebrew not found. Install: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo

# ---------- 1. Tailscale ----------
LAST_STEP="[1/6] Tailscale"
echo "$LAST_STEP"
if ! command -v tailscale >/dev/null 2>&1; then
    if [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
        echo "  Tailscale.app found but 'tailscale' CLI not on PATH."
        echo "  Run: brew install --cask tailscale  (or add /Applications/Tailscale.app/Contents/MacOS to PATH)"
        exit 1
    fi
    echo "  Tailscale not installed. Run: brew install --cask tailscale"
    echo "  Then login via the menubar icon and re-run this script."
    exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
    echo "  Tailscale CLI present but daemon not responding. Open the menubar app and login."
    exit 1
fi
TS_DNS="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Self",{}).get("DNSName","?").rstrip("."))' 2>/dev/null || echo "?")"
# MagicDNS short name (first label of DNSName), not Self.HostName: HostName is
# the OS computer name and goes stale after an admin-console device rename —
# only DNSName tracks the rename, and that's what other tailnet nodes resolve.
TS_HOST="${TS_DNS%%.*}"
echo "  ok logged in"
echo "     hostname : $TS_HOST"
echo "     fqdn     : $TS_DNS"
echo

# ---------- 2. brew python@3.12 (REQUIRED — system Python 3.9.6 can't run fastmcp) ----------
LAST_STEP="[2/6] brew python@3.12"
echo "$LAST_STEP"
echo "  iOS server requires Python >=3.10. macOS ships Python 3.9.6 which"
echo "  can't run fastmcp. Using /opt/homebrew/opt/python@3.12/bin/python3.12."

# Prefer the explicit brew-managed path; don't fall back to system python3.
PYTHON_BIN=""
BREW_PY312="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
if [ -x "$BREW_PY312" ]; then
    PYTHON_BIN="$BREW_PY312"
elif [ -x "/opt/homebrew/bin/python3.12" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.12"
elif [ -x "/usr/local/bin/python3.12" ]; then
    PYTHON_BIN="/usr/local/bin/python3.12"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "  python@3.12 not found. Installing via brew..."
    # brew install on macOS 12 (Tier 3) sometimes exits non-zero even when the
    # install succeeded (post-install link warnings, man-page symlink conflicts).
    # Tolerate the non-zero exit and verify by checking the binary directly.
    brew install python@3.12 || true
    BREW_PY312="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
    if [ -x "$BREW_PY312" ]; then
        PYTHON_BIN="$BREW_PY312"
    elif [ -x "/opt/homebrew/bin/python3.12" ]; then
        PYTHON_BIN="/opt/homebrew/bin/python3.12"
    elif [ -x "/usr/local/bin/python3.12" ]; then
        PYTHON_BIN="/usr/local/bin/python3.12"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "  ERROR: brew install python@3.12 did not produce a usable python3.12 binary."
    echo "         Tried: $(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
    echo "                /opt/homebrew/bin/python3.12"
    echo "                /usr/local/bin/python3.12"
    echo
    echo "  Fix: brew install python@3.12 && which python3.12"
    echo "  Do NOT use macOS system python3 (3.9.6) — fastmcp requires >=3.10."
    exit 1
fi

echo "  ok using $PYTHON_BIN"
"$PYTHON_BIN" -c 'import sys; print(f"  python = {sys.version}")'
echo

# ---------- 3. venv + deps ----------
LAST_STEP="[3/6] ios-device venv + deps"
echo "$LAST_STEP"
if [ ! -d "$VENV_DIR" ]; then
    echo "  creating venv: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "  venv exists: $VENV_DIR"
fi
"$VENV_PY" -m pip install --upgrade pip --quiet
# pip install -e . pulls fastmcp, pymobiledevice3, httpx, pillow, pydantic
"$VENV_PY" -m pip install -e "$SERVER_DIR"
echo "  ok"
echo

# ---------- 4. launchd plist ----------
LAST_STEP="[4/6] launchd plist (auto-start at login + restart on crash)"
echo "$LAST_STEP"

# Make launcher executable
chmod +x "$LAUNCHER"

# Migration: clean up any legacy plist label (future-proof pattern, same as
# setup-macos.sh / setup-android.sh).
LEGACY_LABEL="cc.metahub.ios-gui"
LEGACY_PLIST="$HOME/Library/LaunchAgents/${LEGACY_LABEL}.plist"
if [ -f "$LEGACY_PLIST" ] || launchctl list 2>/dev/null | grep -q "$LEGACY_LABEL"; then
    echo "  found legacy label $LEGACY_LABEL — migrating to ios-device"
    launchctl bootout "gui/$(id -u)" "$LEGACY_PLIST" 2>/dev/null || true
    launchctl unload "$LEGACY_PLIST" 2>/dev/null || true
    rm -f "$LEGACY_PLIST"
fi

# Stop any existing instance so we can re-load the plist cleanly.
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true

# Kill orphaned ios_device_mcp.py processes (manually-launched python that
# escaped launchd management). launchd-managed instances were already shut
# down by the bootout above; this catches stray `python ios_device_mcp.py &`
# left from debugging.
pkill -f "ios_device_mcp\.py" 2>/dev/null || true
sleep 1

mkdir -p "$(dirname "$PLIST_PATH")"
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <!-- Run venv python directly (no bash wrapper). Identical reasoning to
       mac-device: TCC walks the responsible-process chain when deciding
       which binary needs permissions. Direct invocation keeps the chain
       at launchd -> python only.
       _launch-ios.sh stays in the repo as a CLI debugger; not in the
       launchd path. -->
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PY</string>
    <string>$SERVER_PY</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <!-- KeepAlive: launchd auto-restarts on crash; SuccessfulExit=false
       avoids relaunch on clean exit code 0. -->
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>

  <!-- Throttle: don't relaunch faster than every 3 seconds -->
  <key>ThrottleInterval</key>
  <integer>3</integer>

  <key>StandardOutPath</key>
  <string>$LOGS_DIR/ios-device.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS_DIR/ios-device.log</string>

  <key>WorkingDirectory</key>
  <string>$SERVER_DIR</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>LC_ALL</key><string>en_US.UTF-8</string>
  </dict>
</dict>
</plist>
EOF
echo "  wrote $PLIST_PATH"

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "  ok loaded"
echo

# ---------- 5. start + verify ----------
LAST_STEP="[5/6] Verify"
echo "$LAST_STEP"
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 5

attempts=0
while [ $attempts -lt 8 ]; do
    if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "  ok ios-device listening on $PORT"
        break
    fi
    sleep 2
    attempts=$((attempts + 1))
done

if [ $attempts -ge 8 ]; then
    echo "  WARN ios-device not yet on :$PORT after 16s"
    echo "  Check: tail $LOGS_DIR/ios-device.log"
fi
echo

# ---------- 6. iOS device onboarding (per-device prep + WDA status) ----------
# Detects connected devices, runs Developer-Mode automation + guidance via
# ios-device-prep.sh, checks WDA reachability, and tells the user exactly what
# to do next per device. Does NOT auto-build WDA — it guides build-wda.sh (one-off,
# attached) or install-wda-daemon.sh (daemonized: kept alive by launchd, survives
# reboot, no attached xcodebuild).
LAST_STEP="[6/6] iOS device onboarding"
echo "$LAST_STEP"

PMD="$VENV_PY -m pymobiledevice3"
DEVICE_UDIDS="$($PMD usbmux list 2>/dev/null \
    | python3 -c 'import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    data=[]
for d in data:
    u=d.get("UniqueDeviceID") or d.get("Identifier")
    if u: print(u)' 2>/dev/null || true)"

if [ -z "$DEVICE_UDIDS" ]; then
    echo "  No iOS devices connected over USB yet."
    echo "  Plug a device in + tap 'Trust This Computer', then re-run — or onboard later:"
    echo "      bash $SCRIPT_DIR/ios-device-prep.sh <udid>"
else
    # Signing mode: PAID (App Store Connect API key → headless, 1-year cert) vs
    # FREE (Xcode Apple ID account → GUI, 7-day cert, manual refresh).
    TEAM_ID="$(security find-identity -v -p codesigning 2>/dev/null \
        | grep "Apple Development" | head -1 | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/')"
    if [ -n "${WDA_ASC_KEY_PATH:-}" ] && [ -n "${WDA_ASC_KEY_ID:-}" ] && [ -n "${WDA_ASC_ISSUER_ID:-}" ]; then
        echo "  Signing mode: PAID (App Store Connect API key) — headless signing, 1-year cert,"
        echo "                auto cert-refresh. ${TEAM_ID:+Team $TEAM_ID}"
        echo "                (full setup: docs/platforms/ios.md → 付费账号接入)"
    else
        echo "  Signing mode: FREE (Xcode Apple ID account) — 7-day cert, manual refresh."
        if [ -z "$TEAM_ID" ]; then
            echo "  ⚠️  No 'Apple Development' identity yet — one-time:"
            echo "      1. Xcode → Settings → Accounts → add your Apple ID"
            echo "      2. open ~/WebDriverAgent/WebDriverAgent.xcodeproj → WebDriverAgentRunner"
            echo "         → Signing & Capabilities → set Team + Bundle ID → build once (Product → Test)."
            echo "      Then every device builds from CLI via build-wda.sh."
        else
            echo "  ✓ signing identity present (Team $TEAM_ID)"
        fi
        echo "  For headless signing + 1-year cert + auto-refresh: go paid + an ASC API key,"
        echo "  then set WDA_ASC_KEY_PATH/KEY_ID/ISSUER_ID (docs/platforms/ios.md)."
    fi
    echo

    for udid in $DEVICE_UDIDS; do
        echo "  ════ device $udid ════"
        # (a) Developer Mode automation + remaining-steps checklist
        bash "$SCRIPT_DIR/ios-device-prep.sh" "$udid" 2>&1 | sed 's/^/    /' || true
        # (b) WDA reachability check (temporary forward, then drop)
        FWD_PORT=18190
        $PMD usbmux forward "$FWD_PORT" 8100 --udid "$udid" >/dev/null 2>&1 &
        FWD_PID=$!
        WDA_UP="no"
        for i in 1 2 3 4 5; do
            if curl -s --max-time 2 "http://127.0.0.1:$FWD_PORT/status" 2>/dev/null | grep -q '"state"'; then
                WDA_UP="yes"; break
            fi
            sleep 1
        done
        kill $FWD_PID 2>/dev/null || true
        if [ "$WDA_UP" = "yes" ]; then
            echo "    ✓ WDA already reachable on this device"
            echo "      For boot-survival + auto-restart, daemonize it (one-time sudo):"
            echo "        bash $SCRIPT_DIR/install-wda-daemon.sh $udid com.<you>.WebDriverAgentRunner"
        else
            echo "    • WDA not running. After the checklist above is satisfied, either:"
            echo "        (recommended) daemonize — auto-start at boot, kept alive by launchd:"
            echo "          bash $SCRIPT_DIR/install-wda-daemon.sh $udid com.<you>.WebDriverAgentRunner"
            echo "        (one-off, attached, Ctrl-C to stop):"
            echo "          WDA_BUNDLE_ID=com.<you>.WebDriverAgentRunner bash $SCRIPT_DIR/build-wda.sh $udid"
        fi
        echo
    done
    echo "  Tip: ios-device server auto-detects devices on each tool call;"
    echo "       re-run list_devices() after WDA comes up."
fi
echo

echo "=== Done ==="
echo
echo "Send these to the agent operator:"
echo
echo "  Tailscale hostname : $TS_HOST"
echo "  Tailscale FQDN     : $TS_DNS"
echo "  ios-device URL     : http://${TS_HOST}:${PORT}/mcp"
echo
echo "IMPORTANT: WDA must be built and deployed per device before tools work."
echo "  See docs/platforms/ios.md for the Xcode build + run steps."
echo "  (WDA is NOT managed by this script — it is a one-time Xcode operation.)"
echo
echo "On the agent host:"
echo "  python3 scripts/install-agent-side.py --platform ios-device --hostname $TS_HOST"
echo
echo "Service control:"
echo "  launchctl list | grep $LABEL"
echo "  launchctl kickstart -k gui/\$(id -u)/$LABEL"
echo "  tail -f $LOGS_DIR/ios-device.log"
echo
echo "NOTE: ios-device does NOT need Accessibility / Screen Recording grants on the"
echo "      Mac itself. All UI ops go through WDA on the iOS device over USB."
