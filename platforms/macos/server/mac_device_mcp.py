"""macOS MCP Server (mac-device).

Single FastMCP server exposing macOS control: GUI (screenshot / mouse /
keyboard) + shell (zsh / processes / AppleScript) + filesystem (read /
write / list / search) for agent-driven testing and remote operation.

Mirrors the architecture of the Windows win-device server. Same tool
contract for cross-platform Universal Tool Set compliance, with macOS-
specific extensions (run_applescript, open_app).

Transport: streamable-http on 0.0.0.0:8767/mcp. macOS Application Firewall (or pf, if
enabled) + Tailscale ACL gate who can reach it.

In-use state model: advisory single-holder. acquire / release
let agents coordinate explicitly; get_status reports current state.
Idle timeout (10 min) auto-clears stale holders.

GUI permissions (one-time manual grant in System Settings):
  - Privacy & Security > Accessibility       -> Python.framework's Python.app
  - Privacy & Security > Screen Recording    -> Python.framework's Python.app
  - Privacy & Security > Automation          -> python3 controlling
                                                System Events / Finder
  Use the .app bundle inside the brew Python framework (NOT the venv's
  bin/python3 symlink -- macOS rejects symlinks and CLI binaries in
  these panes). setup-macos.sh prints the exact path on the host.
  Without these, click / type / take_screenshot / list_windows fail
  silently or with PermissionError.
"""

from __future__ import annotations

import functools
import io
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import psutil
import pyautogui
import pyperclip
from PIL import ImageGrab
from pydantic import Field

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
import _fsops, _proc, _search
from _device_state import DeviceStateRegistry

# Disable pyautogui's "mouse-to-corner = abort" failsafe (remote agents trip it accidentally).
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


mcp = FastMCP("mac-device")

_state_registry = DeviceStateRegistry()  # name matches android/ios servers
_SERIAL = "host"
_SHELL = _proc.ShellSpec(
    shells={
        "zsh": ["/bin/zsh", "-c"],
        "bash": ["/bin/bash", "-c"],
        "sh": ["/bin/sh", "-c"],
    },
    default_shell="zsh",
    shlex_posix=True,
)


# ============================================================
#                     IN-USE STATE TRACKING
# ============================================================

def with_touch(fn):
    """Decorator: every non-state tool calls _state_registry.touch() before its body so the
    holder's idle timer resets on real usage."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _state_registry.touch(_SERIAL)
        return fn(*args, **kwargs)

    return wrapper


@mcp.tool
def acquire(
    holder_name: Annotated[
        str,
        Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')"),
    ] = "anonymous",
) -> dict:
    """Claim exclusive use of this Mac test machine.

    Advisory: tools still work for everyone, but get_status will show
    your name as the active holder. Use as a polite signal in multi-agent
    setups so others know the box is busy.
    """
    return _state_registry.acquire(_SERIAL, holder_name)


@mcp.tool
def release(
    holder_name: Annotated[
        str,
        Field(description="Must match the holder_name used in acquire"),
    ] = "anonymous",
) -> dict:
    """Release the exclusive-use claim. Only the current holder can release."""
    return _state_registry.release(_SERIAL, holder_name)


@mcp.tool
def get_status() -> dict:
    """Show whether the Mac test machine is currently claimed and by whom."""
    return _state_registry.status(_SERIAL)


# ============================================================
#                      GUI / SCREEN
# ============================================================
# Note: Requires Screen Recording permission for the venv's python3
# (System Settings > Privacy & Security > Screen Recording).

@mcp.tool
@with_touch
def get_screen_size() -> dict:
    """Return the primary screen resolution (logical pixels)."""
    w, h = pyautogui.size()
    return {"width": w, "height": h}


@mcp.tool
@with_touch
def take_screenshot(
    region: Annotated[
        Optional[tuple[int, int, int, int]],
        Field(description="(left, top, right, bottom) in logical pixels; None = full screen"),
    ] = None,
) -> Image:
    """Capture the screen and return a PNG sized to LOGICAL pixels.

    On Retina, ImageGrab returns physical pixels (e.g. 2880x1800) while
    pyautogui clicks use logical pixels (e.g. 1440x900). We resize the
    grab to logical size so screenshot pixel coordinates can be passed
    directly to `click(x, y)` without scaling math.
    """
    img = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    if region is None:
        target = pyautogui.size()
    else:
        target = (region[2] - region[0], region[3] - region[1])
    if img.size != target:
        from PIL import Image as PILImage
        img = img.resize(target, PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")


# ============================================================
#                     MOUSE / KEYBOARD
# ============================================================
# Requires Accessibility permission for the venv's python3.

@mcp.tool
@with_touch
def tap(
    x: Annotated[int, Field(description="Screen x coordinate")],
    y: Annotated[int, Field(description="Screen y coordinate")],
    button: Annotated[str, Field(description="left / right / middle")] = "left",
    clicks: Annotated[int, Field(ge=1, le=3)] = 1,
) -> dict:
    """Click the mouse at screen coordinates."""
    pyautogui.click(x=x, y=y, clicks=clicks, button=button)
    return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}


@mcp.tool
@with_touch
def move_mouse(
    x: int,
    y: int,
    duration: Annotated[float, Field(description="Seconds to take; 0 = instant")] = 0.0,
) -> dict:
    """Move the mouse to a coordinate."""
    pyautogui.moveTo(x, y, duration=duration)
    return {"ok": True, "x": x, "y": y}


@mcp.tool
@with_touch
def type_text(
    text: Annotated[str, Field(description="ASCII text")],
    interval: Annotated[float, Field(description="Per-char delay in seconds")] = 0.02,
) -> dict:
    """Type ASCII text at the focused control. Use paste_text for non-ASCII."""
    pyautogui.typewrite(text, interval=interval)
    return {"ok": True, "len": len(text)}


@mcp.tool
@with_touch
def paste_text(
    text: Annotated[str, Field(description="Any text including CJK / Unicode")],
) -> dict:
    """Type via clipboard + Cmd+V (Unicode-safe)."""
    pyperclip.copy(text)
    # macOS uses Cmd not Ctrl for paste
    pyautogui.hotkey("command", "v")
    return {"ok": True, "len": len(text)}


@mcp.tool
@with_touch
def press_key(
    keys: Annotated[
        str,
        Field(description="Single key or combo, e.g. 'enter' / 'cmd+s' / 'cmd+space' / 'cmd+tab'"),
    ],
) -> dict:
    """Press a key or key combination. macOS modifiers: cmd, option, shift, ctrl, fn."""
    parts = [k.strip() for k in keys.split("+")]
    # Normalize cmd -> command (pyautogui)
    parts = ["command" if p == "cmd" else "option" if p == "alt" else p for p in parts]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return {"ok": True, "keys": keys}


# ============================================================
#                  PROCESS / APP MANAGEMENT
# ============================================================

@mcp.tool
@with_touch
def open_app(
    app: Annotated[str, Field(description="App name (e.g. 'Safari', 'Terminal') or full path")],
    args: Annotated[Optional[list[str]], Field(description="Files / URLs to open with the app")] = None,
) -> dict:
    """Launch a macOS application by name (uses 'open -a').

    Examples:
      open_app("Safari")
      open_app("Safari", args=["https://example.com"])
      open_app("Terminal")
    """
    cmd = ["open", "-a", app]
    if args:
        cmd.extend(args)
    p = subprocess.Popen(cmd)
    return {"pid": p.pid, "cmd": cmd}


@mcp.tool
@with_touch
def kill_process(pid: int) -> dict:
    """Kill a process by PID."""
    p = psutil.Process(pid)
    name = p.name()
    p.kill()
    return {"ok": True, "pid": pid, "name": name}


@mcp.tool
@with_touch
def list_processes(
    name_filter: Annotated[
        Optional[str],
        Field(description="Substring filter on process name; None = all"),
    ] = None,
) -> list[dict]:
    """Summary of running processes (pid / name / user / mem%)."""
    out: list[dict] = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_percent"]):
        try:
            info = p.info
            if name_filter is None or (info["name"] and name_filter.lower() in info["name"].lower()):
                out.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


# ============================================================
#                          SHELL
# ============================================================

# fastmcp/mcp 在 streamable-http transport 上有 task-cancel-vs-respond race
# (jlowin/fastmcp#823, #508): 任何 tool call 超过 ~30s 会导致整个 MCP session 崩，
# 后续所有请求报 "Session not found"。在 wrapper 层 clamp 到 25s 留 5s margin。
# 长任务请改用 start_process + read_process_output 轮询。
_FASTMCP_DEADLINE_SAFE_SECONDS = 25


def _run_with_clamp(cmd: list[str], requested_timeout: int) -> dict:
    """subprocess.run 包装：timeout clamp 到 fastmcp 安全死线，TimeoutExpired 优雅返回 partial output。"""
    effective = min(requested_timeout, _FASTMCP_DEADLINE_SAFE_SECONDS)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=effective, encoding="utf-8", errors="replace",
        )
        return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired as e:
        partial_out = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode("utf-8", "replace") if e.stdout else "")
        partial_err = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode("utf-8", "replace") if e.stderr else "")
        return {
            "returncode": -1, "stdout": partial_out, "stderr": partial_err,
            "timed_out": True, "timeout_seconds": effective,
            "hint": f"Command exceeded {effective}s safe cap. Use start_process + read_process_output for longer jobs.",
        }


@mcp.tool
@with_touch
def run_zsh(
    script: Annotated[str, Field(description="zsh script content")],
    timeout: Annotated[int, Field(ge=1, le=25, description=f"Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s. Use start_process for longer jobs.")] = 25,
) -> dict:
    """Execute a zsh script; return stdout / stderr / exit code. Max 25s — see start_process for longer jobs."""
    return _run_with_clamp(["/bin/zsh", "-c", script], requested_timeout=timeout)


@mcp.tool
@with_touch
def run_applescript(
    script: Annotated[str, Field(description="AppleScript content")],
    timeout: Annotated[int, Field(ge=1, le=25, description=f"Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s.")] = 25,
) -> dict:
    """Execute AppleScript via 'osascript'. Max 25s.

    Powerful for controlling other apps:
      tell application "Safari" to activate
      tell application "System Events" to keystroke "a" using {command down}

    Requires Automation permission (System Settings > Privacy & Security >
    Automation > python3 -> tick the controlled app).
    """
    return _run_with_clamp(["osascript", "-e", script], requested_timeout=timeout)


# ============================================================
#                LONG-RUNNING PROCESS SESSIONS
# ============================================================

@mcp.tool
@with_touch
def start_process(
    command: Annotated[str, Field(description="Command line to execute")],
    shell: Annotated[
        str,
        Field(description="zsh / bash / sh / direct (no shell, splits args by shlex)"),
    ] = "zsh",
) -> dict:
    """Start a long-running process. Returns pid; use read_process_output to read its output, force_terminate to kill."""
    return _proc.start_process(command, shell, shell_spec=_SHELL)


@mcp.tool
@with_touch
def read_process_output(
    pid: Annotated[int, Field(description="PID returned by start_process")],
    offset: Annotated[
        int,
        Field(description="Start line (0=from start, negative=tail N)"),
    ] = -200,
    length: Annotated[int, Field(description="Max lines to return", ge=1, le=5000)] = 200,
) -> dict:
    """Read accumulated stdout/stderr from a process started via start_process."""
    return _proc.read_process_output(pid, offset, length)


@mcp.tool
@with_touch
def interact_with_process(
    pid: Annotated[int, Field(description="PID returned by start_process")],
    input_text: Annotated[str, Field(description="Text to send to the process stdin (newline added automatically)")],
) -> dict:
    """Send a line of input to a running process's stdin."""
    return _proc.interact_with_process(pid, input_text)


@mcp.tool
@with_touch
def force_terminate(
    pid: Annotated[int, Field(description="PID returned by start_process")],
) -> dict:
    """Kill a process started by start_process and remove it from the session map."""
    return _proc.force_terminate(pid)


@mcp.tool
@with_touch
def list_sessions() -> list[dict]:
    """List all processes currently tracked in the session map."""
    return _proc.list_sessions()


# ============================================================
#                       FILE SYSTEM
# ============================================================

@mcp.tool
@with_touch
def read_file(
    path: Annotated[str, Field(description="Absolute path to the file")],
    offset: Annotated[
        int,
        Field(description="Start line (0=from start, negative=tail N)"),
    ] = 0,
    length: Annotated[int, Field(description="Max lines to return", ge=1, le=10000)] = 1000,
    encoding: Annotated[str, Field(description="Text encoding")] = "utf-8",
) -> dict:
    """Read a text file. Returns metadata + selected lines slice."""
    return _fsops.read_file(path, offset, length, encoding)


@mcp.tool
@with_touch
def write_file(
    path: Annotated[str, Field(description="Absolute path to the file")],
    content: Annotated[str, Field(description="Text content to write")],
    mode: Annotated[
        str,
        Field(description="rewrite (default) or append"),
    ] = "rewrite",
    encoding: Annotated[str, Field(description="Text encoding")] = "utf-8",
) -> dict:
    """Write or append text to a file. Creates parent directories if needed."""
    return _fsops.write_file(path, content, mode, encoding)


@mcp.tool
@with_touch
def edit_block(
    path: Annotated[str, Field(description="Absolute path to the file")],
    old_string: Annotated[str, Field(description="Exact text to find")],
    new_string: Annotated[str, Field(description="Text to replace it with")],
    replace_all: Annotated[bool, Field(description="Replace all occurrences (default: only first)")] = False,
    encoding: Annotated[str, Field(description="Text encoding")] = "utf-8",
) -> dict:
    """Find-and-replace inside a text file. Fails if old_string is not unique unless replace_all."""
    return _fsops.edit_block(path, old_string, new_string, replace_all, encoding)


@mcp.tool
@with_touch
def list_directory(
    path: Annotated[str, Field(description="Absolute directory path")],
    depth: Annotated[int, Field(description="Recursion depth (1 = direct children only)", ge=1, le=10)] = 1,
    include_hidden: Annotated[bool, Field(description="Include dotfiles")] = False,
) -> dict:
    """List entries in a directory."""
    return _fsops.list_directory(path, depth, include_hidden)


@mcp.tool
@with_touch
def create_directory(
    path: Annotated[str, Field(description="Absolute directory path")],
) -> dict:
    """Create a directory (mkdir -p semantics)."""
    return _fsops.create_directory(path)


@mcp.tool
@with_touch
def move_file(
    src: Annotated[str, Field(description="Absolute source path")],
    dst: Annotated[str, Field(description="Absolute destination path")],
) -> dict:
    """Move or rename a file or directory."""
    return _fsops.move_file(src, dst)


@mcp.tool
@with_touch
def get_file_info(
    path: Annotated[str, Field(description="Absolute path to file or directory")],
) -> dict:
    """Return stat-like metadata for a path."""
    return _fsops.get_file_info(path)


# ============================================================
#                  FILE-CONTENT SEARCH
# ============================================================

@mcp.tool
@with_touch
def start_search(
    path: Annotated[str, Field(description="Root directory to search")],
    pattern: Annotated[str, Field(description="Regex pattern (Python re syntax)")],
    file_glob: Annotated[str, Field(description="Filename glob, e.g. '*.py' or '*'")] = "*",
    case_sensitive: Annotated[bool, Field(description="Case-sensitive matching")] = False,
) -> dict:
    """Start a recursive file-content search. Returns search_id; poll with get_more_search_results."""
    return _search.start_search(path, pattern, file_glob, case_sensitive)


@mcp.tool
@with_touch
def get_more_search_results(
    search_id: Annotated[str, Field(description="Returned by start_search")],
    offset: Annotated[int, Field(description="Start match index (0-based)")] = 0,
    length: Annotated[int, Field(description="Max matches to return", ge=1, le=1000)] = 100,
) -> dict:
    """Fetch matches from a running or completed search."""
    return _search.get_more_search_results(search_id, offset, length)


@mcp.tool
@with_touch
def list_searches() -> list[dict]:
    """List all in-flight or recent searches."""
    return _search.list_searches()


@mcp.tool
@with_touch
def stop_search(
    search_id: Annotated[str, Field(description="Returned by start_search")],
) -> dict:
    """Cancel a running search."""
    return _search.stop_search(search_id)


# ============================================================
#                  SINGLE-DEVICE CORE TOOLS
# ============================================================

@mcp.tool
@with_touch
def list_devices() -> list[dict]:
    """Single-device platform: always one entry, the host machine itself."""
    st = _state_registry.status(_SERIAL)
    return [{"serial": _SERIAL, "device": _SERIAL, "model": socket.gethostname(),
             "status": "in_use" if st.get("in_use") else "available", "default": True}]


@mcp.tool
def set_default_device(device: Annotated[str, Field(description="ignored on single-device platforms")] = "host") -> dict:
    return {"default": _SERIAL, "note": "single-device platform; always targets the host"}


@mcp.tool
def get_default_device() -> dict:
    return {"default": _SERIAL}


@mcp.tool
@with_touch
def current_app() -> dict:
    """Frontmost app on the macOS host.

    Uses NSWorkspace (public AppKit API — no Automation/TCC permission, unlike the
    `osascript "System Events"` approach which times out headlessly).
    """
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return {"app": None, "error": "no frontmost application"}
        return {
            "app": app.localizedName(),
            "bundle_id": app.bundleIdentifier(),
            "pid": int(app.processIdentifier()),
        }
    except Exception as e:  # noqa: BLE001 — surface as a friendly dict, not a framework crash
        return {"app": None, "error": str(e)}


@mcp.tool
@with_touch
def swipe(
    x1: Annotated[int, Field(description="start x")],
    y1: Annotated[int, Field(description="start y")],
    x2: Annotated[int, Field(description="end x")],
    y2: Annotated[int, Field(description="end y")],
    duration_ms: Annotated[int, Field(description="drag duration in ms")] = 300,
) -> dict:
    """Desktop swipe = left-button click-drag from (x1,y1) to (x2,y2)."""
    pyautogui.moveTo(x1, y1)
    pyautogui.dragTo(x2, y2, duration=max(0.0, duration_ms / 1000.0), button="left")
    return {"ok": True, "from": [x1, y1], "to": [x2, y2], "duration_ms": duration_ms}


# ============================================================
#                  UI ELEMENT INTROSPECTION
# ============================================================
#
# Element-driven automation via macOS Accessibility (AX) API.  Lets agents
# find buttons / menus / text fields by role / title / label instead of
# guessing pixel coordinates from screenshots.
#
# Requires pyobjc-framework-ApplicationServices (declared in
# server/requirements.txt as of v0.6.0-alpha).

def _ax_app_for_pid(pid: int):
    """Return AXUIElementRef for the application with the given PID."""
    from ApplicationServices import AXUIElementCreateApplication  # type: ignore
    return AXUIElementCreateApplication(pid)


def _ax_pid_of_app(app_name: str) -> Optional[int]:
    """Find PID of running app by name (matches NSRunningApplication.localizedName).

    Returns None if not running.  Case-insensitive partial match.
    """
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and app_name.lower() in proc.info["name"].lower():
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _ax_copy_attr(elem, attr: str):
    """Safely fetch one AX attribute. Returns None if missing or error."""
    from ApplicationServices import AXUIElementCopyAttributeValue  # type: ignore
    try:
        err, value = AXUIElementCopyAttributeValue(elem, attr, None)
        if err != 0:
            return None
        return value
    except Exception:
        return None


def _ax_element_dict(elem, depth: int) -> dict:
    """Snapshot an AX element to a JSON-friendly dict.

    Includes role, title, label, value (string-only), enabled, plus the
    element's screen position+size so callers can click its center.
    """
    role = _ax_copy_attr(elem, "AXRole") or ""
    title = _ax_copy_attr(elem, "AXTitle") or ""
    label = _ax_copy_attr(elem, "AXDescription") or ""
    help_text = _ax_copy_attr(elem, "AXHelp") or ""
    enabled = _ax_copy_attr(elem, "AXEnabled")
    role_desc = _ax_copy_attr(elem, "AXRoleDescription") or ""
    raw_value = _ax_copy_attr(elem, "AXValue")
    value_str = raw_value if isinstance(raw_value, str) else None

    # Position and size are CGPoint / CGSize wrapped in AXValue.  Convert.
    pos = _ax_copy_attr(elem, "AXPosition")
    size = _ax_copy_attr(elem, "AXSize")
    pos_xy = None
    size_wh = None
    center = None
    try:
        # pyobjc's AXValueGetValue returns (ok, value_tuple) — the third arg
        # MUST be None.  We previously passed a CGPoint() instance treating it
        # as a C-style output pointer, which raised
        # `ValueError: 'valuePtr' should be None` silently inside the try block
        # and left position/size at None.
        from ApplicationServices import (  # type: ignore
            AXValueGetValue,
            kAXValueCGPointType,
            kAXValueCGSizeType,
        )
        if pos is not None:
            ok, p = AXValueGetValue(pos, kAXValueCGPointType, None)
            if ok:
                pos_xy = [int(p.x), int(p.y)]
        if size is not None:
            ok, s = AXValueGetValue(size, kAXValueCGSizeType, None)
            if ok:
                size_wh = [int(s.width), int(s.height)]
        if pos_xy and size_wh:
            center = [pos_xy[0] + size_wh[0] // 2, pos_xy[1] + size_wh[1] // 2]
    except Exception:
        pass

    return {
        "role": role,
        "role_description": role_desc,
        "title": title,
        "label": label,
        "help": help_text,
        "value": value_str,
        "enabled": bool(enabled) if enabled is not None else None,
        "position": pos_xy,
        "size": size_wh,
        "center": center,
        "depth": depth,
    }


def _ax_walk(elem, depth: int, max_depth: int, out: list):
    """Walk AX tree breadth-first, append element dicts to out (depth ≤ max_depth)."""
    if depth > max_depth:
        return
    out.append(_ax_element_dict(elem, depth))
    if depth == max_depth:
        return
    children = _ax_copy_attr(elem, "AXChildren") or []
    for child in children:
        _ax_walk(child, depth + 1, max_depth, out)


@mcp.tool
@with_touch
def list_ui_elements(
    app: Annotated[str, Field(description="App name (e.g. 'Safari', 'Calculator', 'Code'); case-insensitive substring match on process name")],
    max_depth: Annotated[int, Field(ge=1, le=15, description="Max tree depth from app root")] = 6,
) -> dict:
    """Walk the AX (accessibility) tree of a running app and return all elements.

    Each element carries role / title / label / position / size / center, so
    callers can find a button by title and click it without guessing pixels.

    Note: the target app must be running.  TCC permission required:
    System Settings → Privacy & Security → Accessibility → Terminal/Python
    (the wizard's permission primer registers this automatically in v0.6.0+).

    Some apps don't expose proper AX trees (Electron with a11y off, Java
    Swing without bridge, Flutter desktop). Fall back to take_screenshot +
    click for those.
    """
    pid = _ax_pid_of_app(app)
    if pid is None:
        return {"ok": False, "error": f"no running process matches {app!r}"}

    try:
        app_elem = _ax_app_for_pid(pid)
    except ImportError as e:
        return {"ok": False, "error": f"pyobjc-framework-ApplicationServices not installed: {e}"}

    elements: list[dict] = []
    _ax_walk(app_elem, 0, max_depth, elements)
    return {"ok": True, "app": app, "pid": pid, "count": len(elements), "elements": elements}


@mcp.tool
@with_touch
def dump_ui(
    max_depth: Annotated[
        Optional[int],
        Field(description="Max AX tree depth (1-15). Defaults to 6 if not specified.", ge=1, le=15),
    ] = None,
) -> dict:
    """Dump the AX (accessibility) tree for the current frontmost macOS application.

    Resolves the active app via NSWorkspace.sharedWorkspace().frontmostApplication()
    without requiring you to know the app name. Use list_ui_elements when you need
    to target a specific app by name substring.

    Note: max_depth is honored when provided; defaults to 6 (same as list_ui_elements default).
    """
    try:
        from AppKit import NSWorkspace  # type: ignore
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front_app is None:
            return {"ok": False, "error": "no frontmost application"}
        pid = int(front_app.processIdentifier())
        # Use localizedName, fall back to bundleIdentifier, fall back to
        # "pid:<pid>" — purely for the display field; resolution is PID-based.
        app_label = (
            front_app.localizedName()
            or front_app.bundleIdentifier()
            or f"pid:{pid}"
        )
    except ImportError as e:
        return {"ok": False, "error": f"AppKit unavailable: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"NSWorkspace unavailable: {e}"}

    # Resolve AX tree by PID directly — avoids the name→pid round-trip that
    # would fail when localizedName() is falsy and bundleIdentifier() doesn't
    # match any psutil process *name* (e.g. "com.apple.Safari").
    depth = max_depth if max_depth is not None else 6
    try:
        app_elem = _ax_app_for_pid(pid)
    except ImportError as e:
        return {"ok": False, "error": f"pyobjc-framework-ApplicationServices not installed: {e}"}

    elements: list[dict] = []
    _ax_walk(app_elem, 0, depth, elements)
    return {"ok": True, "app": app_label, "pid": pid, "count": len(elements), "elements": elements}


@mcp.tool
@with_touch
def terminate_app(
    target: Annotated[
        str,
        Field(
            description="App name or bundle identifier substring to match "
                        "(e.g. 'Safari', 'com.apple.safari'). "
                        "Short or generic substrings can over-match unintended processes; "
                        "prefer the full app name or bundle ID."
        ),
    ],
) -> dict:
    """Terminate all running processes matching the given app name or bundle identifier.

    Tries NSWorkspace bundle-ID matching first; falls back to psutil process-name
    substring match. Use kill_process(pid) for precise single-process termination by PID.
    Returns a summary of how many processes were terminated.
    """
    target_lower = target.lower()
    terminated: list[dict] = []
    errors: list[dict] = []

    # Attempt NSWorkspace bundle-ID lookup first (preferred, macOS-native).
    try:
        from AppKit import NSWorkspace  # type: ignore
        running_apps = NSWorkspace.sharedWorkspace().runningApplications()
        for app in running_apps:
            bundle_id = app.bundleIdentifier() or ""
            name = app.localizedName() or ""
            if target_lower in bundle_id.lower() or target_lower in name.lower():
                pid = int(app.processIdentifier())
                try:
                    p = psutil.Process(pid)
                    p.kill()
                    terminated.append({"pid": pid, "name": name, "bundle_id": bundle_id})
                except Exception as e:
                    errors.append({"pid": pid, "error": str(e)})
    except ImportError:
        # AppKit unavailable — fall back to psutil process-name match
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = p.info
                name = info.get("name") or ""
                exe = info.get("exe") or ""
                if target_lower in name.lower() or target_lower in exe.lower():
                    p.kill()
                    terminated.append({"pid": info["pid"], "name": name, "bundle_id": None})
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                errors.append({"pid": p.pid, "error": str(e)})
            except Exception as e:
                errors.append({"pid": getattr(p, "pid", None), "error": str(e)})

    return {
        "ok": True,
        "target": target,
        "terminated_count": len(terminated),
        "terminated": terminated,
        "errors": errors,
    }


@mcp.tool
@with_touch
def find_ui_element(
    app: Annotated[str, Field(description="App name (e.g. 'Safari')")],
    title: Annotated[Optional[str], Field(description="Substring-match Element.title")] = None,
    role: Annotated[Optional[str], Field(description="Exact-match AX role (e.g. 'AXButton', 'AXMenuItem')")] = None,
    label: Annotated[Optional[str], Field(description="Substring-match AXDescription")] = None,
    max_depth: Annotated[int, Field(ge=1, le=15)] = 8,
) -> dict:
    """Find AX elements matching all provided filters (AND logic).

    Example:
        find_ui_element(app="Calculator", title="9")
        find_ui_element(app="Safari", role="AXButton", title="Reload")
    """
    if not any([title, role, label]):
        return {"ok": False, "error": "at least one of title/role/label required"}

    dump = list_ui_elements(app=app, max_depth=max_depth)
    if not dump.get("ok"):
        return dump

    def matches(e: dict) -> bool:
        if title and title not in e["title"]:
            return False
        if role and e["role"] != role:
            return False
        if label and label not in e["label"]:
            return False
        return True

    matches_list = [e for e in dump["elements"] if matches(e)]
    return {"ok": True, "app": app, "count": len(matches_list), "elements": matches_list}


@mcp.tool
@with_touch
def click_ui_element(
    app: Annotated[str, Field(description="App name")],
    title: Annotated[Optional[str], Field()] = None,
    role: Annotated[Optional[str], Field()] = None,
    label: Annotated[Optional[str], Field()] = None,
    nth: Annotated[int, Field(ge=0, description="If multiple match, click the nth (0-indexed)")] = 0,
) -> dict:
    """Find an AX element by filter and click its center.

    The element-driven equivalent of click(x, y), but resilient to window
    layout changes since it looks up by AX attributes.

    Errors out if no element matches OR nth is out of range — agent sees a
    clear failure instead of silently clicking nothing.
    """
    found = find_ui_element(app=app, title=title, role=role, label=label)
    if not found.get("ok"):
        return found
    matches_list = found["elements"]
    if not matches_list:
        return {"ok": False, "error": "no element matched the filter"}
    if nth >= len(matches_list):
        return {"ok": False, "error": f"only {len(matches_list)} element(s) matched, requested nth={nth}"}

    el = matches_list[nth]
    if not el["center"]:
        return {"ok": False, "error": "matched element has no bounds — cannot click"}

    cx, cy = el["center"]
    pyautogui.click(cx, cy)
    return {"ok": True, "clicked_at": [cx, cy], "element": el, "total_matches": len(matches_list)}


# ============================================================

if __name__ == "__main__":
    # Line-buffer stdio so log redirection (`python server.py > log 2>&1` from
    # launchctl / manual launchers) flushes in real time instead of waiting
    # for server exit.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    # Bind 0.0.0.0; the macOS Application Firewall (off by default on most
    # setups) and Tailscale ACL gate access.
    #
    # Transport: streamable-http (FastMCP's "http" alias). Replaces the
    # legacy SSE transport in v0.3.0 because long tool calls (>60s,
    # take_screenshot under load, run_zsh installs) caused the SSE keep-
    # alive to time out at intermediate hops; the client kept the old
    # session_id, the server no longer knew it, and every subsequent call
    # returned -32602 until the user did /exit + reopen Claude Code.
    # streamable-http uses per-request streams instead of a long-lived
    # event channel, so a stale connection is just one bad request --
    # auto-reconnect on the next call.
    #
    # Endpoint: http://<host>:8767/mcp  (was /sse)
    mcp.run(transport="http", host="0.0.0.0", port=8767)
