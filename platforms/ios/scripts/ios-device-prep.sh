#!/usr/bin/env bash
# Prepare an iOS device for WebDriverAgent via pymobiledevice3 — automate what
# can be automated, clearly guide what can't.
#
# Automated (no user action):
#   - pairing check (usbmux list)
#   - Developer Mode state query (amfi developer-mode-status)
#   - Developer Mode reveal + enable trigger (amfi reveal/enable-developer-mode)
#
# Still needs the user (iOS security — can't be bypassed), but clearly guided:
#   - tap "Trust This Computer" on first USB connect (+ passcode)
#   - after the Developer-Mode reboot, tap "Turn On" on the lock screen (+ passcode)
#   - Enable UI Automation (Settings → Developer) — needs a reboot to take effect
#   - trust the developer cert after WDA installs (Settings → General → VPN & Device Management)
#
# Usage: ios-device-prep.sh <UDID>
# Env:   PMD=<python -m pymobiledevice3 invocation>  (default: server venv)
set -e

UDID="$1"
if [ -z "$UDID" ]; then
    echo "usage: ios-device-prep.sh <UDID>   (from: pymobiledevice3 usbmux list)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$SCRIPT_DIR/../server/.venv/bin/python"
PMD="${PMD:-$VENV_PY -m pymobiledevice3}"

echo "── iOS device prep: $UDID ──"

# 1. Pairing
if ! $PMD usbmux list 2>/dev/null | grep -q "$UDID"; then
    echo "✗ Device not found / not paired."
    echo "  → Plug it in via USB and tap 'Trust This Computer' (+ passcode) on the device,"
    echo "    then re-run this script."
    exit 1
fi
echo "✓ Paired + reachable over usbmux"

# 2. Developer Mode
STATUS=$($PMD amfi developer-mode-status --udid "$UDID" 2>/dev/null | tr -d '[:space:]' | tail -c 5)
if echo "$STATUS" | grep -qi "true"; then
    echo "✓ Developer Mode already enabled"
else
    echo "• Developer Mode is OFF — revealing the option + triggering enable..."
    $PMD amfi reveal-developer-mode --udid "$UDID" 2>/dev/null || true
    if $PMD amfi enable-developer-mode --udid "$UDID" 2>&1 | grep -qiE "error|fail|exception"; then
        echo "  (enable returned a notice — the device may need to be unlocked first)"
    fi
    echo ""
    echo "⚠️  ACTION REQUIRED on the device:"
    echo "    The device is rebooting. After it boots, the lock screen shows a prompt:"
    echo "       'Turn on Developer Mode?' → tap Turn On → enter passcode."
    echo "    Then re-run this script to confirm."
    echo ""
    echo "    (If no prompt appears: Settings → Privacy & Security → Developer Mode → toggle on → reboot.)"
    exit 2
fi

# 3. Remaining manual prerequisites (can't be automated — iOS security)
echo ""
echo "Remaining one-time device steps before WDA will run (re-check after each):"
echo "  [ ] Enable UI Automation:  Settings → Developer → Enable UI Automation → ON → REBOOT"
echo "      (this one MUST be followed by a reboot or WDA times out 'enabling automation mode')"
echo "  [ ] Screen Time install limit OFF (if you use Screen Time):"
echo "      Settings → Screen Time → Content & Privacy Restrictions → off"
echo "  [ ] Auto-Lock = Never + keep unlocked during WDA build:"
echo "      Settings → Display & Brightness → Auto-Lock → Never"
echo "  [ ] (after WDA installs) Trust developer cert:"
echo "      Settings → General → VPN & Device Management → your Apple ID → Trust"
echo ""
echo "Then build WDA:  platforms/ios/scripts/build-wda.sh $UDID <bundle_id>"
