#!/usr/bin/env bash
# CLI debugger for the macOS GUI MCP service. NOT invoked by launchd.
#
# As of v0.3.2, the launchd plist invokes the venv python directly
# (no bash hop) so macOS TCC's responsible-process chain stays as
# launchd -> python and the Accessibility / Screen Recording panes
# only need an entry for Python.app -- not for /bin/bash on top.
#
# This script stays in the repo for one-off manual launches when
# debugging crashes / permission issues / dependency resolution
# without going through launchd. Run it as:
#
#     bash platforms/macos/scripts/_launch-mac-device.sh
#
# It will print server output to your terminal so you can see
# tracebacks live. Ctrl-C to stop.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
VENV_PY="$SERVER_DIR/.venv/bin/python3"
SERVER_PY="$SERVER_DIR/mac_device_mcp.py"

if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: venv python missing at $VENV_PY" >&2
    exit 1
fi
if [ ! -f "$SERVER_PY" ]; then
    echo "ERROR: server script missing at $SERVER_PY" >&2
    exit 1
fi

echo "=== $(date -u +%FT%TZ) launcher starting (pid=$$) ==="
echo "  python = $VENV_PY"
echo "  server = $SERVER_PY"

cd "$SERVER_DIR"
exec "$VENV_PY" "$SERVER_PY"
