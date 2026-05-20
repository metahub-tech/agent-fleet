#!/usr/bin/env bash
# Remove the WDA daemon.
#   uninstall-wda-daemon.sh <UDID>   remove ONLY that device's WDA LaunchAgent
#                                    (leaves tunneld + other devices running)
#   uninstall-wda-daemon.sh --all    remove ALL WDA LaunchAgents AND the shared
#                                    root tunneld LaunchDaemon (sudo)
set -e

ARG="${1:-}"
if [ -z "$ARG" ]; then
    echo "usage: uninstall-wda-daemon.sh <UDID> | --all"
    exit 1
fi

AGENTS_DIR="$HOME/Library/LaunchAgents"

remove_agent() {
    local label="$1" plist="$AGENTS_DIR/$1.plist"
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null \
        || launchctl unload "$plist" 2>/dev/null || true
    rm -f "$plist"
    echo "✓ removed WDA LaunchAgent: $label"
}

if [ "$ARG" = "--all" ]; then
    for plist in "$AGENTS_DIR"/cc.metahub.ios-wda-*.plist; do
        [ -e "$plist" ] || continue
        remove_agent "$(basename "$plist" .plist)"
    done
    TUNNELD_LABEL="cc.metahub.ios-tunneld"
    TUNNELD_PLIST="/Library/LaunchDaemons/$TUNNELD_LABEL.plist"
    if [ -f "$TUNNELD_PLIST" ]; then
        echo "── removing root tunneld LaunchDaemon (sudo) ──"
        sudo launchctl bootout "system/$TUNNELD_LABEL" 2>/dev/null \
            || sudo launchctl unload -w "$TUNNELD_PLIST" 2>/dev/null || true
        sudo rm -f "$TUNNELD_PLIST"
        echo "✓ removed tunneld LaunchDaemon"
    fi
else
    SHORT="$(echo "$ARG" | tr -cd '[:alnum:]' | tail -c 12)"
    remove_agent "cc.metahub.ios-wda-$SHORT"
fi
