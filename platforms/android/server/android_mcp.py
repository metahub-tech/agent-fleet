"""Android MCP Server (android-gui).

FastMCP server bridging an LLM agent to one Android device via raw ADB.
Mirrors the architecture of winpc-gui / macbox-gui (state model, FastMCP,
streamable-http on Tailscale, advisory single-holder coordination), with
platform-specific tools for touch / keys / app management / shell-on-device.

v0.4.0 design: pure adb commands, no uiautomator2 / scrcpy dependency.
This avoids pushing a JSON-RPC server APK to OEM-locked-down ROMs (Huawei
HarmonyOS / MIUI / etc.) on first deploy. UI introspection (`dump_xml`,
`find_by_resource_id`) is deferred to v0.4.1 when uiautomator2 will land
behind a feature flag.

Transport: streamable-http on 0.0.0.0:8768/mcp.

Single-device assumption: the host running this server has exactly one
authorized device in `adb devices`. If 0 or >1 devices are present, tools
fail loudly with an actionable error. Multi-device (acquire by serial) is
roadmap'd to v0.5.

Connection mode (USB / Wireless / Hybrid) is the operator's choice at
host-setup time; the server itself is mode-agnostic and only requires
that `adb devices` shows the target.

ADB binary resolution order:
  1. ATB_ANDROID_ADB env var (absolute path)
  2. `adb` on PATH
  3. Known SDK locations (Win: %LOCALAPPDATA%\\Android\\Sdk\\platform-tools)
  4. Error if not found.
"""

from __future__ import annotations

import functools
import io
import os
import platform as host_platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from PIL import Image as PILImage
from pydantic import Field

from fastmcp import FastMCP
from fastmcp.utilities.types import Image


mcp = FastMCP("android-gui")


# ============================================================
#                    ADB BINARY RESOLUTION
# ============================================================

def _resolve_adb() -> str:
    if env := os.environ.get("ATB_ANDROID_ADB"):
        if Path(env).is_file():
            return env
    if path := shutil.which("adb"):
        return path
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
        Path("/opt/homebrew/bin/adb"),
        Path("/usr/local/bin/adb"),
        Path("/usr/bin/adb"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError(
        "adb not found. Set ATB_ANDROID_ADB=/path/to/adb or install platform-tools."
    )


_ADB = _resolve_adb()


def _adb_run(args: list[str], timeout: int = 30, capture_bytes: bool = False) -> dict:
    """Run an adb command with timeout. Returns dict with stdout/stderr/returncode.

    capture_bytes=True returns raw bytes in 'stdout_bytes' (for screencap).
    """
    cmd = [_ADB] + args
    try:
        proc = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"adb command timed out after {timeout}s", "stdout_bytes": b""}
    out: dict = {
        "returncode": proc.returncode,
        "stderr": proc.stderr.decode("utf-8", errors="replace"),
    }
    if capture_bytes:
        out["stdout_bytes"] = proc.stdout
        out["stdout"] = ""
    else:
        out["stdout"] = proc.stdout.decode("utf-8", errors="replace")
    return out


def _adb_shell(cmd: str, timeout: int = 30, capture_bytes: bool = False) -> dict:
    """`adb shell <cmd>`. Convenience wrapper."""
    if capture_bytes:
        return _adb_run(["exec-out"] + cmd.split(), timeout=timeout, capture_bytes=True)
    return _adb_run(["shell", cmd], timeout=timeout)


def _ensure_one_device() -> str:
    r = _adb_run(["devices"], timeout=10)
    if r["returncode"] != 0:
        raise RuntimeError(f"adb devices failed: {r['stderr']}")
    lines = [ln for ln in r["stdout"].splitlines() if "\tdevice" in ln]
    if not lines:
        raise RuntimeError(
            "no authorized Android device found. Plug a phone via USB and accept "
            "the 'Allow USB debugging' prompt, or pair via Wireless Debugging."
        )
    if len(lines) > 1:
        serials = [ln.split("\t")[0] for ln in lines]
        raise RuntimeError(
            f"multiple devices attached ({serials}); v0.4.0 supports only one at a time. "
            f"Set ATB_ANDROID_SERIAL or unplug others."
        )
    return lines[0].split("\t")[0]


# ============================================================
#                     IN-USE STATE TRACKING
# ============================================================

@dataclass
class _Holder:
    name: str
    acquired_at: datetime
    last_used_at: datetime


_state_lock = threading.Lock()
_holder: Optional[_Holder] = None
_IDLE_TIMEOUT = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_idle_release_locked() -> None:
    global _holder
    if _holder is not None and (_now() - _holder.last_used_at) > _IDLE_TIMEOUT:
        _holder = None


def _touch() -> None:
    with _state_lock:
        _check_idle_release_locked()
        if _holder is not None:
            _holder.last_used_at = _now()


def with_touch(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _touch()
        return fn(*args, **kwargs)
    return wrapper


@mcp.tool
def acquire_android(
    holder_name: Annotated[
        str,
        Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')"),
    ] = "anonymous",
) -> dict:
    """Claim exclusive use of this Android test device. Advisory only -- tools still work for everyone."""
    global _holder
    with _state_lock:
        _check_idle_release_locked()
        now = _now()
        if _holder is None:
            _holder = _Holder(name=holder_name, acquired_at=now, last_used_at=now)
            return {"acquired": True, "holder": holder_name}
        if _holder.name == holder_name:
            _holder.last_used_at = now
            return {"acquired": True, "holder": holder_name, "note": "already yours"}
        idle = int((now - _holder.last_used_at).total_seconds())
        return {
            "acquired": False,
            "current_holder": _holder.name,
            "since": _holder.acquired_at.isoformat(),
            "idle_seconds": idle,
            "auto_release_in_seconds": max(0, int(_IDLE_TIMEOUT.total_seconds()) - idle),
        }


@mcp.tool
def release_android(
    holder_name: Annotated[str, Field(description="Must match the name used in acquire_android")] = "anonymous",
) -> dict:
    """Release the exclusive-use claim. Only the current holder can release."""
    global _holder
    with _state_lock:
        if _holder is None:
            return {"released": False, "note": "no holder"}
        if _holder.name != holder_name:
            return {
                "released": False,
                "current_holder": _holder.name,
                "you_provided": holder_name,
                "note": "holder_name mismatch -- only the holder can release",
            }
        held = (_now() - _holder.acquired_at).total_seconds()
        _holder = None
        return {"released": True, "held_for_seconds": int(held)}


@mcp.tool
def get_android_status() -> dict:
    """Show whether the device is currently claimed and by whom."""
    with _state_lock:
        _check_idle_release_locked()
        if _holder is None:
            return {"in_use": False, "note": "free for acquire"}
        idle = int((_now() - _holder.last_used_at).total_seconds())
        return {
            "in_use": True,
            "holder": _holder.name,
            "acquired_at": _holder.acquired_at.isoformat(),
            "last_used_at": _holder.last_used_at.isoformat(),
            "idle_seconds": idle,
            "auto_release_in_seconds": max(0, int(_IDLE_TIMEOUT.total_seconds()) - idle),
        }


# ============================================================
#                     DEVICE INFO
# ============================================================

@mcp.tool
@with_touch
def list_devices() -> dict:
    """List all devices visible to adb on this host with their state.

    Returns: {devices: [{serial, state, model?, manufacturer?}], adb_version}.
    """
    r = _adb_run(["devices", "-l"], timeout=10)
    if r["returncode"] != 0:
        return {"error": r["stderr"], "stdout": r["stdout"]}
    # `adb devices -l` output uses whitespace alignment (not tabs):
    #   List of devices attached
    #   MQS0219A10009471       device product:VOG-AL00 model:VOG_AL00 ...
    valid_states = {"device", "offline", "unauthorized", "authorizing", "no permissions"}
    out = []
    for ln in r["stdout"].splitlines():
        if not ln.strip() or ln.startswith("List of devices"):
            continue
        parts = ln.split()
        if len(parts) >= 2 and parts[1] in valid_states:
            rec = {"serial": parts[0], "state": parts[1]}
            for kv in parts[2:]:
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    rec[k] = v
            out.append(rec)
    ver = _adb_run(["version"], timeout=5)
    return {"devices": out, "adb_version": ver["stdout"].splitlines()[0] if ver["stdout"] else ""}


@mcp.tool
@with_touch
def get_screen_size() -> dict:
    """Return the device screen resolution as reported by `wm size`."""
    _ensure_one_device()
    r = _adb_shell("wm size", timeout=5)
    if r["returncode"] != 0:
        return {"error": r["stderr"]}
    # Format: "Physical size: 1080x2340"  (sometimes also "Override size: 720x1560")
    width = height = None
    for line in r["stdout"].splitlines():
        if ":" in line and "x" in line:
            try:
                v = line.split(":", 1)[1].strip()
                w, h = v.split("x")
                width, height = int(w), int(h)
            except (ValueError, IndexError):
                continue
    if width is None:
        return {"error": "could not parse wm size", "raw": r["stdout"]}
    return {"width": width, "height": height, "raw": r["stdout"].strip()}


# ============================================================
#                       SCREEN
# ============================================================

@mcp.tool
@with_touch
def take_screenshot() -> Image:
    """Capture the device screen and return as PNG.

    Uses `adb exec-out screencap -p`, which dumps a PNG to stdout. Resilient
    to OEM locked-down ROMs since it doesn't require pushing any APK.
    """
    _ensure_one_device()
    r = _adb_run(["exec-out", "screencap", "-p"], timeout=15, capture_bytes=True)
    if r["returncode"] != 0 or not r["stdout_bytes"]:
        # Some Huawei ROMs won't `exec-out` cleanly; fall back to push-then-pull
        return _take_screenshot_fallback()
    raw = r["stdout_bytes"]
    if not raw.startswith(b"\x89PNG"):
        return _take_screenshot_fallback()
    return Image(data=raw, format="png")


def _take_screenshot_fallback() -> Image:
    """Fallback: write to /sdcard, pull, read."""
    remote = "/sdcard/atb_screenshot.png"
    r1 = _adb_shell(f"screencap -p {remote}", timeout=10)
    if r1["returncode"] != 0:
        raise RuntimeError(f"screencap failed: {r1['stderr']}")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        local_path = tf.name
    r2 = _adb_run(["pull", remote, local_path], timeout=15)
    if r2["returncode"] != 0:
        raise RuntimeError(f"adb pull failed: {r2['stderr']}")
    _adb_shell(f"rm {remote}", timeout=5)
    raw = Path(local_path).read_bytes()
    Path(local_path).unlink(missing_ok=True)
    return Image(data=raw, format="png")


# ============================================================
#                       TOUCH
# ============================================================

@mcp.tool
@with_touch
def tap(
    x: Annotated[int, Field(ge=0, description="X coordinate in screen pixels")],
    y: Annotated[int, Field(ge=0, description="Y coordinate in screen pixels")],
) -> dict:
    """Tap the screen at (x, y). Coordinates are in the same space as get_screen_size."""
    _ensure_one_device()
    r = _adb_shell(f"input tap {x} {y}", timeout=5)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "x": x, "y": y}


@mcp.tool
@with_touch
def swipe(
    x1: Annotated[int, Field(ge=0, description="Start X")],
    y1: Annotated[int, Field(ge=0, description="Start Y")],
    x2: Annotated[int, Field(ge=0, description="End X")],
    y2: Annotated[int, Field(ge=0, description="End Y")],
    duration_ms: Annotated[int, Field(ge=50, le=10000, description="Swipe duration in ms")] = 300,
) -> dict:
    """Swipe from (x1,y1) to (x2,y2) over duration_ms milliseconds."""
    _ensure_one_device()
    r = _adb_shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}", timeout=15)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "from": (x1, y1), "to": (x2, y2), "duration_ms": duration_ms}


@mcp.tool
@with_touch
def long_press(
    x: int,
    y: int,
    duration_ms: Annotated[int, Field(ge=300, le=10000, description="Hold duration in ms")] = 800,
) -> dict:
    """Long-press at (x, y). Implemented as a 0-distance swipe."""
    _ensure_one_device()
    r = _adb_shell(f"input swipe {x} {y} {x} {y} {duration_ms}", timeout=15)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "x": x, "y": y, "duration_ms": duration_ms}


# ============================================================
#                       KEYBOARD
# ============================================================

# Friendly key-name aliases -> Android KEYCODE_*
_KEY_ALIASES = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "menu": "KEYCODE_MENU",
    "recent": "KEYCODE_APP_SWITCH",
    "app_switch": "KEYCODE_APP_SWITCH",
    "power": "KEYCODE_POWER",
    "wake": "KEYCODE_WAKEUP",
    "sleep": "KEYCODE_SLEEP",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE",
    "enter": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "escape": "KEYCODE_ESCAPE",
    "del": "KEYCODE_DEL",
    "delete": "KEYCODE_DEL",
    "backspace": "KEYCODE_DEL",
    "space": "KEYCODE_SPACE",
    "search": "KEYCODE_SEARCH",
    "camera": "KEYCODE_CAMERA",
}


@mcp.tool
@with_touch
def press_key(
    key: Annotated[
        str,
        Field(description="Key name: back/home/menu/recent/power/wake/volume_up/volume_down/enter/tab/del/space/search/camera"),
    ],
) -> dict:
    """Send a physical / system key to the device. Uses Android KeyEvent."""
    _ensure_one_device()
    code = _KEY_ALIASES.get(key.lower())
    if code is None:
        return {
            "ok": False,
            "error": f"unknown key '{key}'. Allowed: {sorted(_KEY_ALIASES.keys())}",
        }
    r = _adb_shell(f"input keyevent {code}", timeout=5)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "key": key, "keycode": code}


@mcp.tool
@with_touch
def type_text(
    text: Annotated[str, Field(description="Text to type. Whitespace and special chars handled.")],
) -> dict:
    """Type text into the currently focused input. Uses `adb shell input text`.

    NOTE: `adb input text` does NOT support newlines or all unicode. For
    Chinese / emoji / multiline, push to the device clipboard via `am
    broadcast` and paste -- not implemented in v0.4.0.
    """
    _ensure_one_device()
    # `input text` interprets some chars specially. Escape spaces and quotes.
    escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
    r = _adb_shell(f"input text '{escaped}'", timeout=15)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "chars": len(text)}


# ============================================================
#                       APP MANAGEMENT
# ============================================================

@mcp.tool
@with_touch
def list_packages(
    filter_substring: Annotated[
        Optional[str],
        Field(description="Filter package names containing this substring; None = all"),
    ] = None,
    only_user: Annotated[bool, Field(description="Only third-party (non-system) packages")] = True,
) -> dict:
    """List installed app packages. `pm list packages`."""
    _ensure_one_device()
    flag = "-3" if only_user else ""
    r = _adb_shell(f"pm list packages {flag}".strip(), timeout=15)
    if r["returncode"] != 0:
        return {"error": r["stderr"]}
    pkgs = []
    for ln in r["stdout"].splitlines():
        if ln.startswith("package:"):
            p = ln[len("package:"):].strip()
            if filter_substring is None or filter_substring in p:
                pkgs.append(p)
    return {"count": len(pkgs), "packages": pkgs}


@mcp.tool
@with_touch
def install_apk(
    apk_path: Annotated[str, Field(description="Absolute path to .apk on the HOST machine")],
    replace: Annotated[bool, Field(description="-r flag: replace existing")] = True,
    grant_runtime: Annotated[bool, Field(description="-g flag: grant all runtime permissions")] = False,
) -> dict:
    """Install an APK from the host onto the device. `adb install`."""
    _ensure_one_device()
    p = Path(apk_path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"apk not found: {apk_path}"}
    args = ["install"]
    if replace:
        args.append("-r")
    if grant_runtime:
        args.append("-g")
    args.append(str(p))
    r = _adb_run(args, timeout=120)
    if r["returncode"] != 0 or "Success" not in r["stdout"]:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"]}
    return {"ok": True, "apk": str(p)}


@mcp.tool
@with_touch
def uninstall_app(
    package: Annotated[str, Field(description="Package id, e.g. 'com.example.app'")],
) -> dict:
    """Uninstall an app by package id. `adb uninstall`."""
    _ensure_one_device()
    r = _adb_run(["uninstall", package], timeout=30)
    if r["returncode"] != 0 or "Success" not in r["stdout"]:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"]}
    return {"ok": True, "package": package}


@mcp.tool
@with_touch
def start_app(
    package: Annotated[str, Field(description="Package id, e.g. 'com.android.settings'")],
    activity: Annotated[
        Optional[str],
        Field(description="Activity name (e.g. '.MainActivity'). None = use launcher intent."),
    ] = None,
) -> dict:
    """Launch an app. With activity: `am start -n pkg/activity`. Without: `monkey -p pkg`."""
    _ensure_one_device()
    if activity:
        if not activity.startswith("."):
            target = f"{package}/{activity}"
        else:
            target = f"{package}/{package}{activity}"
        r = _adb_shell(f"am start -n {target}", timeout=15)
    else:
        r = _adb_shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", timeout=15)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"], "stdout": r["stdout"]}
    return {"ok": True, "package": package, "stdout": r["stdout"][:500]}


@mcp.tool
@with_touch
def kill_app(
    package: Annotated[str, Field(description="Package id to force-stop")],
) -> dict:
    """Force-stop an app. `am force-stop`."""
    _ensure_one_device()
    r = _adb_shell(f"am force-stop {package}", timeout=10)
    if r["returncode"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "package": package}


@mcp.tool
@with_touch
def current_app() -> dict:
    """Return the package name of the currently focused app on the device.

    Tries multiple dumpsys commands since the format varies across Android
    versions and OEM ROMs (EMUI, MIUI, OneUI, etc.).
    """
    _ensure_one_device()
    import re
    pkg_pattern = re.compile(r"([a-zA-Z][\w.]+\.[\w.]+)/[\w.$]+")

    # Strategy 1: dumpsys window (compact, has mCurrentFocus near top)
    for cmd, key in [
        ("dumpsys window", "mCurrentFocus"),
        ("dumpsys window", "mFocusedApp"),
        ("dumpsys activity activities", "mResumedActivity"),
        ("dumpsys activity activities", "topResumedActivity"),
        ("dumpsys window windows", "mCurrentFocus"),
    ]:
        r = _adb_shell(cmd, timeout=10)
        if r["returncode"] != 0:
            continue
        for ln in r["stdout"].splitlines():
            if key in ln:
                m = pkg_pattern.search(ln)
                if m:
                    return {"package": m.group(1), "via": f"{cmd} -> {key}", "raw": ln.strip()}

    return {"error": "could not find current focus", "tried": "dumpsys window/activity"}


# ============================================================
#                       SHELL
# ============================================================

@mcp.tool
@with_touch
def adb_shell(
    command: Annotated[str, Field(description="Shell command to run ON the device")],
    timeout: Annotated[int, Field(ge=1, le=120, description="Seconds")] = 30,
) -> dict:
    """Run an arbitrary shell command on the Android device.

    Useful for `getprop`, `dumpsys`, `pm`, `am`, `settings`, `cmd`, etc.
    Output > 100KB is truncated.
    """
    _ensure_one_device()
    r = _adb_shell(command, timeout=timeout)
    out = r["stdout"]
    if len(out) > 100_000:
        out = out[:100_000] + f"\n[... truncated, total {len(r['stdout'])} chars]"
    return {
        "returncode": r["returncode"],
        "stdout": out,
        "stderr": r["stderr"],
    }


# ============================================================
#                  HOST <-> DEVICE FILE TRANSFER
# ============================================================

@mcp.tool
@with_touch
def push_file(
    host_path: Annotated[str, Field(description="Absolute path on the HOST")],
    device_path: Annotated[str, Field(description="Destination path on the DEVICE (e.g. /sdcard/foo.txt)")],
) -> dict:
    """Copy a file from host to device. `adb push`."""
    _ensure_one_device()
    h = Path(host_path).expanduser()
    if not h.is_file():
        return {"ok": False, "error": f"host file not found: {host_path}"}
    r = _adb_run(["push", str(h), device_path], timeout=300)
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"]}
    return {"ok": True, "host": str(h), "device": device_path, "size": h.stat().st_size}


@mcp.tool
@with_touch
def pull_file(
    device_path: Annotated[str, Field(description="Source path on the DEVICE")],
    host_path: Annotated[str, Field(description="Destination path on the HOST (parent dir must exist)")],
) -> dict:
    """Copy a file from device to host. `adb pull`."""
    _ensure_one_device()
    h = Path(host_path).expanduser()
    h.parent.mkdir(parents=True, exist_ok=True)
    r = _adb_run(["pull", device_path, str(h)], timeout=300)
    if r["returncode"] != 0:
        return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"]}
    return {
        "ok": True,
        "device": device_path,
        "host": str(h),
        "size": h.stat().st_size if h.exists() else None,
    }


# ============================================================
#                       ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print(f"android-gui MCP server starting")
    print(f"  adb       = {_ADB}")
    print(f"  host      = {host_platform.system()} {host_platform.release()}")
    try:
        serial = _ensure_one_device()
        print(f"  device    = {serial} (ok)")
    except Exception as e:
        print(f"  device    = NONE  ({e})")
        print(f"  WARNING: server will start but tools will fail until a device appears.")
    # Transport: streamable-http (FastMCP "http" alias). Migrated from
    # SSE for the same reason as macbox-gui / winpc-gui: long tool calls
    # broke SSE keep-alive and yielded -32602 forever after.
    # Endpoint: http://<host>:8768/mcp  (was /sse)
    print(f"  transport = http (streamable) on 0.0.0.0:8768/mcp")
    mcp.run(transport="http", host="0.0.0.0", port=8768)
