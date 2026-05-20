"""iOS device discovery via the pymobiledevice3 CLI.

pymobiledevice3 9.x made its *Python* API fully async (list_devices /
create_using_usbmux are coroutines). Rather than thread an event loop through
the synchronous FastMCP tool handlers, we shell out to the CLI, which wraps
asyncio internally and prints stable JSON. This also decouples us from
pymobiledevice3 Python-API churn across versions.

`pymobiledevice3 usbmux list` already returns every field we need in one call
(Identifier/UniqueDeviceID, ProductType, ProductVersion, DeviceClass,
DeviceName, BuildVersion) — no per-device lockdown round-trips required.

DeviceInfo mapping for the shared _aliases module:
  serial = UniqueDeviceID (UDID)
  brand  = "apple"   (constant)
  model  = ProductType (e.g. "iPhone11,8", "iPad15,7")
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from _aliases import DeviceInfo

_PMD_LIST_TIMEOUT = 15


def _usbmux_list() -> list[dict[str, Any]]:
    """Run `pymobiledevice3 usbmux list` and return the parsed JSON array.

    Returns [] on any failure (CLI missing, timeout, no devices, bad JSON) —
    callers treat an empty list as "no devices", which is the safe default.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
            capture_output=True, text=True,
            timeout=_PMD_LIST_TIMEOUT, encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _udid_of(d: dict[str, Any]) -> str:
    return d.get("UniqueDeviceID") or d.get("Identifier") or ""


def detect_ios_devices() -> list[DeviceInfo]:
    """Enumerate authorized iOS devices, sorted by UDID. Empty list is valid."""
    out: list[DeviceInfo] = []
    for d in _usbmux_list():
        udid = _udid_of(d)
        if not udid:
            continue
        out.append(DeviceInfo(serial=udid, brand="apple", model=d.get("ProductType")))
    return sorted(out, key=lambda x: x.serial)


def device_extras(udid: str) -> dict[str, Any]:
    """Return per-device extras (device_class, device_name, os_version, build).

    Re-runs `usbmux list` and filters — fine at our call frequency (device
    listing + handshake). Returns {} if the UDID is no longer present.
    """
    for d in _usbmux_list():
        if _udid_of(d) == udid:
            return {
                "device_class": d.get("DeviceClass"),
                "device_name": d.get("DeviceName"),
                "os_version": d.get("ProductVersion"),
                "build_version": d.get("BuildVersion"),
            }
    return {}
