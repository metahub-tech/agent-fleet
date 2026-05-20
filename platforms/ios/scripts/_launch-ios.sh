#!/usr/bin/env bash
# CLI debugger for the iOS MCP service. NOT invoked by launchd.
#
# NOTE: WebDriverAgent (WDA) must be built and running SEPARATELY on each
# device before any UI/screen tools will work. This launcher only manages
# the ios-device MCP server process. See docs/platforms/ios.md for WDA
# Xcode build & deployment steps.
#
# As of v0.8.0, the launchd plist invokes the venv python directly (no
# bash hop) so the responsible-process chain stays at launchd -> python.
# This script stays in the repo for one-off manual launches when debugging
# crashes / dependency issues without going through launchd. Run it as:
#
#     bash platforms/ios/scripts/_launch-ios.sh
#
# It will print server output to your terminal so you can see tracebacks
# live. Ctrl-C to stop.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
VENV_PY="$SERVER_DIR/.venv/bin/python3"
SERVER_PY="$SERVER_DIR/ios_device_mcp.py"

if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: venv python missing at $VENV_PY" >&2
    echo "       Run: bash platforms/ios/scripts/setup-ios.sh" >&2
    exit 1
fi
if [ ! -f "$SERVER_PY" ]; then
    echo "ERROR: server script missing at $SERVER_PY" >&2
    exit 1
fi

echo "=== $(date -u +%FT%TZ) launcher starting (pid=$$) ==="
echo "  python = $VENV_PY"
echo "  server = $SERVER_PY"
echo "  NOTE: WDA must be running per device (xcodebuild test / Xcode run scheme)."
echo "        See docs/platforms/ios.md for WDA setup."

cd "$SERVER_DIR"
exec "$VENV_PY" "$SERVER_PY"
