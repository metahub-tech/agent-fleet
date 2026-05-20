#!/usr/bin/env bash
# Auto-install Xcode via xcodes — no manual App Store / .xip wrangling.
# You provide your Apple ID + a 2FA code once; xcodes downloads (~10GB),
# unxips, installs to /Applications/Xcode-<version>.app, selects it, and
# accepts the license.
#
# Coexistence: xcodes installs a VERSIONED app bundle, so it sits alongside any
# existing /Applications/Xcode.app. To trial the flow without touching your
# current Xcode, install a different version (then `xcodes uninstall <ver>`).
#
# ── China connectivity notes (this is the slow part, not Xcode itself) ──
#   * `brew install xcodesorg/made/xcodes` taps a GitHub repo that can stall.
#     If it hangs on "Tapping xcodesorg/made", Ctrl-C and retry with
#     HOMEBREW_NO_AUTO_UPDATE=1, OR install the xcodes binary directly from
#     https://github.com/XcodesOrg/xcodes/releases (xcodes.zip → unzip →
#     move `xcodes` onto PATH). This script tries brew first, falls back to
#     the release binary.
#   * The ~10GB Xcode download from Apple is the real time sink (30min–2h on
#     a typical China link). Run this when you can leave it.
#
# ── Apple ID auth ──
#   Set XCODES_USERNAME (and optionally XCODES_PASSWORD) to skip the username
#   prompt. 2FA still requires entering the code Apple pushes to your devices —
#   xcodes will pause and ask for it interactively.
#
# Usage: install-xcode.sh [version|latest]
set -e

VERSION="${1:-latest}"
XCODES_RELEASE="https://github.com/XcodesOrg/xcodes/releases/latest/download/xcodes.zip"

# 1. Ensure the `xcodes` CLI is available.
if ! command -v xcodes >/dev/null 2>&1; then
    echo "── installing xcodes CLI ──"
    if command -v brew >/dev/null 2>&1; then
        if ! HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 \
                brew install xcodesorg/made/xcodes; then
            echo "  brew tap/install failed (often a slow China clone). Falling back to release binary..."
            tmp="$(mktemp -d)"
            curl -fsSL -o "$tmp/xcodes.zip" "$XCODES_RELEASE"
            unzip -q "$tmp/xcodes.zip" -d "$tmp"
            sudo mv "$tmp/xcodes" /usr/local/bin/xcodes
            sudo chmod +x /usr/local/bin/xcodes
            rm -rf "$tmp"
        fi
    else
        echo "  ERROR: Homebrew not found. Install brew first (see install.sh / docs)."
        exit 1
    fi
fi
echo "  ok xcodes $(xcodes version 2>/dev/null | head -1)"

# 2. Install Xcode (Apple ID + 2FA prompts here; ~10GB download).
echo "── installing Xcode '$VERSION' via xcodes (~10GB; Apple ID + 2FA when prompted) ──"
xcodes install "$VERSION"

# 3. Select it + accept the license (needs sudo — interactive password).
echo "── selecting Xcode + accepting license (sudo) ──"
XCODE_APP="$(xcodes installed 2>/dev/null | tail -1 | sed -E 's/.*(\/Applications\/[^ ]+\.app).*/\1/')"
if [ -z "$XCODE_APP" ] || [ ! -d "$XCODE_APP" ]; then
    echo "  WARN couldn't auto-detect installed Xcode path from 'xcodes installed'."
    echo "       Run manually: sudo xcode-select -s /Applications/Xcode-<ver>.app && sudo xcodebuild -license accept"
    exit 0
fi
sudo xcode-select -s "$XCODE_APP/Contents/Developer"
sudo xcodebuild -license accept
echo "── done. Active developer dir: $(xcode-select -p) ──"
