#!/usr/bin/env bash
# Refresh the WDA dev cert before the free-Apple-ID 7-day expiry, then let the
# daemon pick up the freshly-signed runner. Built for unattended scheduling.
#
# Why this exists: a free Apple ID provisioning profile expires 7 days after
# signing. Once expired, go-ios runwda can't authorize the testmanagerd session
# and the WDA LaunchAgent just retries forever. Re-running xcodebuild with
# -allowProvisioningUpdates re-mints the profile and re-signs/reinstalls the
# runner.
#
# Flow (per device, NO launchctl GUI-domain access needed — schedule-friendly):
#   1. set a pause sentinel + kill runwda → the WDA LaunchAgent's wrapper honors
#      the sentinel and idles, freeing the runner for reinstall.
#   2. xcodebuild test re-signs (fresh profile) + reinstalls the runner; run
#      bounded, then stop it. The cert is refreshed once the re-signed runner is
#      INSTALLED — the test run itself is irrelevant (so a locked device is fine).
#   3. remove the sentinel → the LaunchAgent's next KeepAlive cycle relaunches
#      go-ios runwda against the freshly-signed runner.
#
# Scheduling: install-wda-daemon.sh installs a per-device LaunchAgent
# (cc.metahub.ios-wda-certrefresh-<short>) with StartCalendarInterval that calls
# this every ~5 days. A LaunchAgent (vs plain cron) runs in the user's gui
# session, so codesign can reach the unlocked login keychain — plain cron can't.
#
# Long-term clean fix: a PAID Apple Developer account — 1-year cert (no weekly
# rebuild) + App Store Connect API key for fully headless signing.
#
# Usage: refresh-wda-cert.sh <udid> <bundle_id>   (same args as build-wda.sh)
set -u

UDID="${1:-}"
BUNDLE_ID="${2:-}"
if [ -z "$UDID" ] || [ -z "$BUNDLE_ID" ]; then
    echo "usage: refresh-wda-cert.sh <udid> <bundle_id>" >&2
    exit 1
fi

WDA_DIR="${WDA_DIR:-$HOME/WebDriverAgent}"
SHORT="$(echo "$UDID" | tr -cd '[:alnum:]' | tail -c 12)"
PAUSE_FILE="${TMPDIR:-/tmp}/agent-fleet-wda-pause-${UDID}"
LOG="${TMPDIR:-/tmp}/agent-fleet-wda-rebuild-$SHORT.log"
TS() { date -u +%FT%TZ; }

if [ ! -d "$WDA_DIR/WebDriverAgent.xcodeproj" ]; then
    echo "[$(TS)] ERROR: WebDriverAgent not found at $WDA_DIR" >&2
    exit 1
fi
TEAM_ID="$(security find-identity -v -p codesigning 2>/dev/null \
    | grep 'Apple Development' | head -1 | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/')"
if [ -z "$TEAM_ID" ]; then
    echo "[$(TS)] ERROR: no 'Apple Development' codesigning identity found." >&2
    echo "        If scheduled, the login keychain may be locked/inaccessible." >&2
    exit 1
fi

echo "[$(TS)] refresh-wda-cert: udid=$UDID bundle=$BUNDLE_ID team=$TEAM_ID"

# 1. pause the daemon's runwda for this device
touch "$PAUSE_FILE"
pkill -f "runwda.*$UDID" 2>/dev/null || true
sleep 3

# 2. re-sign + reinstall (bounded; cert is refreshed once the runner installs)
xcodebuild -project "$WDA_DIR/WebDriverAgent.xcodeproj" -scheme WebDriverAgentRunner \
    -destination "id=$UDID" -allowProvisioningUpdates \
    DEVELOPMENT_TEAM="$TEAM_ID" PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" test \
    > "$LOG" 2>&1 &
XB=$!
ok=no
for _ in $(seq 1 80); do
    if grep -qE "ServerURLHere|Test Suite .* started|Testing started" "$LOG" 2>/dev/null; then
        ok=yes; break
    fi
    kill -0 "$XB" 2>/dev/null || break   # xcodebuild exited early (build/sign error)
    sleep 3
done
sleep 5
kill "$XB" 2>/dev/null || true
pkill -f "xcodebuild.*$UDID" 2>/dev/null || true
echo "[$(TS)] rebuild runner-install-marker=$ok (log: $LOG)"

# 3. unpause → LaunchAgent KeepAlive relaunches runwda against the fresh runner
rm -f "$PAUSE_FILE"
echo "[$(TS)] sentinel cleared; daemon will relaunch WDA for $UDID"

if [ "$ok" != yes ]; then
    echo "[$(TS)] WARN: never saw a runner install/launch marker — check $LOG and" >&2
    echo "        whether codesign could reach the keychain." >&2
    exit 2
fi
