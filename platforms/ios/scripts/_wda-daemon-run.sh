#!/usr/bin/env bash
# Per-device WDA launcher invoked by the cc.metahub.ios-wda-<udid> LaunchAgent.
#
# Looks up this device's RSD tunnel (address + port) from the pymobiledevice3
# tunneld HTTP API, then execs go-ios `runwda` to bring WebDriverAgent up over
# that tunnel. Because launchd (KeepAlive) restarts this whole script whenever
# runwda exits, every (re)start re-queries the tunnel — so it self-heals across
# tunneld restarts, device hot-plug, and the WDA 7-day-cert death.
#
# NOT set -e: the tunnel-readiness retry loop and `read` from a command
# substitution are set -e hostile, so errors are handled explicitly.
#
# Usage (normally via launchd): _wda-daemon-run.sh <UDID> <bundle_id>
#   <bundle_id> = the SAME base bundle id used with build-wda.sh
#                 (PRODUCT_BUNDLE_IDENTIFIER). ".xctrunner" is appended to get
#                 the XCUITest runner bundle id that go-ios launches.
set -u

UDID="${1:-}"
BUNDLE_ID="${2:-}"
TUNNELD_URL="${TUNNELD_URL:-http://127.0.0.1:49151}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IOS_BIN="${IOS_BIN:-$(cd "$SCRIPT_DIR/.." && pwd)/bin/ios}"

if [ -z "$UDID" ] || [ -z "$BUNDLE_ID" ]; then
    echo "usage: _wda-daemon-run.sh <UDID> <bundle_id>" >&2
    exit 2
fi
if [ ! -x "$IOS_BIN" ]; then
    echo "ERROR: go-ios not found at $IOS_BIN — run install-go-ios.sh" >&2
    exit 3
fi

# Honor a pause sentinel set by refresh-wda-cert.sh: while it exists, idle instead
# of launching runwda, so a cert rebuild can reinstall the runner without two
# things driving the same XCUITest bundle. launchd KeepAlive keeps re-running us
# (cheaply idling) until the sentinel is cleared, then we proceed to runwda.
PAUSE_FILE="${TMPDIR:-/tmp}/agent-fleet-wda-pause-${UDID}"
if [ -f "$PAUSE_FILE" ]; then
    echo "[$(date -u +%FT%TZ)] paused ($PAUSE_FILE present) — idling 15s" >&2
    sleep 15
    exit 0
fi

RUNNER_BUNDLE="${BUNDLE_ID}.xctrunner"

# iOS version decides connectivity: iOS<17 uses the CLASSIC path (no RSD tunnel —
# go-ios runwda over usbmux/lockdown directly); iOS17+ needs the tunneld RSD tunnel.
# A WRONG guess is costly: an iOS17+ device sent down the classic path makes runwda
# fail instantly → launchd KeepAlive restart storm with no clear cause. So detection
# retries (the device may still be settling after hot-plug) and, if it STILL can't
# tell, we do NOT guess "<17" — we exit nonzero and let launchd retry cleanly.
# UDID is passed to Python via the environment (not string-interpolated) to avoid
# any code-injection surface.
VENV_PY="$(cd "$SCRIPT_DIR/.." && pwd)/server/.venv/bin/python"
detect_ios_major() {
    local maj i
    for i in 1 2 3; do
        maj="$("$VENV_PY" -m pymobiledevice3 usbmux list 2>/dev/null | DEVICE_UDID="$UDID" "$VENV_PY" -c "
import sys, json, os
u = os.environ['DEVICE_UDID']
try:
    for d in json.load(sys.stdin):
        if d.get('UniqueDeviceID') == u:
            print((d.get('ProductVersion') or '').split('.')[0]); break
except Exception:
    pass" 2>/dev/null)"
        maj="$(printf '%s' "$maj" | grep -oE '^[0-9]+' | head -1)"
        [ -n "$maj" ] && { printf '%s' "$maj"; return 0; }
        sleep 2
    done
    return 1
}
IOS_MAJ="$(detect_ios_major)" || IOS_MAJ=""

if [ -z "$IOS_MAJ" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: 无法检测 $UDID 的 iOS 版本(设备未就绪?);15s 后由 launchd KeepAlive 重试" >&2
    sleep 15
    exit 1
fi

if [ "$IOS_MAJ" -lt 17 ]; then
    # ---- classic path (iOS < 17): no RSD tunnel, no tunneld dependency ----
    echo "[$(date -u +%FT%TZ)] WDA daemon (classic, iOS ${IOS_MAJ}): $UDID runner=$RUNNER_BUNDLE" >&2
    exec "$IOS_BIN" runwda \
        --udid="$UDID" \
        --bundleid="$RUNNER_BUNDLE" \
        --testrunnerbundleid="$RUNNER_BUNDLE" \
        --xctestconfig=WebDriverAgentRunner.xctest
fi

# ---- tunnel path (iOS 17+) ----
# Wait (up to ~2min) for tunneld to publish a tunnel for this device. tunneld
# lags boot/hot-plug; exiting nonzero lets launchd KeepAlive retry cleanly.
ADDR=""; PORT=""
for i in $(seq 1 60); do
    # reset each iteration: `read` leaves vars untouched on EOF, so without this
    # a later empty poll could otherwise keep a stale address from a prior poll.
    ADDR=""; PORT=""
    read -r ADDR PORT < <(curl -s --max-time 3 "$TUNNELD_URL/" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    t = d.get('$UDID') or []
    if t:
        print(t[0]['tunnel-address'], t[0]['tunnel-port'])
except Exception:
    pass
" 2>/dev/null) || true
    if [ -n "$ADDR" ] && [ -n "$PORT" ]; then
        break
    fi
    echo "[$(date -u +%FT%TZ)] waiting for tunneld tunnel for $UDID ($i/60)..." >&2
    sleep 2
done

if [ -z "$ADDR" ] || [ -z "$PORT" ]; then
    echo "ERROR: no tunnel for $UDID from tunneld at $TUNNELD_URL after timeout" >&2
    exit 4   # launchd KeepAlive retries
fi

echo "[$(date -u +%FT%TZ)] WDA daemon: $UDID via [$ADDR]:$PORT runner=$RUNNER_BUNDLE" >&2
exec "$IOS_BIN" runwda \
    --udid="$UDID" \
    --address="$ADDR" \
    --rsd-port="$PORT" \
    --bundleid="$RUNNER_BUNDLE" \
    --testrunnerbundleid="$RUNNER_BUNDLE" \
    --xctestconfig=WebDriverAgentRunner.xctest
