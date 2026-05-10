#!/usr/bin/env bash
# CLI debugger for the Android MCP service (macOS host). NOT invoked by launchd.
#
# As of v0.4.0, the launchd plist invokes the venv python directly (same
# reasoning as macbox-gui: TCC responsible-process chain stays clean).
# This script remains in the repo for one-off manual launches when
# debugging crashes outside launchd:
#
#     bash platforms/android/scripts/_launch-android.sh
#
# Will print server output to your terminal so you can see tracebacks
# live. Ctrl-C to stop.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
VENV_PY="$SERVER_DIR/.venv/bin/python3"
SERVER_PY="$SERVER_DIR/android_mcp.py"

if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: venv python missing at $VENV_PY" >&2
    echo "       Run setup-android.sh first." >&2
    exit 1
fi
if [ ! -f "$SERVER_PY" ]; then
    echo "ERROR: server script missing at $SERVER_PY" >&2
    exit 1
fi

echo "=== $(date -u +%FT%TZ) launching android-gui (pid=$$) ==="
echo "  python = $VENV_PY"
echo "  server = $SERVER_PY"
cd "$SERVER_DIR"
exec "$VENV_PY" "$SERVER_PY"
