"""Shared iOS smoke-test helpers used by the macOS host installer."""
from __future__ import annotations


def _ios_bridge_smoke_tests():
    """Shared smoke tests for the ios-device role.
    The ios-device MCP server only runs on a macOS host (WDA + Xcode requirement).
    """
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_ios_status", {},
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


def _has_device_in_result(result) -> bool:
    """Inspect list_devices tool result: any entry in `devices` array == success."""
    import json
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if payload.get("devices"):
            return True
    return False
