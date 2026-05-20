#!/usr/bin/env bash
# Install the WDA daemon for one device: a shared root tunneld LaunchDaemon +
# a per-device WDA LaunchAgent. After this, WebDriverAgent comes up
# automatically at login/boot and is kept alive by launchd — no attached
# `xcodebuild test`, no manual restart.
#
# Architecture (all parts verified on iPadOS 26 / iOS 18, 2026-05-21):
#   LaunchDaemon  cc.metahub.ios-tunneld  (root, RunAtLoad+KeepAlive)
#       pymobiledevice3 `remote tunneld` — RSD tunnels for ALL iOS 17+ devices,
#       exposed on http://127.0.0.1:49151. Shared by every device.
#   LaunchAgent   cc.metahub.ios-wda-<udid>  (user, RunAtLoad+KeepAlive)
#       _wda-daemon-run.sh -> go-ios `runwda` over that tunnel.
#
# Prereqs (one-time per device — see build-wda.sh / docs/platforms/ios.md):
#   WDA already built & trusted on the device with <bundle_id>; device prepped
#   (Developer Mode, UI Automation, dev cert trusted). This script does NOT
#   build WDA — it only daemonizes its launch.
#
# Usage:  install-wda-daemon.sh <UDID> <bundle_id>
#   <bundle_id> = the SAME base bundle id used with build-wda.sh
#
# Requires sudo ONCE (to install the root tunneld LaunchDaemon) — you will be
# prompted for your password. Run this ON the host (macmini) in an interactive
# shell, NOT over a non-interactive remote shell (sudo -n fails there).
set -e

UDID="$1"
BUNDLE_ID="$2"
if [ -z "$UDID" ] || [ -z "$BUNDLE_ID" ]; then
    echo "usage: install-wda-daemon.sh <UDID> <bundle_id>"
    echo "  <UDID>       from: pymobiledevice3 usbmux list"
    echo "  <bundle_id>  same base bundle id used with build-wda.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$PLATFORM_DIR/server/.venv/bin/python"
RUNNER="$SCRIPT_DIR/_wda-daemon-run.sh"
LOG_DIR="$HOME/Library/Logs/agent-fleet"
mkdir -p "$LOG_DIR"

# 1. go-ios (headless WDA launcher)
bash "$SCRIPT_DIR/install-go-ios.sh"

# 2. pymobiledevice3 (tunnel daemon engine) must be in the server venv
if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: server venv missing at $VENV_PY — run setup-ios.sh first." >&2
    exit 1
fi
if ! "$VENV_PY" -m pymobiledevice3 version >/dev/null 2>&1; then
    echo "ERROR: pymobiledevice3 not importable in the server venv." >&2
    exit 1
fi

# 3. Shared root LaunchDaemon: pymobiledevice3 tunneld
#    MUST be a root LaunchDaemon, not a user LaunchAgent: `remote tunneld`
#    creates a tun network interface, which requires root. A LaunchAgent runs as
#    the (non-root) logged-in user and cannot create the tunnel. Verified: the
#    same `sudo <venv-python> -m pymobiledevice3 remote tunneld` invocation runs
#    fine as root and finds pairing records in system-wide /var/db/lockdown.
TUNNELD_LABEL="cc.metahub.ios-tunneld"
TUNNELD_PLIST="/Library/LaunchDaemons/$TUNNELD_LABEL.plist"
if [ ! -f "$TUNNELD_PLIST" ]; then
    echo "── installing root tunneld LaunchDaemon (sudo; you'll be prompted) ──"
    tmp_plist="$(mktemp)"
    cat > "$tmp_plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$TUNNELD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PY</string>
    <string>-m</string>
    <string>pymobiledevice3</string>
    <string>remote</string>
    <string>tunneld</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/agent-fleet-ios-tunneld.log</string>
  <key>StandardErrorPath</key><string>/var/log/agent-fleet-ios-tunneld.log</string>
</dict>
</plist>
PLIST
    sudo cp "$tmp_plist" "$TUNNELD_PLIST"
    sudo chown root:wheel "$TUNNELD_PLIST"
    sudo chmod 644 "$TUNNELD_PLIST"
    rm -f "$tmp_plist"
    sudo launchctl bootstrap system "$TUNNELD_PLIST" 2>/dev/null \
        || sudo launchctl load -w "$TUNNELD_PLIST"
    echo "✓ tunneld LaunchDaemon installed + loaded"
else
    echo "✓ tunneld LaunchDaemon already present ($TUNNELD_PLIST)"
fi

# 4. Per-device WDA LaunchAgent
SHORT="$(echo "$UDID" | tr -cd '[:alnum:]' | tail -c 12)"
WDA_LABEL="cc.metahub.ios-wda-$SHORT"
AGENTS_DIR="$HOME/Library/LaunchAgents"
WDA_PLIST="$AGENTS_DIR/$WDA_LABEL.plist"
mkdir -p "$AGENTS_DIR"
cat > "$WDA_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$WDA_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNNER</string>
    <string>$UDID</string>
    <string>$BUNDLE_ID</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/wda-$SHORT.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/wda-$SHORT.log</string>
</dict>
</plist>
PLIST

# (re)load the agent
launchctl bootout "gui/$(id -u)/$WDA_LABEL" 2>/dev/null \
    || launchctl unload "$WDA_PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$WDA_PLIST" 2>/dev/null \
    || launchctl load -w "$WDA_PLIST"
echo "✓ WDA LaunchAgent installed + loaded: $WDA_LABEL ($UDID)"
echo ""
echo "Logs:"
echo "  tunneld: /var/log/agent-fleet-ios-tunneld.log"
echo "  wda:     $LOG_DIR/wda-$SHORT.log"
echo "WDA should be up in ~20-40s. Verify via the ios-device MCP (list_devices /"
echo "take_screenshot) — it forwards to device port 8100 transparently."
