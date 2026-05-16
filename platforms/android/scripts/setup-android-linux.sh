#!/usr/bin/env bash
# agent-fleet / Android (Linux host) platform setup
#
# Run from inside the cloned repo:
#   cd <repo-root>
#   bash platforms/android/scripts/setup-android-linux.sh
#
# What this does (8 stages):
#   1. verify Tailscale logged in
#   2. install Android platform-tools (adb) via apt
#   3. install Python 3.10+ (apt python3-venv if missing)
#   4. create Python venv + install requirements
#   5. ask ADB connection mode (USB / Wireless / Hybrid) -> ~/.atb-android/config.toml
#   6. verify `adb devices` shows at least one authorized device
#   7. install systemd user unit
#   8. start + verify port 8768 listens
#
# Idempotent: re-run is safe.
#
# This is the Linux-host setup. For macOS host see setup-android.sh.

set -euo pipefail

# Friendly failure trap (set -e otherwise dies silently).
trap 'rc=$?; echo; echo "ERROR: setup-android-linux.sh failed at line $LINENO (exit=$rc)" >&2; echo "       Last step: $LAST_STEP" >&2; echo "       See docs/platforms/linux.md and platforms/android/README.md for reference." >&2; exit $rc' ERR
LAST_STEP="(before any step)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
LOGS_DIR="$PLATFORM_DIR/logs"
VENV_DIR="$SERVER_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3"
SERVER_PY="$SERVER_DIR/android_device_mcp.py"
REQ_TXT="$SERVER_DIR/requirements.txt"
UNIT_PATH="$HOME/.config/systemd/user/agent-fleet-android-device.service"
PORT=8768
CONFIG_DIR="$HOME/.atb-android"
CONFIG_PATH="$CONFIG_DIR/config.toml"

mkdir -p "$LOGS_DIR" "$(dirname "$UNIT_PATH")"

echo "=== agent-fleet / Android Bridge Setup (Linux host) ==="
echo "Repo  : $(cd "$PLATFORM_DIR/../.." && pwd)"
echo "User  : $(whoami)"
echo

# ---------- 1. Tailscale ----------
LAST_STEP="[1/8] Tailscale"
echo "$LAST_STEP"
if ! command -v tailscale >/dev/null 2>&1; then
    echo "  Tailscale not installed. Install: curl -fsSL https://tailscale.com/install.sh | sh"
    echo "  Then login: tailscale up"
    exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
    echo "  Tailscale CLI present but daemon not responding. Run: tailscale up"
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

# ---------- 2. android-tools-adb ----------
LAST_STEP="[2/8] Android platform-tools (adb)"
echo "$LAST_STEP"
if ! command -v adb >/dev/null 2>&1; then
    echo "  installing android-tools-adb via apt..."
    sudo apt-get update
    sudo apt-get install -y android-tools-adb
fi
ADB_PATH="$(command -v adb)"
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
    echo "  installing python3 + python3-venv via apt..."
    sudo apt-get install -y python3 python3-venv
    PYTHON_BIN="$(command -v python3)"
    ver="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
    echo "  ok using $PYTHON_BIN ($ver)"
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

if [ "${ATB_ANDROID_REUSE_CONFIG:-}" = "1" ]; then
    if [ -f "$CONFIG_PATH" ]; then
        echo "  ok reusing existing config $CONFIG_PATH"
        REUSE=1
    else
        echo "  ATB_ANDROID_REUSE_CONFIG=1 but $CONFIG_PATH missing -- selecting mode instead"
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    if [ -n "${ATB_ANDROID_MODE:-}" ]; then
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
# agent-fleet / android-device server config (Linux host)
mode = "$MODE_NAME"

[host]
os = "linux"
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

# ---------- 7. systemd user unit ----------
LAST_STEP="[7/8] systemd user unit"
echo "$LAST_STEP"

systemctl --user stop agent-fleet-android-device.service 2>/dev/null || true

# Migrate / cleanup: remove the legacy atb-android-gui.service if present
LEGACY_UNIT="atb-android-gui.service"
if systemctl --user list-unit-files 2>/dev/null | grep -q "$LEGACY_UNIT"; then
    systemctl --user stop "$LEGACY_UNIT" 2>/dev/null || true
    systemctl --user disable "$LEGACY_UNIT" 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/$LEGACY_UNIT"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "  removed legacy unit $LEGACY_UNIT"
fi

mkdir -p "$(dirname "$UNIT_PATH")"
cat > "$UNIT_PATH" <<EOF
[Unit]
Description=agent-fleet android-device MCP server
After=network.target

[Service]
Type=simple
ExecStart=$VENV_PY $SERVER_PY
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=ATB_ANDROID_ADB=$ADB_PATH
StandardOutput=append:$LOGS_DIR/android-device.log
StandardError=append:$LOGS_DIR/android-device.log

[Install]
WantedBy=default.target
EOF
echo "  wrote $UNIT_PATH"
systemctl --user daemon-reload
systemctl --user enable agent-fleet-android-device.service
echo "  ok enabled"
echo

# ---------- 8. start + verify ----------
LAST_STEP="[8/8] verify"
echo "$LAST_STEP"
systemctl --user start agent-fleet-android-device.service
sleep 4
attempts=0
while [ $attempts -lt 8 ]; do
    if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
        echo "  ok android-device listening on :$PORT"
        break
    fi
    sleep 2
    attempts=$((attempts + 1))
done
if [ $attempts -ge 8 ]; then
    echo "  WARN android-device not yet on :$PORT after 16s"
    echo "  Check: journalctl --user -u agent-fleet-android-device.service"
fi

echo
echo "=== Done ==="
echo
echo "Send these to the agent operator:"
echo
echo "  Tailscale hostname : $TS_HOST"
echo "  Tailscale FQDN     : $TS_DNS"
echo "  android URL        : http://${TS_HOST}:${PORT}/mcp"
echo
echo "On the agent host:"
echo "  python3 scripts/install-agent-side.py --platform android-device --hostname $TS_HOST"
echo
echo "Service control:"
echo "  systemctl --user list-unit-files | grep android"
echo "  systemctl --user restart agent-fleet-android-device.service"
echo "  journalctl --user -u agent-fleet-android-device.service -f"
echo
echo "NOTE: Linux does NOT need special permissions for android-device --"
echo "      this server only shells out to adb; no GUI capture / mouse / keyboard"
echo "      on the Linux machine itself. (Those are only relevant for mac-device.)"
