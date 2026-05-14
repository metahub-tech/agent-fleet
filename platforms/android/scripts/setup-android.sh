#!/usr/bin/env bash
# agent-fleet / Android (macOS host) platform setup
#
# Run from inside the cloned repo (no sudo; brew refuses root):
#   cd <repo-root>
#   bash platforms/android/scripts/setup-android.sh
#
# What this does (8 stages):
#   0. brew prefix dir permission preflight
#   1. verify Tailscale logged in
#   2. install Android platform-tools (adb) via brew cask
#   3. install Python 3.10+ if missing (brew)
#   4. create Python venv + install requirements
#   5. ask ADB connection mode (USB / Wireless / Hybrid) -> ~/.atb-android/config.toml
#   6. verify `adb devices` shows at least one authorized device
#   7. install launchd plist (~/Library/LaunchAgents/cc.metahub.android-device.plist)
#   8. start service and verify port 8768 listens
#
# Idempotent: re-run is safe.
#
# This is the macOS-host setup. For Windows host see setup-android.ps1.

set -euo pipefail

# Friendly failure trap (set -e otherwise dies silently on Tier-3 macOS).
trap 'rc=$?; echo; echo "ERROR: setup-android.sh failed at line $LINENO (exit=$rc)" >&2; echo "       Last step: $LAST_STEP" >&2; echo "       See docs/platforms/macos.md and platforms/android/README.md for reference." >&2; exit $rc' ERR
LAST_STEP="(before any step)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
LOGS_DIR="$PLATFORM_DIR/logs"
VENV_DIR="$SERVER_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3"
SERVER_PY="$SERVER_DIR/android_mcp.py"
REQ_TXT="$SERVER_DIR/requirements.txt"
LAUNCHER="$SCRIPT_DIR/_launch-android.sh"
PLIST_PATH="$HOME/Library/LaunchAgents/cc.metahub.android-device.plist"
LABEL="cc.metahub.android-device"
PORT=8768
CONFIG_DIR="$HOME/.atb-android"
CONFIG_PATH="$CONFIG_DIR/config.toml"

mkdir -p "$LOGS_DIR"

echo "=== agent-fleet / Android Bridge Setup (macOS host) ==="
echo "Repo  : $(cd "$PLATFORM_DIR/../.." && pwd)"
echo "User  : $(whoami)"
echo

# ---------- 0. brew dir permission preflight ----------
LAST_STEP="[0/8] brew dir permission preflight"
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
LAST_STEP="[1/8] Tailscale"
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

# ---------- 2. platform-tools (adb) ----------
LAST_STEP="[2/8] Android platform-tools (adb)"
echo "$LAST_STEP"
if ! command -v adb >/dev/null 2>&1; then
    echo "  installing android-platform-tools cask..."
    # brew install can exit non-zero on Tier-3 macOS even when install succeeded;
    # tolerate and verify by checking the binary directly afterward.
    brew install --cask android-platform-tools || true
    if ! command -v adb >/dev/null 2>&1; then
        # Sometimes brew installs to a path that isn't on the current shell's PATH yet.
        for cand in /opt/homebrew/bin/adb /usr/local/bin/adb "$BREW_PREFIX/bin/adb"; do
            if [ -x "$cand" ]; then
                ADB_PATH="$cand"
                break
            fi
        done
        if [ -z "${ADB_PATH:-}" ]; then
            echo "  ERROR: brew install did not produce a usable adb. Try manually:"
            echo "    brew install --cask android-platform-tools && which adb"
            exit 1
        fi
    else
        ADB_PATH="$(command -v adb)"
    fi
else
    ADB_PATH="$(command -v adb)"
fi
echo "  ok adb at $ADB_PATH"
"$ADB_PATH" version | head -1
echo

# ---------- 3. Python 3.10+ ----------
LAST_STEP="[3/8] Python 3.10+"
echo "$LAST_STEP"
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver="$($candidate -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
        major="${ver%%.*}"; minor="${ver#*.}"
        if [ "$major" = "3" ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON_BIN="$(command -v "$candidate")"
            echo "  ok using $PYTHON_BIN ($ver)"
            break
        fi
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "  installing python@3.12 via brew..."
    brew install python@3.12 || true
    PYTHON_BIN="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
    if [ ! -x "$PYTHON_BIN" ]; then
        for cand in /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12; do
            [ -x "$cand" ] && PYTHON_BIN="$cand" && break
        done
    fi
    if [ ! -x "$PYTHON_BIN" ]; then
        echo "  ERROR: brew install python@3.12 did not produce a usable binary"
        exit 1
    fi
    echo "  ok using $PYTHON_BIN"
fi
echo

# ---------- 4. venv + deps ----------
LAST_STEP="[4/8] android-device venv + deps"
echo "$LAST_STEP"
if [ ! -d "$VENV_DIR" ]; then
    echo "  creating venv: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "  venv exists: $VENV_DIR"
fi
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r "$REQ_TXT"
echo "  ok"
echo

# ---------- 5. ADB connection mode ----------
# Priority:
#   1. ATB_ANDROID_REUSE_CONFIG=1  -> keep existing config, skip everything
#   2. ATB_ANDROID_MODE=<mode>     -> wizard already asked; use it non-interactively
#   3. interactive fallback        -> standalone run (no wizard)
LAST_STEP="[5/8] ADB connection mode"
echo "$LAST_STEP"
mkdir -p "$CONFIG_DIR"
REUSE=0
MODE_NAME=""

if [ "$ATB_ANDROID_REUSE_CONFIG" = "1" ]; then
    if [ -f "$CONFIG_PATH" ]; then
        echo "  ok reusing existing config $CONFIG_PATH"
        REUSE=1
    else
        echo "  ATB_ANDROID_REUSE_CONFIG=1 but $CONFIG_PATH missing -- selecting mode instead"
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    if [ -n "$ATB_ANDROID_MODE" ]; then
        case "$ATB_ANDROID_MODE" in
            usb|wireless|hybrid) MODE_NAME="$ATB_ANDROID_MODE" ;;
            *) echo "  ERROR: ATB_ANDROID_MODE='$ATB_ANDROID_MODE' invalid (expected usb/wireless/hybrid)"; exit 1 ;;
        esac
        echo "  using ADB mode from wizard: $MODE_NAME"
    else
        # interactive fallback -- standalone run
        if [ -f "$CONFIG_PATH" ]; then
            echo "  existing $CONFIG_PATH found:"
            cat "$CONFIG_PATH"
            echo "  Press Enter to keep this config, or 'n' to switch ADB mode (USB/Wireless/Hybrid):"
            read -r ans
            if [[ "$ans" != "n" && "$ans" != "N" ]]; then
                REUSE=1
                echo "  ok using existing config"
            fi
        fi
        if [ "$REUSE" -eq 0 ]; then
            echo "  Choose ADB connection mode:"
            echo "    1) USB only             (cable always required)"
            echo "    2) Wireless Debugging   (Android 11+ / SDK 30+ -- some HarmonyOS 4 phones report Android 10, in which case use 3)"
            echo "    3) Hybrid (USB enroll)  (Android 5-10 -- adb tcpip 5555; reconnect after each phone reboot)"
            while true; do
                echo "  mode [1/2/3]:"
                read -r mode
                case "$mode" in
                    1) MODE_NAME="usb"; break ;;
                    2) MODE_NAME="wireless"; break ;;
                    3) MODE_NAME="hybrid"; break ;;
                    *) echo "  invalid; pick 1/2/3" ;;
                esac
            done
        fi
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    cat > "$CONFIG_PATH" <<EOF
# agent-fleet / android-device server config (macOS host)
mode = "$MODE_NAME"

[host]
os = "macos"
adb_path = "$ADB_PATH"
EOF
    echo "  ok wrote $CONFIG_PATH (mode=$MODE_NAME)"
fi
echo

# ---------- 6. verify adb sees a device ----------
LAST_STEP="[6/8] adb devices"
echo "$LAST_STEP"
"$ADB_PATH" devices -l
DEV_COUNT="$("$ADB_PATH" devices | awk 'NR>1 && $2=="device"' | wc -l | tr -d ' ')"
if [ "$DEV_COUNT" -lt 1 ]; then
    echo "  WARN: no authorized device. Plug in via USB and accept the prompt on the phone, OR pair via wireless."
    echo "        Service will start anyway; tools will fail until a device appears."
fi
echo

# ---------- 7. launchd plist ----------
LAST_STEP="[7/8] launchd plist"
echo "$LAST_STEP"
chmod +x "$LAUNCHER"

# Migration: clean up the legacy plist label from before the v0.6.0 rename.
# Same pattern as setup-macos.sh — legacy label with KeepAlive=true would
# squat port 8768.  Detect, unload, delete, kill orphaned procs.
LEGACY_LABEL="cc.metahub.android-gui"
LEGACY_PLIST="$HOME/Library/LaunchAgents/${LEGACY_LABEL}.plist"
if [ -f "$LEGACY_PLIST" ] || launchctl list 2>/dev/null | grep -q "$LEGACY_LABEL"; then
    echo "  found legacy label $LEGACY_LABEL — migrating to android-device"
    launchctl bootout "gui/$(id -u)" "$LEGACY_PLIST" 2>/dev/null || true
    launchctl unload "$LEGACY_PLIST" 2>/dev/null || true
    rm -f "$LEGACY_PLIST"
fi

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
# Kill orphaned android_mcp.py processes (see setup-macos.sh for rationale).
pkill -f "android_mcp\.py" 2>/dev/null || true
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

  <!-- Run venv python directly (no bash wrapper). Reasoning identical to
       mac-device: TCC walks the responsible-process chain and granting
       permission to /bin/bash is wrong granularity. Direct invocation
       keeps the chain at launchd -> python only.
       _launch-android.sh stays in the repo as CLI debugger; not in the
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

  <key>ThrottleInterval</key>
  <integer>3</integer>

  <key>StandardOutPath</key>
  <string>$LOGS_DIR/android-device.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS_DIR/android-device.log</string>

  <key>WorkingDirectory</key>
  <string>$SERVER_DIR</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>LC_ALL</key><string>en_US.UTF-8</string>
    <key>ATB_ANDROID_ADB</key><string>$ADB_PATH</string>
  </dict>
</dict>
</plist>
EOF
echo "  wrote $PLIST_PATH"
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "  ok loaded"
echo

# ---------- 8. start + verify ----------
LAST_STEP="[8/8] verify"
echo "$LAST_STEP"
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 5
attempts=0
while [ $attempts -lt 8 ]; do
    if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "  ok android-device listening on :$PORT"
        break
    fi
    sleep 2
    attempts=$((attempts + 1))
done
if [ $attempts -ge 8 ]; then
    echo "  WARN android-device not yet on :$PORT after 16s"
    echo "  Check: tail $LOGS_DIR/android-device.log"
fi

echo
echo "=== Done ==="
echo
echo "Send these to the agent operator:"
echo
echo "  Tailscale hostname : $TS_HOST"
echo "  Tailscale FQDN     : $TS_DNS"
echo "  android URL        : http://${TS_HOST}:${PORT}/sse"
echo
echo "On the agent host:"
echo "  python3 scripts/install-agent-side.py --platform android-device --hostname $TS_HOST"
echo
echo "Service control:"
echo "  launchctl list | grep $LABEL"
echo "  launchctl kickstart -k gui/\$(id -u)/$LABEL"
echo "  tail -f $LOGS_DIR/android-device.log"
echo
echo "NOTE: macOS does NOT need Accessibility / Screen Recording grants for android-device --"
echo "      this server only shells out to adb; no GUI capture / mouse / keyboard events"
echo "      on the Mac itself. (Those are only relevant for mac-device.)"
