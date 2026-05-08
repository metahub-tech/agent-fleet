#!/usr/bin/env bash
# Internal launcher for the macOS GUI MCP service.
#
# Invoked by launchd via the cc.metahub.macbox-gui.plist (StandardOutPath
# and StandardErrorPath of the plist redirect this script's stdout/stderr
# into platforms/macos/logs/macos-gui.log -- so we just exec the python
# server directly without any redirection plumbing).
#
# launchd's KeepAlive=true (with Crashed=true) handles auto-restart on
# crash; the equivalent of the Windows launcher's while-loop is built
# into launchd itself. ThrottleInterval=3 in the plist throttles to
# at most one restart every 3 seconds (rapid-fail safety baked in by
# launchd; we don't need the rapid-fail-counter logic the Windows
# launcher has).
#
# Not for direct user invocation.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
VENV_PY="$SERVER_DIR/.venv/bin/python3"
SERVER_PY="$SERVER_DIR/macos_gui_mcp.py"

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
