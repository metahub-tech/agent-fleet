"""Shared Android smoke-test helpers used by all three host-OS installers."""
from __future__ import annotations


def _android_bridge_smoke_tests():
    """Shared smoke tests for the android-device role regardless of host OS
    (Mac / Windows / Linux all run the same android_device_mcp.py server)."""
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_status", {},
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
