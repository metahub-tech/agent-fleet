"""iOS device discovery via pymobiledevice3 usbmux/lockdown.

Returns DeviceInfo objects compatible with the shared _aliases module:
  serial = UniqueDeviceID (UDID, 40-char hex)
  brand  = "apple"  (constant — Apple is the only iOS device maker)
  model  = ProductType (e.g. "iPhone11,8", "iPad15,7") — Apple's internal model id

We deliberately use ProductType (e.g. "iPhone11,8") rather than the marketing
name ("iPhone XR") because:
  - ProductType is stable, machine-readable, and trivially derived from lockdown
  - Marketing name requires a maintained lookup table that drifts with new releases
  - Aliases stay reproducible across pymobiledevice3 version bumps

Slugged aliases come out like "apple-iphone11-8" / "apple-ipad15-7" via
_aliases.derive_alias (extended slug rule handles the comma in ProductType).
Users can override via ~/.agent-fleet/ios-aliases.json.
"""
from __future__ import annotations

from typing import Any

from _aliases import DeviceInfo


def _list_lockdown() -> list[dict[str, Any]]:
    """Return raw lockdown info dicts for every USB-connected iOS device.

    Uses pymobiledevice3's high-level usbmux API. Empty list if no device
    attached or `pymobiledevice3` isn't installed (raises ImportError then —
    callers should be installed-aware).
    """
    from pymobiledevice3.usbmux import list_devices as _usb_list  # type: ignore
    from pymobiledevice3.lockdown import create_using_usbmux  # type: ignore

    out: list[dict[str, Any]] = []
    for mux_dev in _usb_list():
        try:
            ld = create_using_usbmux(serial=mux_dev.serial)
        except Exception as exc:  # device locked / pairing missing / etc.
            out.append({
                "UniqueDeviceID": mux_dev.serial,
                "_error": f"lockdown failed: {exc.__class__.__name__}: {exc}",
            })
            continue
        info = ld.all_values
        info["UniqueDeviceID"] = mux_dev.serial
        out.append(info)
    return out


def detect_ios_devices() -> list[DeviceInfo]:
    """Enumerate authorized iOS devices.

    Returns list[DeviceInfo] sorted by UDID. Devices that failed lockdown
    pairing (no `_error` cleared) are still returned with brand/model=None
    so they show up in list_devices as "needs pairing" rather than silently
    vanishing.
    """
    raw = _list_lockdown()
    out: list[DeviceInfo] = []
    for d in raw:
        udid = d.get("UniqueDeviceID", "")
        if not udid:
            continue
        if "_error" in d:
            out.append(DeviceInfo(serial=udid, brand=None, model=None))
            continue
        out.append(DeviceInfo(
            serial=udid,
            brand="apple",
            model=d.get("ProductType"),
        ))
    return sorted(out, key=lambda x: x.serial)


def device_extras(udid: str) -> dict[str, Any]:
    """Return per-device extras (OS version, device class, friendly name).

    Used by list_devices() to enrich the basic DeviceInfo with iOS-only
    fields (ProductVersion, DeviceClass, DeviceName).
    """
    from pymobiledevice3.lockdown import create_using_usbmux  # type: ignore

    try:
        ld = create_using_usbmux(serial=udid)
        info = ld.all_values
        return {
            "device_class": info.get("DeviceClass"),  # "iPhone" / "iPad"
            "device_name": info.get("DeviceName"),    # user-set name like "qjl's iPhone"
            "os_version": info.get("ProductVersion"), # "18.7.9"
            "build_version": info.get("BuildVersion"),
        }
    except Exception as exc:
        return {"error": f"{exc.__class__.__name__}: {exc}"}
