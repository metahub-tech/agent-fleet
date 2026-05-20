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

RUNNER_BUNDLE="${BUNDLE_ID}.xctrunner"

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
