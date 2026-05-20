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

# Resolve free vs paid signing (shared with build-wda.sh). PAID (ASC API key)
# refreshes fully headless; FREE has no headless path (needs an account + 2FA) so
# this will fail at signing by design, with guidance, and refresh must be manual.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_signing.sh"
resolve_wda_signing
if [ -z "$WDA_TEAM_ID" ]; then
    echo "[$(TS)] ERROR: no Team ID (set WDA_TEAM_ID or create an Apple Development identity)." >&2
    echo "        If scheduled, the login keychain may be locked/inaccessible." >&2
    exit 1
fi
if [ "$WDA_SIGNING_MODE" = paid ]; then
    echo "[$(TS)] refresh-wda-cert: udid=$UDID bundle=$BUNDLE_ID team=$WDA_TEAM_ID (PAID: ASC API key, headless)"
else
    echo "[$(TS)] refresh-wda-cert: udid=$UDID bundle=$BUNDLE_ID team=$WDA_TEAM_ID (FREE: no API key — will fail at signing if no Apple ID account is live)"
fi

# 1. pause the daemon's runwda for this device
touch "$PAUSE_FILE"
pkill -f "runwda.*$UDID" 2>/dev/null || true
sleep 3

# 2. re-sign + reinstall (bounded; cert is refreshed once the runner installs)
xcodebuild -project "$WDA_DIR/WebDriverAgent.xcodeproj" -scheme WebDriverAgentRunner \
    -destination "id=$UDID" -allowProvisioningUpdates \
    ${WDA_AUTH_ARGS[@]+"${WDA_AUTH_ARGS[@]}"} \
    DEVELOPMENT_TEAM="$WDA_TEAM_ID" PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" test \
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
    echo "[$(TS)] WARN: never saw a runner install/launch marker — check $LOG." >&2
    if grep -qiE "No Accounts|No profiles" "$LOG" 2>/dev/null; then
        echo "        Signing failed (No Accounts / No profiles). This is the free-Apple-ID" >&2
        echo "        wall: minting a fresh 7-day profile needs an Apple ID account, and" >&2
        echo "        (re-)adding one to Xcode needs password + 2FA — not automatable." >&2
        echo "        Fix: open Xcode → Settings → Accounts → (re-)add your Apple ID, then" >&2
        echo "        rebuild via build-wda.sh. Permanent fix: paid Apple Developer + an" >&2
        echo "        App Store Connect API key (set WDA_ASC_KEY_PATH/KEY_ID/ISSUER_ID)." >&2
    fi
    exit 2
fi
