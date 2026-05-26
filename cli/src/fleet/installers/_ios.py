"""Shared iOS smoke-test helpers used by the macOS host installer."""
from __future__ import annotations


def _ios_bridge_smoke_tests():
    """Shared smoke tests for the ios-device role.
    The ios-device MCP server only runs on a macOS host (WDA + Xcode requirement).
    """
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_status", {},
            description="server reachable"),
        SmokeTest("list_devices", {},
            description="pymobiledevice3 sees >=1 iOS device",
            hint_on_failure="Plug device via USB and tap 'Trust this computer' on the device screen. "
                            "If already trusted, run: python3 -m pymobiledevice3 usbmux list",
            success_predicate=lambda r: _has_device_in_result(r)),
        SmokeTest("get_screen_size", {},
            description="WDA reachable + device responsive",
            hint_on_failure="WDA must be running on the device (xcodebuild test / Xcode run scheme). "
                            "See docs/platforms/ios.md for WDA build & deployment steps."),
        SmokeTest("take_screenshot", {},
            description="WDA screenshot via USB forward",
            timeout=15),
        SmokeTest("current_app", {},
            description="WDA activeAppInfo",
            optional=True,
            hint_on_failure="(optional) WDA activeAppInfo may not be available on some iOS versions; non-blocking"),
    ]


# adb / pymobiledevice3 states meaning "detected but NOT ready to drive".
_NOT_READY_STATES = {
    "unauthorized", "offline", "no permissions", "no_permissions",
    "untrusted", "bootloader", "recovery", "sideload", "host",
    "unknown", "disconnected",
}


def _has_device_in_result(result) -> bool:
    """True iff list_devices reports >=1 *usable* device.

    A device entry counts unless it advertises a not-ready state (e.g. adb
    `unauthorized` / `offline`). Entries without a `state` field are treated as
    usable — the servers already filter to authorized devices and `state` only
    appears in richer payloads — so an unauthorized device no longer passes the
    smoke check merely by being detected.
    """
    import json
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        for dev in payload.get("devices") or []:
            if not isinstance(dev, dict):
                continue  # skip malformed entries — only a real device dict counts
            state = dev.get("state")
            if state is None or str(state).strip().lower() not in _NOT_READY_STATES:
                return True
    return False
