"""iOS MCP Server (ios-device) — v0.8.0-alpha.

FastMCP server bridging an LLM agent to one or more iOS devices via:
  - pymobiledevice3 — device discovery, app install/uninstall, lockdown info
  - WebDriverAgent (WDA) — UI operations (tap/swipe/screenshot/elements)

Architecture mirrors android-device v0.7.x exactly:
  - Single MCP entry on 0.0.0.0:8769/mcp (streamable-http)
  - 26 tools (24 mirror Android + activate_app + device_info; drop run_shell)
  - All tools accept optional `device` parameter (UDID or alias)
  - Alias map auto-derived from ProductType, override via
    ~/.agent-fleet/ios-aliases.json
  - Per-device holder advisory lock (acquire / release)
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
  - install_app / push_file / pull_file warn for large files
"""

from __future__ import annotations

import asyncio
import inspect
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
from _manifest import load_manifest
from capabilities import (
    CapabilityRegistry,
    CoreCapability,
    current_host_os,
    resolve_enabled_capabilities,
)


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
            "hint": "Long pymobiledevice3 ops (install_app with big bundles) exceed the fastmcp transport deadline. See jlowin/fastmcp#823.",
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

# 文件上传支撑（设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md）
import time  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

import _uploads_ios as up_ios  # noqa: E402
from _upload_common import (  # noqa: E402
    UploadError as _UploadError,
    URL_HARD_MAX as _URL_HARD_MAX,
    UPLOADS_DIR as _UPLOADS_DIR,
    ensure_dirs as _common_ensure_dirs,
    require_xor as _require_xor,
    decode_b64 as _decode_b64,
    download_url as _download_url,
    parse_bool as _parse_bool,
)


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
def acquire(
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
def release(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    holder_name: Annotated[str, Field(description="Must match acquire's holder_name")] = "anonymous",
    ctx: Context = None,
) -> dict:
    """Release the exclusive-use claim. Only the current holder can release."""
    udid = _resolve_device(device, _get_session_default(ctx))
    r = _state_registry.release(udid, holder_name)
    r["device"] = udid
    return r


@mcp.tool
def get_status(
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
    region: Annotated[list[int] | None, Field(description="[x,y,w,h] crop; None=full screen (crop not yet implemented)")] = None,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> Image:
    """Capture a PNG screenshot of the device. Returns base64-embedded image.

    `region` accepted for canonical-contract parity; cropping is not implemented
    yet (full screen always returned). TODO: implement crop via PIL.
    """
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
def press_key(
    key: Annotated[
        str,
        Field(description="Physical button name: home | volume_up | volume_down | lock"),
    ],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Press a physical button on the device.

    iOS supports the physical buttons: home, volume_up, volume_down, lock.
    Keyboard text input uses type_text instead (iOS has no concept of physical keys).
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).press_key(key)
    return {"ok": True, "key": key, "device": udid}


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
def dump_ui(
    max_depth: Annotated[int | None, Field(description="Optional depth limit for the UI tree; currently advisory (WDA returns the full tree, depth limit is not enforced).")] = None,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Dump the current screen's UI element tree via WDA /source.

    Returns JSON tree of XCUIElement nodes with type, name, label, value,
    rect (x/y/width/height), enabled, visible flags. Use find_elements()
    for substring filtering or tap_element() for the common find+tap path.

    max_depth: optional depth limit; currently advisory — WDA returns the full
    tree regardless. Pass None (default) to always get the complete tree.
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
def install_app(
    path: Annotated[str, Field(description="Absolute path to .ipa on the HOST (macmini)")],
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
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"ipa not found: {path}", "device": udid}
    r = _run_pmd(["apps", "install", str(p), "--udid", udid], timeout=120)
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], "device": udid, **_diag(r)}
    return {"ok": True, "path": str(p), "device": udid}


@mcp.tool
def uninstall_app(
    target: Annotated[str, Field(description="Bundle ID to uninstall, e.g. 'com.example.MyApp'")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Uninstall an app by bundle ID. `pymobiledevice3 apps uninstall`."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    r = _run_pmd(["apps", "uninstall", target, "--udid", udid], timeout=30)
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], "device": udid, **_diag(r)}
    return {"ok": True, "target": target, "device": udid}


@mcp.tool
def launch_app(
    target: Annotated[str, Field(description="Bundle ID to launch, e.g. 'com.apple.MobileSafari'")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Launch an app by bundle ID via WDA /wda/apps/launch."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).launch_app(target)
    return {"ok": True, "target": target, "device": udid}


@mcp.tool
def terminate_app(
    target: Annotated[str, Field(description="Bundle ID to terminate")],
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Force-terminate an app by bundle ID via WDA /wda/apps/terminate."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    _wda_for(udid).terminate_app(target)
    return {"ok": True, "target": target, "device": udid}


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
#                  FILE TRANSFER (app sandbox via house_arrest/afc)
# ============================================================

# pymobiledevice3 9.x exposes afc only as an interactive shell on the CLI
# (incompatible with non-interactive subprocess calls, and it prompts for a
# device on multi-device hosts). We use the Python house_arrest API instead.
# Its methods are a mix of sync and async across versions, so _aw() awaits
# only the coroutine ones. The whole flow runs in a fresh event loop via
# asyncio.run — safe because FastMCP runs sync tool handlers on worker threads
# (no running loop there).

async def _aw(result):
    """Await result if it's a coroutine, else return as-is (handles afc's
    sync/async method mix across pymobiledevice3 versions)."""
    return await result if inspect.iscoroutine(result) else result


def _afc_op(udid: str, bundle_id: str, documents_only: bool, op):
    """Open a house_arrest afc session for bundle_id on udid, run async `op(ha)`,
    always close. Raises on failure (caller wraps for a friendly tool error)."""
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.house_arrest import HouseArrestService

    async def _run():
        lockdown = await create_using_usbmux(serial=udid)
        ha = HouseArrestService(lockdown=lockdown, documents_only=documents_only)
        try:
            await _aw(ha.send_command(bundle_id))
            return await op(ha)
        finally:
            await _aw(ha.aclose())

    return asyncio.run(_run())


_AFC_HINT = (
    "App must be reachable via house_arrest: either UIFileSharingEnabled=true "
    "(documents_only=True; path is relative to the app's Documents dir), or "
    "dev-signed (documents_only=False; path relative to container root, e.g. "
    "'Documents/foo.txt'). System apps and 3rd-party apps without file sharing "
    "raise InstallationLookupFailed."
)


@mcp.tool
def push_file_to_app(
    host_path: Annotated[str, Field(description="Absolute path on the HOST (macmini)")],
    bundle_id: Annotated[str, Field(description="Target app's bundle ID")],
    device_relpath: Annotated[
        str,
        Field(description="Destination path inside the app sandbox. With documents_only=True it's relative to Documents (e.g. 'inbox/foo.txt'); with documents_only=False it's relative to container root (e.g. 'Documents/foo.txt')."),
    ],
    documents_only: Annotated[bool, Field(description="True: Documents-only (UIFileSharingEnabled apps). False: full container (dev-signed apps only).")] = True,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Copy a host file into an app's sandbox via house_arrest/afc.

    Only works for apps reachable via house_arrest (UIFileSharingEnabled apps
    with documents_only=True, or dev-signed apps with documents_only=False).
    """
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    p = Path(host_path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"host file not found: {host_path}", "device": udid}
    try:
        async def _op(ha):
            await _aw(ha.push(str(p), device_relpath))
        _afc_op(udid, bundle_id, documents_only, _op)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "hint": _AFC_HINT, "device": udid}
    return {"ok": True, "host": str(p), "device_relpath": device_relpath,
            "bundle_id": bundle_id, "documents_only": documents_only, "device": udid}


@mcp.tool
def pull_file_from_app(
    bundle_id: Annotated[str, Field(description="Source app's bundle ID")],
    device_relpath: Annotated[str, Field(description="Source path inside the app sandbox (same relativity rules as push_file_to_app's device_relpath).")],
    host_path: Annotated[str, Field(description="Destination path on HOST (parent dir auto-created)")],
    documents_only: Annotated[bool, Field(description="True: Documents-only (UIFileSharingEnabled apps). False: full container (dev-signed apps only).")] = True,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> dict:
    """Copy a file out of an app's sandbox to the host via house_arrest/afc."""
    udid = _resolve_device(device, _get_session_default(ctx))
    _state_registry.touch(udid)
    h = Path(host_path).expanduser()
    h.parent.mkdir(parents=True, exist_ok=True)
    try:
        async def _op(ha):
            await _aw(ha.pull(device_relpath, str(h)))
        _afc_op(udid, bundle_id, documents_only, _op)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "hint": _AFC_HINT, "device": udid}
    return {"ok": True, "device_relpath": device_relpath, "host": str(h),
            "bundle_id": bundle_id, "documents_only": documents_only, "device": udid}


# ============================================================
#       AGENT → iOS UPLOAD（HTTP /upload + 3 MCP 工具）
#       设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md
# ============================================================

def _http_upload_worker(target: str, body: bytes, params: dict, udid: str) -> dict:
    """同步执行（在 threadpool）。target=photos → WDA；target=app → afc。"""
    if target == "photos":
        return up_ios.wda_photos_import(body, filename=params.get("filename", "upload.bin"),
                                         ttype=params["type"])
    elif target == "app":
        # afc 需要 host_path 实文件 → 先落 mac 暂存再 push
        import uuid as _uuid
        _common_ensure_dirs()
        tmp = _UPLOADS_DIR / f"ios_http_{_uuid.uuid4().hex}"
        try:
            tmp.write_bytes(body)
            return up_ios.afc_push_to_app(
                udid=udid, bundle_id=params["bundle_id"],
                documents_only=params.get("documents_only", True),
                host_path=str(tmp), device_relpath=params["relpath"],
                afc_op=_afc_op,
            )
        finally:
            tmp.unlink(missing_ok=True)
    return {"ok": False, "error": f"unknown target: {target}"}


@mcp.custom_route("/upload", methods=["POST"])
async def http_upload(request: Request) -> JSONResponse:
    """POST 文件字节 → target=photos 走 WDA / target=app 走 afc。

    Query: target(photos|app, 默 photos)、filename、bundle_id、relpath、
           documents_only、device。
    Body: raw（--data-binary）或 multipart（file 字段）。
    """
    try:
        qp = request.query_params
        target = qp.get("target", "photos")
        filename = qp.get("filename")
        bundle_id = qp.get("bundle_id")
        relpath = qp.get("relpath")
        documents_only = _parse_bool(qp.get("documents_only"), True)
        device = qp.get("device")

        clen = request.headers.get("content-length")
        if clen and clen.isdigit() and int(clen) > _URL_HARD_MAX:
            return JSONResponse({"ok": False, "error": f"超过上限 {_URL_HARD_MAX} 字节"}, status_code=413)

        # 流式读 body（小内存）；支持 multipart 与 raw 两种
        ctype = request.headers.get("content-type", "")
        buf = bytearray()
        size = 0
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            f = form.get("file")
            if f is None or not hasattr(f, "read"):
                return JSONResponse({"ok": False, "error": "multipart 缺 file 字段"}, status_code=400)
            filename = filename or getattr(f, "filename", None)
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _URL_HARD_MAX:
                    return JSONResponse({"ok": False, "error": f"超过上限 {_URL_HARD_MAX} 字节"}, status_code=413)
                buf.extend(chunk)
        else:
            async for chunk in request.stream():
                size += len(chunk)
                if size > _URL_HARD_MAX:
                    return JSONResponse({"ok": False, "error": f"超过上限 {_URL_HARD_MAX} 字节"}, status_code=413)
                buf.extend(chunk)

        if size == 0:
            return JSONResponse({"ok": False, "error": "空请求体"}, status_code=400)

        fname, params = up_ios.resolve_target(target, filename, bundle_id, relpath)
        params["filename"] = fname  # photos worker 透传文件名作 X-Filename
        if target == "app":
            params["documents_only"] = documents_only
        udid = _resolve_device(device, None)
        _state_registry.touch(udid)

        result = await run_in_threadpool(
            _http_upload_worker, target, bytes(buf), params, udid)
        result.setdefault("target", target)
        result.setdefault("device", udid)
        result.setdefault("size", size)
        return JSONResponse(result, status_code=200 if result.get("ok") else 500)
    except _UploadError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)


@mcp.tool
def upload_to_photos(
    content_base64: Annotated[Optional[str], Field(description="文件字节 base64；与 url 二选一")] = None,
    url: Annotated[Optional[str], Field(description="http/https 链接；与 content_base64 二选一")] = None,
    filename: Annotated[Optional[str], Field(description="原文件名（必填，决定 image/video）")] = None,
    device: Annotated[Optional[str], Field(description="udid 或 alias")] = None,
    ctx: Context = None,
) -> dict:
    """同步上传图片/视频到 iOS Photos 相册（小文件 base64；大文件用 HTTP POST /upload）。

    返回 {ok, target:'photos', device, asset_id?, error?, size}。首次写入会触发
    设备相册授权弹窗，按提示在 设置→隐私→照片→WebDriverAgent→添加照片 中允许。
    """
    import uuid as _uuid
    try:
        _require_xor(content_base64, url, ("content_base64", "url"))
        if not filename:
            raise _UploadError("upload_to_photos 必须提供 filename")
        fname, params = up_ios.resolve_target("photos", filename, None, None)
        udid = _resolve_device(device, _get_session_default(ctx))
        _state_registry.touch(udid)
        if content_base64 is not None:
            body = _decode_b64(content_base64)
            if len(body) > 6 * 1024 * 1024:
                return {"ok": False, "error": "超过同步上限 6MB（base64 解码后）",
                        "hint": "用 HTTP POST /upload 端点上传任意大小"}
        else:
            _common_ensure_dirs()
            tmp = _UPLOADS_DIR / f"ios_sync_{_uuid.uuid4().hex}"
            try:
                _download_url(url, tmp, max_bytes=20 * 1024 * 1024)
                body = tmp.read_bytes()
            finally:
                tmp.unlink(missing_ok=True)
        res = up_ios.wda_photos_import(body, filename=fname, ttype=params["type"])
        res.setdefault("target", "photos")
        res.setdefault("device", udid)
        res.setdefault("size", len(body))
        return res
    except _UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def upload_to_app(
    bundle_id: Annotated[str, Field(description="目标 app bundle id")],
    relpath: Annotated[str, Field(description="app 沙盒内相对路径（默 Documents 下；documents_only=True）")],
    content_base64: Annotated[Optional[str], Field(description="文件字节 base64；与 url 二选一")] = None,
    url: Annotated[Optional[str], Field(description="http/https 链接；与 content_base64 二选一")] = None,
    documents_only: Annotated[bool, Field(description="True=Documents-only；False=full container（dev-signed apps）")] = True,
    device: Annotated[Optional[str], Field(description="udid 或 alias")] = None,
    ctx: Context = None,
) -> dict:
    """推 agent 字节到指定 app 沙盒（等价 push_file_to_app，但字节来自 agent）。"""
    import uuid as _uuid
    try:
        _require_xor(content_base64, url, ("content_base64", "url"))
        fname, params = up_ios.resolve_target("app", None, bundle_id, relpath)
        udid = _resolve_device(device, _get_session_default(ctx))
        _state_registry.touch(udid)
        _common_ensure_dirs()
        tmp = _UPLOADS_DIR / f"ios_app_{_uuid.uuid4().hex}"
        try:
            if content_base64 is not None:
                tmp.write_bytes(_decode_b64(content_base64))
            else:
                _download_url(url, tmp, max_bytes=20 * 1024 * 1024)
            res = up_ios.afc_push_to_app(
                udid=udid, bundle_id=bundle_id, documents_only=documents_only,
                host_path=str(tmp), device_relpath=relpath, afc_op=_afc_op,
            )
            res.setdefault("target", "app")
            res.setdefault("device", udid)
            res.setdefault("size", tmp.stat().st_size)
            return res
        finally:
            tmp.unlink(missing_ok=True)
    except _UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def get_upload_endpoint(ctx: Context = None) -> dict:
    """返回 /upload HTTP 端点用法（直接 POST 文件字节，绕过 base64/分片）。"""
    return {
        "ok": True,
        "method": "POST",
        "path": "/upload",
        "port": 8769,
        "params": ("target=photos|app（默 photos）、filename（photos 必填）、"
                   "bundle_id+relpath（app 必填）、documents_only、device"),
        "hint": ("host 同 ios-device MCP 的 URL。例:\n"
                 "  curl -X POST --data-binary @bg.png "
                 "'http://<ios-host>:8769/upload?target=photos&filename=bg.png&device=<udid|alias>'\n"
                 "首次相册写入需在设备 设置→隐私→照片→WebDriverAgent→添加照片 中允许。"),
    }


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
#                  CAPABILITY MODULE FRAMEWORK
# ============================================================
# core tools (above) stay inline — registered the normal way (zero behavior
# change). The registry adds list_capabilities() and registers optional
# capability modules (browser, ...) when enabled in config. Static registration
# at import → the client defers tool schemas (design §1), no upfront token cost.
_PLATFORM_DIR = Path(__file__).resolve().parent.parent      # platforms/ios
_REPO_ROOT = _PLATFORM_DIR.parent.parent                    # repo root
try:
    _enabled_caps = resolve_enabled_capabilities(
        load_manifest(_PLATFORM_DIR / "platform.toml").capabilities, _REPO_ROOT
    )
except Exception as e:  # never let capability config crash server startup
    print(f"[capabilities] config load failed, defaulting to core only: "
          f"{type(e).__name__}: {e}", file=sys.stderr)
    _enabled_caps = ["core"]

_cap_registry = CapabilityRegistry(host_os=current_host_os())
_cap_registry.add(CoreCapability(skill="using-ios"))
_cap_registry.setup(mcp, _enabled_caps)


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
