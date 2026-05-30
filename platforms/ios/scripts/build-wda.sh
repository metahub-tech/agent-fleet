#!/usr/bin/env bash
# Build & launch WebDriverAgent on an iOS device — fully from the CLI, no Xcode
# IDE interaction PER DEVICE.
#
# Why a one-time GUI step is still needed (free Apple ID):
#   xcodebuild can reuse an EXISTING provisioning profile + auto-add a new
#   device's UDID via -allowProvisioningUpdates without any account auth. But
#   creating a profile for a BRAND-NEW bundle id from the CLI requires Apple ID
#   account auth that a launchd/non-GUI shell can't provide ("No Accounts"
#   error). So:
#
#   ONE-TIME setup per machine (free Apple ID):
#     1. Xcode → Settings → Accounts → add your Apple ID
#     2. open ~/WebDriverAgent/WebDriverAgent.xcodeproj, select the
#        WebDriverAgentRunner target → Signing & Capabilities → set your Team
#        and a Bundle ID (e.g. com.<you>.WebDriverAgentRunner), then build once
#        (Product → Test) to ANY device to mint the provisioning profile.
#     3. Use that SAME bundle id with this script for every device thereafter.
#
#   Paid Apple Developer can skip the GUI entirely with an App Store Connect
#   API key (-authenticationKeyPath / -authenticationKeyID / -authenticationKeyIssuerID)
#   — see docs/platforms/ios.md.
#
# After the one-time setup, this script builds WDA on ANY device by reusing the
# profile and auto-adding the device UDID. Team ID is auto-extracted from the
# codesigning identity. Verified on iPhone XR + iPad sharing one bundle id.
#
# Two signing modes (resolved by _signing.sh, auto-detected from env):
#   FREE — default. Team ID auto-extracted from the Xcode-configured Apple ID
#          identity (one-time GUI setup above). 7-day cert.
#   PAID — set WDA_ASC_KEY_PATH + WDA_ASC_KEY_ID + WDA_ASC_ISSUER_ID for headless
#          App Store Connect API-key signing (1-year cert, no GUI/2FA). On a fresh
#          paid account with no identity yet, also set WDA_TEAM_ID (Membership
#          team id) so the first build can sign before a cert exists.
#
# Usage:
#   build-wda.sh <UDID> <bundle_id>
#   WDA_BUNDLE_ID=com.you.WebDriverAgentRunner build-wda.sh <UDID>
#   # paid/headless:
#   WDA_ASC_KEY_PATH=/path/key.p8 WDA_ASC_KEY_ID=XXXX WDA_ASC_ISSUER_ID=uuid \
#     WDA_TEAM_ID=ABCDE12345 build-wda.sh <UDID> <bundle_id>
#
# Runs `xcodebuild ... test`, which stays attached keeping WDA alive (Ctrl-C to
# stop). For unattended/daemon operation see install-wda-daemon.sh.
set -e

UDID="$1"
BUNDLE_ID="${2:-${WDA_BUNDLE_ID}}"
WDA_DIR="${WDA_DIR:-$HOME/WebDriverAgent}"

if [ -z "$UDID" ] || [ -z "$BUNDLE_ID" ]; then
    echo "usage: build-wda.sh <UDID> <bundle_id>   (or set WDA_BUNDLE_ID env)"
    echo ""
    echo "  <UDID>       from: pymobiledevice3 usbmux list"
    echo "  <bundle_id>  the bundle id you set up once in Xcode (must already"
    echo "               have a provisioning profile — see header comment)"
    exit 1
fi

if [ ! -d "$WDA_DIR/WebDriverAgent.xcodeproj" ]; then
    echo "ERROR: WebDriverAgent not found at $WDA_DIR"
    echo "  git -c http.version=HTTP/1.1 clone https://github.com/appium/WebDriverAgent.git $WDA_DIR"
    exit 1
fi

# Resolve free vs paid signing (see _signing.sh). PAID (WDA_ASC_KEY_PATH/KEY_ID/
# ISSUER_ID set) signs headless via an App Store Connect API key; FREE uses the
# Xcode-configured Apple ID account.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_signing.sh"
resolve_wda_signing

if [ -z "$WDA_TEAM_ID" ]; then
    echo "ERROR: no Team ID. Set WDA_TEAM_ID, or create an 'Apple Development'"
    echo "       identity first:"
    echo "         FREE: Xcode → Settings → Accounts → add your Apple ID (one-time)."
    echo "         PAID: set WDA_ASC_KEY_PATH/KEY_ID/ISSUER_ID + WDA_TEAM_ID (Membership team id)."
    exit 1
fi

echo "Signing:   $WDA_SIGNING_MODE$([ "$WDA_SIGNING_MODE" = paid ] && echo ' (App Store Connect API key — headless)' || echo ' (Xcode Apple ID account)')"
echo "Team ID:   $WDA_TEAM_ID"
echo "Bundle ID: $BUNDLE_ID"
echo "Device:    $UDID"
echo "Building + launching WDA (stays attached; Ctrl-C to stop)..."

# agent-fleet WDA 扩展（FBPhotosCommands /wda/photos/import 等）—— 幂等注入到 $WDA_DIR
EXT_DIR="$(cd "$(dirname "$0")"/../wda-ext && pwd)"
if [ -d "$EXT_DIR" ]; then
  echo "[build-wda] applying agent-fleet wda-ext from $EXT_DIR"
  if ! "$EXT_DIR/install.sh" "$WDA_DIR"; then
    echo "[build-wda] FATAL: wda-ext install failed; abort build" >&2
    exit 1
  fi
fi

exec xcodebuild \
    -project "$WDA_DIR/WebDriverAgent.xcodeproj" \
    -scheme WebDriverAgentRunner \
    -destination "id=$UDID" \
    -allowProvisioningUpdates \
    ${WDA_AUTH_ARGS[@]+"${WDA_AUTH_ARGS[@]}"} \
    DEVELOPMENT_TEAM="$WDA_TEAM_ID" \
    PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
    test
