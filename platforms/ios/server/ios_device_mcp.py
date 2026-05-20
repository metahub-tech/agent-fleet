"""iOS MCP Server (ios-device) — v0.8.0-alpha.

FastMCP server bridging an LLM agent to one or more iOS devices via:
  - pymobiledevice3 — device discovery, app install/uninstall, lockdown info
  - WebDriverAgent (WDA) — UI operations (tap/swipe/screenshot/elements)

Architecture mirrors android-device v0.7.x exactly:
  - Single MCP entry on 0.0.0.0:8769/mcp (streamable-http)
  - 24 tools (22 mirror Android + activate_app + device_info; drop adb_shell)
  - All tools accept optional `device` parameter (UDID or alias)
  - Alias map auto-derived from ProductType, override via
    ~/.agent-fleet/ios-aliases.json
  - Per-device holder advisory lock (acquire_ios / release_ios)
  - FastMCP `instructions=` reports connected-device list at handshake
  - Resource `iosfleet://devices` provides live JSON snapshot
  - Session-scoped sticky default via set_default_device / get_default_device

Host requirements:
  macOS-only. Needs full Xcode (not just CLT) to build & sign WDA.
  Free Apple ID works (7-day cert refresh); $99/yr Apple Developer is smoother.

Per-device port forwarding:
  device:8100 (WDA listen)  --pymobiledevice3 usbmux forward-->  host:18100+N
  Forwarder subprocess kept alive for server lifetime, one per device.

Transport: streamable-http on 0.0.0.0:8769/mcp.

Same fastmcp/mcp transport caveats as Android (jlowin/fastmcp#823):
  - All long subprocess ops clamped to 25s via _adb_run-style helper
  - install_ipa / push_file / pull_file warn for large files
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Annotated, Any, Optional

from PIL import Image as PILImage
from pydantic import Field

from fastmcp import Context, FastMCP
from fastmcp.utilities.types import Image

# _aliases / _device_state are shared across platform servers — see platforms/common/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))

from _aliases import DeviceInfo, derive_alias, load_aliases, resolve_aliases
from _device_state import DeviceStateRegistry
from _ios_devices import detect_ios_devices, device_extras
from _wda_client import WdaClient, WdaForwarder


# ============================================================
#                  CONSTANTS + STATE
# ============================================================

# fastmcp/mcp streamable-http race (jlowin/fastmcp#823): cap subprocess ops
# at 25s leaving 5s margin under the ~30s transport deadline.
_FASTMCP_DEADLINE_SAFE_SECONDS = 25

# Per-device forwarders bind starting from this port.
_WDA_LOCAL_PORT_BASE = 18100

# Forward + WDA client maps, keyed by UDID. Mutated by main() at startup and
# by hot-plug logic. Reads are unguarded by design — these dicts only grow.
_forwarders: dict[str, WdaForwarder] = {}
_wda_clients: dict[str, WdaClient] = {}
_forwarders_lock = threading.Lock()

# Alias config file
ALIAS_CONFIG_PATH = Path.home() / ".agent-fleet" / "ios-aliases.json"

# Per-device advisory holder registry
_state_registry = DeviceStateRegistry()

# Session-scoped sticky default device map (FastMCP session id -> UDID)
_session_defaults: dict[str, str] = {}
_session_defaults_lock = threading.Lock()
_NO_SESSION = "__no_session__"


# ============================================================
#                  SHARED HELPERS
# ============================================================

class MultipleDevicesError(RuntimeError):
    """Raised when a tool can't pick a device automatically and the caller didn't specify one."""


_DIAG_FIELDS = ("timed_out", "requested_timeout", "effective_timeout", "hint")


def _diag(r: dict) -> dict:
    return {k: r[k] for k in _DIAG_FIELDS if k in r}


def _run_pmd(args: list[str], timeout: int = 25) -> dict:
    """Run a pymobiledevice3 CLI command with fastmcp-safe timeout cap.
    Returns dict {returncode, stdout, stderr [+ timed_out/hint on timeout]}.
    """
    effective = min(timeout, _FASTMCP_DEADLINE_SAFE_SECONDS)
    cmd = [sys.executable, "-m", "pymobiledevice3"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=effective, encoding="utf-8", errors="replace")
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired as e:
        return {
            "returncode": -1,
            "stdout": e.stdout if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr if isinstance(e.stderr, str) else "") + f"\npymobiledevice3 timed out after {effective}s",
            "timed_out": True,
            "requested_timeout": timeout,
            "effective_timeout": effective,
            "hint": "Long pymobiledevice3 ops (install_ipa with big bundles) exceed the fastmcp transport deadline. See jlowin/fastmcp#823.",
        }


# ============================================================
#                  DEVICE DETECTION + ALIASES
# ============================================================

def _load_alias_overrides() -> dict[str, str]:
    try:
        return load_aliases(ALIAS_CONFIG_PATH)
    except ValueError as exc:
        print(f"[ios-device] WARN malformed alias config at {ALIAS_CONFIG_PATH}: {exc}", file=sys.stderr)
        return {}


def _detected_aliased() -> tuple[list[DeviceInfo], dict[str, str]]:
    detected = detect_ios_devices()
    overrides = _load_alias_overrides()
    aliases = resolve_aliases(detected, overrides)
    return detected, aliases


def _format_known(detected: list[DeviceInfo], aliases: dict[str, str]) -> str:
    if not detected:
        return "(none detected)"
    parts: list[str] = []
    for d in detected:
        alias = aliases.get(d.serial, "(no alias)")
        parts.append(f"{alias} ({d.serial})")
    return ", ".join(parts)


def _resolve_device(device_arg: str | None, session_default: str | None = None) -> str:
    """Resolve a device argument to a UDID. Order: explicit -> sticky default ->
    only-1 autoselect -> MultipleDevicesError.
    """
    detected, aliases = _detected_aliased()
    if device_arg:
        serials = {d.serial for d in detected}
        if device_arg in serials:
            return device_arg
        for serial, alias in aliases.items():
            if alias == device_arg:
                return serial
        raise RuntimeError(
            f"unknown device '{device_arg}'. Known: {_format_known(detected, aliases)}"
        )
    if session_default:
        return _resolve_device(session_default, session_default=None)
    if len(detected) == 1:
        return detected[0].serial
    if not detected:
        raise MultipleDevicesError(
            "no iOS devices found. Plug a device via USB and tap 'Trust this computer' on first connect."
        )
    raise MultipleDevicesError(
        f"multiple iOS devices attached ({len(detected)}). "
        f"Pass device=<alias|udid>, or call set_default_device() to set a session sticky default. "
        f"Available: {_format_known(detected, aliases)}"
    )


def _get_session_default(ctx: Optional["Context"]) -> str | None:
    try:
        sid = ctx.session_id if ctx is not None else None  # type: ignore[attr-defined]
    except Exception:
        sid = None
    key = sid or _NO_SESSION
    with _session_defaults_lock:
        return _session_defaults.get(key)


def _set_session_default(ctx: Optional["Context"], serial: str | None) -> None:
    try:
        sid = ctx.session_id if ctx is not None else None  # type: ignore[attr-defined]
    except Exception:
        sid = None
    key = sid or _NO_SESSION
    with _session_defaults_lock:
        if serial is None:
            _session_defaults.pop(key, None)
        else:
            _session_defaults[key] = serial


# ============================================================
#                  WDA FORWARDER / CLIENT MANAGEMENT
# ============================================================

def _ensure_forwarder_and_client(udid: str) -> WdaClient:
    """Return (creating if needed) a running WdaForwarder + cached WdaClient
    for the given UDID. Idempotent.
    """
    with _forwarders_lock:
        if udid in _wda_clients and _forwarders[udid].is_alive():
            return _wda_clients[udid]
        # Choose stable port: idx in sorted UDID list. Detect on demand.
        all_udids = sorted({d.serial for d in detect_ios_devices()})
        try:
            idx = all_udids.index(udid)
        except ValueError:
            raise RuntimeError(f"UDID {udid} is no longer detected; was the device unplugged?")
        local_port = _WDA_LOCAL_PORT_BASE + idx
        if udid not in _forwarders:
            _forwarders[udid] = WdaForwarder(udid, local_port)
        _forwarders[udid].start()
        _wda_clients[udid] = WdaClient(udid, f"http://127.0.0.1:{local_port}")
        return _wda_clients[udid]


def _wda_for(udid: str) -> WdaClient:
    return _ensure_forwarder_and_client(udid)


# ============================================================
#                  FASTMCP INSTRUCTIONS (handshake)
# ============================================================

def _build_instructions() -> str:
    try:
        detected, aliases = _detected_aliased()
    except Exception:
        detected, aliases = [], {}

    if not detected:
        return (
            "iOS MCP bridge. No iOS devices currently attached. Plug an iPhone/iPad via USB "
            "and accept 'Trust this computer' on first connect.\n\n"
            "Note: requires WebDriverAgent (WDA) to be built & deployed to each device via Xcode "
            "(see docs/platforms/ios.md). Tools fail until WDA is reachable."
        )

    lines = [f"iOS MCP bridge (multi-device). {len(detected)} device(s) attached:"]
    for d in detected:
        alias = aliases.get(d.serial, "(no alias)")
        extras = device_extras(d.serial)
        os_v = extras.get("os_version", "?")
        cls = extras.get("device_class", "?")
        name = extras.get("device_name", "")
        suffix = f" [{name}]" if name else ""
        lines.append(f"  - {alias}  ({d.serial[:8]}…, {cls} iOS {os_v}{suffix})")

    if len(detected) == 1:
        lines.append("\nOnly one device — all tools route to it automatically; `device` param is optional.")
    else:
        lines.append("")
        lines.append("Multiple devices — every tool call must target one explicitly. Options:")
        lines.append("  - Pass `device=<alias|udid>` to each tool call, OR")
        lines.append("  - Call set_default_device(device='<alias|udid>') once for THIS session.")
        lines.append("Use list_devices() to refresh the live list at any time.")
    return "\n".join(lines)


mcp = FastMCP("ios-device", instructions=_build_instructions())


# ============================================================
#                  DEVICE / SESSION / HOLDER TOOLS
# ============================================================

@mcp.tool
def list_devices() -> dict:
    """List ALL attached iOS devices with udid, alias, model, OS version, holder status.

    Returns {"count": int, "devices": [{"udid", "alias", "model", "device_class",
    "device_name", "os_version", "in_use", "holder", "default_for_session"}, ...]}.

    Always reflects current state — re-runs pymobiledevice3 on every call.
    """
    detected, aliases = _detected_aliased()
    holders = _state_registry.all_status()
    out = []
    for d in detected:
        extras = device_extras(d.serial)
        h = holders.get(d.serial, {})
        out.append({
            "udid": d.serial,
            "alias": aliases.get(d.serial),
            "model": d.model,
            "device_class": extras.get("device_class"),
            "device_name": extras.get("device_name"),
            "os_version": extras.get("os_version"),
            "in_use": h.get("in_use", False),
            "holder": h.get("holder"),
            "default_for_session": False,  # populated below in resource-only paths
        })
    return {"count": len(out), "devices": out}


@mcp.resource("iosfleet://devices")
def devices_resource() -> dict:
    """Live JSON snapshot of all attached iOS devices (re-queries on every read)."""
    return list_devices()


@mcp.tool
def set_default_device(
    device: Annotated[str, Field(description="udid or alias to use as the default for this session")],
    ctx: Context = None,
) -> dict:
    """Set sticky default device for THIS MCP session.

    Subsequent tool calls without an explicit `device` param will route to
    this UDID. Returns {"set": True, "device": <udid>, "alias": <alias>}.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _set_session_default(ctx, udid)
    _, aliases = _detected_aliased()
    return {"set": True, "device": udid, "alias": aliases.get(udid)}


@mcp.tool
def get_default_device(ctx: Context = None) -> dict:
    """Return the sticky default device for this session, if any."""
    udid = _get_session_default(ctx)
    if not udid:
        return {"device": None, "alias": None}
    _, aliases = _detected_aliased()
    return {"device": udid, "alias": aliases.get(udid)}


@mcp.tool
def acquire_ios(
    device: Annotated[str | None, Field(description="udid or alias; omit if only 1 device or you've set a default")] = None,
    holder_name: Annotated[str, Field(description="Human-readable identifier (e.g. 'agent-A')")] = "anonymous",
    ctx: Context = None,
) -> dict:
    """Claim exclusive use of an iOS device. Advisory only — tools still work for others."""
    udid = _resolve_device(device, _get_session_default(ctx))
    r = _state_registry.acquire(udid, holder_name)
    r["device"] = udid
    return r


@mcp.tool
def release_ios(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    holder_name: Annotated[str, Field(description="Must match acquire_ios's holder_name")] = "anonymous",
    ctx: Context = None,
) -> dict:
    """Release the exclusive-use claim. Only the current holder can release."""
    udid = _resolve_device(device, _get_session_default(ctx))
    r = _state_registry.release(udid, holder_name)
    r["device"] = udid
    return r


@mcp.tool
def get_ios_status(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Show whether the specified device is claimed and by whom."""
    udid = _resolve_device(device, _get_session_default(ctx))
    r = _state_registry.status(udid)
    r["device"] = udid
    return r


# ============================================================
#                  UI / SCREEN
# ============================================================

@mcp.tool
def get_screen_size(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Return device screen size {width, height} in points (WDA's coordinate space)."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    size = _wda_for(udid).window_size()
    return {"width": size.get("width"), "height": size.get("height"), "device": udid}


@mcp.tool
def take_screenshot(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> Image:
    """Capture a PNG screenshot of the device. Returns base64-embedded image."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    png_bytes = _wda_for(udid).screenshot_png_bytes()
    return Image(data=png_bytes, format="png")


@mcp.tool
def tap(
    x: Annotated[int, Field(description="X coordinate in points", ge=0)],
    y: Annotated[int, Field(description="Y coordinate in points", ge=0)],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Tap the screen at (x, y) in WDA's coordinate space (points)."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).tap(x, y)
    return {"ok": True, "x": x, "y": y, "device": udid}


@mcp.tool
def swipe(
    x1: Annotated[int, Field(description="Start X", ge=0)],
    y1: Annotated[int, Field(description="Start Y", ge=0)],
    x2: Annotated[int, Field(description="End X", ge=0)],
    y2: Annotated[int, Field(description="End Y", ge=0)],
    duration_ms: Annotated[int, Field(description="Swipe duration in ms", ge=50, le=10000)] = 300,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Swipe from (x1,y1) to (x2,y2) over duration_ms milliseconds."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).swipe(x1, y1, x2, y2, duration_ms)
    return {"ok": True, "from": (x1, y1), "to": (x2, y2), "duration_ms": duration_ms, "device": udid}


@mcp.tool
def long_press(
    x: Annotated[int, Field(description="X coordinate", ge=0)],
    y: Annotated[int, Field(description="Y coordinate", ge=0)],
    duration_ms: Annotated[int, Field(description="Hold duration in ms", ge=50, le=10000)] = 800,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Touch and hold at (x, y) for duration_ms milliseconds."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).touch_and_hold(x, y, duration_ms)
    return {"ok": True, "x": x, "y": y, "duration_ms": duration_ms, "device": udid}


@mcp.tool
def press_button(
    button: Annotated[
        str,
        Field(description="Physical button name: home | volume_up | volume_down | lock"),
    ],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Press a system button on the device.

    Supported by WDA: home, volume_up, volume_down, lock.
    Keyboard text input uses type_text instead (iOS has no concept of physical keys).
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).press_button(button)
    return {"ok": True, "button": button, "device": udid}


@mcp.tool
def type_text(
    text: Annotated[str, Field(description="Text to type via the on-screen keyboard")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Type text into the currently-focused input. The keyboard must already be visible.

    iOS routes this via /wda/keys which delegates to UIKit; some apps with
    custom text fields may not receive the input. If type_text doesn't land,
    fall back to tap() + clipboard paste flow.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).type_keys(text)
    return {"ok": True, "chars": len(text), "device": udid}


# ============================================================
#                  UI HIERARCHY / ELEMENTS
# ============================================================

@mcp.tool
def dump_ui_hierarchy(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Dump the current screen's UI element tree via WDA /source.

    Returns JSON tree of XCUIElement nodes with type, name, label, value,
    rect (x/y/width/height), enabled, visible flags. Use find_elements()
    for substring filtering or tap_element() for the common find+tap path.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    src = _wda_for(udid).page_source(fmt="json")
    return {"ok": True, "tree": src, "device": udid}


@mcp.tool
def find_elements(
    using: Annotated[
        str,
        Field(description="Locator strategy: 'class chain' (recommended) | 'xpath' | 'predicate string' | 'name' | 'accessibility id'"),
    ] = "class chain",
    value: Annotated[
        str,
        Field(description="Locator value. Class chain example: **/XCUIElementTypeButton[`name == \"Done\"`]"),
    ] = "",
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Find UI elements via a WDA locator strategy.

    Returns list of element handles {ELEMENT, type, name, label, rect}.
    Pass any handle's ELEMENT to tap_element() to interact.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    elements = _wda_for(udid).find_elements(using, value)
    return {"ok": True, "count": len(elements), "elements": elements, "device": udid}


@mcp.tool
def tap_element(
    element_id: Annotated[
        str | None,
        Field(description="WDA element ELEMENT id from find_elements. If None, supply using+value below."),
    ] = None,
    using: Annotated[
        str | None,
        Field(description="If element_id is None: locator strategy. Same options as find_elements."),
    ] = None,
    value: Annotated[
        str | None,
        Field(description="If element_id is None: locator value."),
    ] = None,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Tap a UI element. Either pass element_id directly, or (using, value) to find-and-tap."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    client = _wda_for(udid)
    if element_id is None:
        if not using or not value:
            return {"ok": False, "error": "must pass element_id OR (using AND value)"}
        elements = client.find_elements(using, value)
        if not elements:
            return {"ok": False, "error": f"no elements found for {using}={value!r}"}
        element_id = elements[0]["ELEMENT"]
    client.click_element(element_id)
    return {"ok": True, "element_id": element_id, "device": udid}


# ============================================================
#                  APP LIFECYCLE
# ============================================================

@mcp.tool
def current_app(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Return info about the currently foregrounded app (bundleId, name, pid, processArguments)."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    info = _wda_for(udid).active_app_info()
    return {"ok": True, "info": info, "device": udid}


@mcp.tool
def list_apps(
    filter_substring: Annotated[
        Optional[str],
        Field(description="Filter bundle IDs containing this substring; None = all"),
    ] = None,
    only_user: Annotated[bool, Field(description="Only user-installed apps (skip system)")] = True,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """List installed apps on the device.

    Returns {count, apps: [{bundleId, name, version}, ...]} via pymobiledevice3
    installation_proxy.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    filter_args = ["--type", "User"] if only_user else ["--type", "Any"]
    r = _run_pmd(["apps", "list", "--udid", udid] + filter_args, timeout=25)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"], "device": udid, **_diag(r)}
    # pmd `apps list` returns JSON-like text — try parse, else surface raw
    import json as _json
    try:
        data = _json.loads(r["stdout"])
        items = []
        for bid, meta in data.items():
            if filter_substring and filter_substring not in bid:
                continue
            items.append({
                "bundleId": bid,
                "name": meta.get("CFBundleDisplayName") or meta.get("CFBundleName"),
                "version": meta.get("CFBundleShortVersionString"),
            })
        return {"ok": True, "count": len(items), "apps": items, "device": udid}
    except Exception as exc:
        return {"ok": True, "raw": r["stdout"][:2000], "parse_error": str(exc), "device": udid}


@mcp.tool
def install_ipa(
    ipa_path: Annotated[str, Field(description="Absolute path to .ipa on the HOST (macmini)")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Install an .ipa onto the device. `pymobiledevice3 apps install`.

    Note: subprocess timeout is hard-capped at 25s (fastmcp transport limit).
    On USB 2.0 (~30MB/s) this covers ipas up to ~500MB. Large bundles need a
    follow-up async install API (planned).
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    p = Path(ipa_path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"ipa not found: {ipa_path}", "device": udid}
    r = _run_pmd(["apps", "install", str(p), "--udid", udid], timeout=120)
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], "device": udid, **_diag(r)}
    return {"ok": True, "ipa": str(p), "device": udid}


@mcp.tool
def uninstall_app(
    bundle_id: Annotated[str, Field(description="Bundle ID to uninstall, e.g. 'com.example.MyApp'")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Uninstall an app by bundle ID. `pymobiledevice3 apps uninstall`."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    r = _run_pmd(["apps", "uninstall", bundle_id, "--udid", udid], timeout=30)
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], "device": udid, **_diag(r)}
    return {"ok": True, "bundle_id": bundle_id, "device": udid}


@mcp.tool
def start_app(
    bundle_id: Annotated[str, Field(description="Bundle ID to launch, e.g. 'com.apple.MobileSafari'")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Launch an app by bundle ID via WDA /wda/apps/launch."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).launch_app(bundle_id)
    return {"ok": True, "bundle_id": bundle_id, "device": udid}


@mcp.tool
def terminate_app(
    bundle_id: Annotated[str, Field(description="Bundle ID to terminate")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Force-terminate an app by bundle ID via WDA /wda/apps/terminate."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).terminate_app(bundle_id)
    return {"ok": True, "bundle_id": bundle_id, "device": udid}


@mcp.tool
def activate_app(
    bundle_id: Annotated[str, Field(description="Bundle ID to bring to foreground (must be already running)")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Activate a backgrounded app (bring to foreground) via WDA /wda/apps/activate."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).activate_app(bundle_id)
    return {"ok": True, "bundle_id": bundle_id, "device": udid}


# ============================================================
#                  FILE TRANSFER (limited by iOS sandbox)
# ============================================================

@mcp.tool
def push_file_to_app(
    host_path: Annotated[str, Field(description="Absolute path on the HOST (macmini)")],
    bundle_id: Annotated[str, Field(description="Target app's bundle ID (file goes into its Documents sandbox)")],
    device_relpath: Annotated[
        str,
        Field(description="Relative path inside the app's Documents dir, e.g. 'inbox/foo.txt'"),
    ],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Copy a host file into an app's Documents sandbox via house_arrest/afc.

    Limited to apps with `UIFileSharingEnabled=true` in their Info.plist (i.e.
    "Files app" visible apps). System apps and most third-party apps without
    this flag will reject the push.

    Note: subprocess timeout hard-capped at 25s — large files need split.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    p = Path(host_path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"host file not found: {host_path}", "device": udid}
    r = _run_pmd(
        ["apps", "afc", "push", "--bundle-id", bundle_id, str(p), device_relpath, "--udid", udid],
        timeout=300,
    )
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], "device": udid, **_diag(r)}
    return {"ok": True, "host": str(p), "device_relpath": device_relpath, "bundle_id": bundle_id, "device": udid}


@mcp.tool
def pull_file_from_app(
    bundle_id: Annotated[str, Field(description="Source app's bundle ID")],
    device_relpath: Annotated[str, Field(description="Relative path inside Documents")],
    host_path: Annotated[str, Field(description="Destination path on HOST (parent dir must exist)")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Copy a file out of an app's Documents sandbox to the host."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    h = Path(host_path).expanduser()
    h.parent.mkdir(parents=True, exist_ok=True)
    r = _run_pmd(
        ["apps", "afc", "pull", "--bundle-id", bundle_id, device_relpath, str(h), "--udid", udid],
        timeout=300,
    )
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], "device": udid, **_diag(r)}
    return {"ok": True, "device_relpath": device_relpath, "host": str(h), "bundle_id": bundle_id, "device": udid}


# ============================================================
#                  DEVICE INFO (iOS-specific)
# ============================================================

@mcp.tool
def device_info(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Return device info: OS version, build, model, battery, storage.

    Combines pymobiledevice3 lockdown + diagnostics. Battery info requires
    iOS 11+; storage requires the developer disk image to be mounted on iOS 17+.
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    extras = device_extras(udid)
    # battery — separate diagnostics call (may fail on locked devices)
    bat = _run_pmd(["diagnostics", "battery", "--udid", udid], timeout=10)
    battery: Any = None
    if bat["returncode"] == 0 and bat["stdout"]:
        import json as _json
        try:
            battery = _json.loads(bat["stdout"])
        except Exception:
            battery = bat["stdout"][:500]
    return {
        "ok": True,
        "udid": udid,
        "device_class": extras.get("device_class"),
        "device_name": extras.get("device_name"),
        "os_version": extras.get("os_version"),
        "build_version": extras.get("build_version"),
        "battery": battery,
    }


# ============================================================
#                       ENTRY POINT
# ============================================================

if __name__ == "__main__":
    # Line-buffer stdio so log redirection from launchd / manual launchers
    # flushes in real time instead of waiting for server exit.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)

    print("ios-device MCP server starting")
    print(f"  python    = {sys.executable}")
    try:
        detected, aliases = _detected_aliased()
        if not detected:
            print("  devices   = NONE")
            print("  WARNING: server will start but tools will fail until a device appears (and WDA is deployed).")
        else:
            print(f"  devices   = {len(detected)} attached")
            for d in detected:
                alias = aliases.get(d.serial, "(no alias)")
                extras = device_extras(d.serial)
                print(f"    - {alias}  ({d.serial[:8]}…, {extras.get('device_class', '?')} iOS {extras.get('os_version', '?')})")
                # Pre-start the forward so WDA is reachable when the first tool fires.
                # If WDA isn't deployed yet, start() will fail after 5s — that's fine,
                # the per-tool _ensure_forwarder_and_client() will retry on demand.
                try:
                    _ensure_forwarder_and_client(d.serial)
                except Exception as exc:
                    print(f"      WARN forwarder failed: {exc}")
    except Exception as exc:
        print(f"  device detection failed: {exc}")

    print("  transport = http (streamable) on 0.0.0.0:8769/mcp")
    mcp.run(transport="http", host="0.0.0.0", port=8769)
