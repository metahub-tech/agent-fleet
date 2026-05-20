#!/usr/bin/env bash
# Install the go-ios CLI (pinned) — the headless WebDriverAgent launcher used by
# the WDA daemon. go-ios drives testmanagerd over an RSD tunnel to start WDA
# WITHOUT a permanently-attached `xcodebuild test`, and succeeds where
# pymobiledevice3's `dvt xcuitest` fails on iOS 17+ (verified: iPadOS 26 / iOS 18,
# 2026-05-21 — dvt xcuitest "Connection terminated abruptly", runwda authorizes
# the testmanagerd session and brings WDA up).
#
# The mac release is a universal binary (x86_64 + arm64) — runs natively on
# Apple Silicon, no Rosetta. ~13MB, and crucially needs NO brew/npm/go (the
# macmini host has none of them).
#
# Usage:  install-go-ios.sh                  # pinned version -> <platform>/bin/ios
#         GO_IOS_VERSION=v1.0.213 install-go-ios.sh
set -e

GO_IOS_VERSION="${GO_IOS_VERSION:-v1.0.213}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/bin"
IOS_BIN="$BIN_DIR/ios"

if [ -x "$IOS_BIN" ] && "$IOS_BIN" version 2>/dev/null | grep -q "$GO_IOS_VERSION"; then
    echo "✓ go-ios $GO_IOS_VERSION already installed at $IOS_BIN"
    exit 0
fi

mkdir -p "$BIN_DIR"
URL="https://github.com/danielpaulus/go-ios/releases/download/$GO_IOS_VERSION/go-ios-mac.zip"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "── downloading go-ios $GO_IOS_VERSION (universal mac binary, ~13MB) ──"
echo "   $URL"
echo "   (GitHub can be slow on China links; this is small relative to Xcode.)"
curl -fSL --retry 3 -o "$tmp/go-ios-mac.zip" "$URL"
unzip -o -q "$tmp/go-ios-mac.zip" -d "$tmp"
mv "$tmp/ios" "$IOS_BIN"
chmod +x "$IOS_BIN"
# de-Gatekeeper so launchd / non-GUI shells can exec it without a quarantine block
xattr -d com.apple.quarantine "$IOS_BIN" 2>/dev/null || true

echo "✓ installed: $("$IOS_BIN" version 2>/dev/null | tail -1)"
echo "  path: $IOS_BIN"
