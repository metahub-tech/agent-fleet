"""Shared Android smoke-test helpers used by all three host-OS installers."""
from __future__ import annotations


def _android_bridge_smoke_tests():
    """Shared smoke tests for the android-device role regardless of host OS
    (Mac / Windows / Linux all run the same android_device_mcp.py server)."""
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_android_status", {},
            description="server reachable"),
        SmokeTest("list_devices", {},
            description="ADB sees at least one device",
            hint_on_failure="Plug in via USB (and accept the 'Allow USB debugging' prompt on the phone), OR run setup-android again and pick Wireless/Hybrid",
            success_predicate=lambda r: _has_device_in_result(r)),
        SmokeTest("get_screen_size", {},
            description="device responsive",
            hint_on_failure="adb sees the device but it's unauthorized — unplug + replug + accept the on-screen prompt"),
        SmokeTest("take_screenshot", {},
            description="screencap via adb exec-out",
            timeout=10),
        SmokeTest("current_app", {},
            description="dumpsys focused app",
            optional=True,
            hint_on_failure="(optional) some OEM ROMs strip dumpsys; non-blocking"),
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
