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
# Usage:
#   build-wda.sh <UDID> <bundle_id>
#   WDA_BUNDLE_ID=com.you.WebDriverAgentRunner build-wda.sh <UDID>
#
# Runs `xcodebuild ... test`, which stays attached keeping WDA alive (Ctrl-C to
# stop). For unattended/daemon operation see the WDA-daemon backlog item.
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

TEAM_ID=$(security find-identity -v -p codesigning \
    | grep "Apple Development" | head -1 \
    | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/')
if [ -z "$TEAM_ID" ]; then
    echo "ERROR: no 'Apple Development' codesigning identity found."
    echo "  Log in to Xcode → Settings → Accounts first (one-time)."
    exit 1
fi

echo "Team ID:   $TEAM_ID   (auto-extracted)"
echo "Bundle ID: $BUNDLE_ID"
echo "Device:    $UDID"
echo "Building + launching WDA (stays attached; Ctrl-C to stop)..."

exec xcodebuild \
    -project "$WDA_DIR/WebDriverAgent.xcodeproj" \
    -scheme WebDriverAgentRunner \
    -destination "id=$UDID" \
    -allowProvisioningUpdates \
    DEVELOPMENT_TEAM="$TEAM_ID" \
    PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
    test
