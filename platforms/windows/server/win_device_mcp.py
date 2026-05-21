"""Windows MCP Server (win-device).

Single FastMCP server exposing all Windows control: GUI (screenshot / mouse /
keyboard / windows) + shell (PowerShell / processes) + filesystem (read /
write / list / search) for agent-driven testing and remote operation.

This file used to be the GUI-only half; the shell side was a separate
mcp-proxy + desktop-commander chain on port 8765. That stack hit several
single-client / npm / IPv6 issues, so we consolidated into one FastMCP
server (multi-client native, all-in-one venv).

Transport: streamable-http on 0.0.0.0:8766/mcp. Windows Firewall + Tailscale ACL gate
who can reach it.

In-use state model: advisory single-holder. acquire / release
let agents coordinate explicitly; get_status reports current state.
Idle timeout (10 min) auto-clears stale holders. Foundation for future
multi-agent enforcement.
"""

from __future__ import annotations

import contextlib
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

from pywinauto import Desktop

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
import _fsops, _proc, _search
from _device_state import DeviceStateRegistry

# Disable pyautogui's "mouse-to-corner = abort" failsafe (remote agents trip it accidentally).
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


mcp = FastMCP("win-device")

_state_registry = DeviceStateRegistry()  # name matches android/ios servers
_SERIAL = "host"
_SHELL = _proc.ShellSpec(
    shells={
        "powershell": ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"],
        "pwsh": ["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command"],
        "cmd": ["cmd.exe", "/c"],
    },
    default_shell="powershell",
    shlex_posix=False,
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
    """Claim exclusive use of this Windows test machine.

    Advisory: tools still work for everyone, but get_status will show
    your name as the active holder. Use this as a polite signal in
    multi-agent setups so others know the box is busy.
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
    """Show whether the Windows test machine is currently claimed and by whom."""
    return _state_registry.status(_SERIAL)


# ============================================================
#                      GUI / SCREEN
# ============================================================

@mcp.tool
@with_touch
def get_screen_size() -> dict:
    """Return the primary screen resolution (logical pixels, no DPI compensation)."""
    w, h = pyautogui.size()
    return {"width": w, "height": h}


@mcp.tool
@with_touch
def take_screenshot(
    region: Annotated[
        Optional[tuple[int, int, int, int]],
        Field(description="(left, top, right, bottom); None = full screen"),
    ] = None,
) -> Image:
    """Capture the screen and return a PNG."""
    img = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")


@mcp.tool
@with_touch
def list_windows() -> list[dict]:
    """List all visible top-level windows (title, class, rect, pid)."""
    out: list[dict] = []
    for w in Desktop(backend="uia").windows():
        try:
            if w.is_visible() and w.window_text():
                r = w.rectangle()
                out.append(
                    {
                        "title": w.window_text(),
                        "class_name": w.class_name(),
                        "left": r.left,
                        "top": r.top,
                        "right": r.right,
                        "bottom": r.bottom,
                        "pid": w.process_id(),
                    }
                )
        except Exception:
            continue
    return out


@mcp.tool
@with_touch
def inspect_window(
    title_substring: Annotated[str, Field(description="Window whose title contains this substring")],
    max_depth: Annotated[int, Field(description="UI tree max depth", ge=1, le=10)] = 4,
) -> str:
    """Print the UIA control tree for a window, useful for finding buttons / inputs."""
    try:
        win = Desktop(backend="uia").window(title_re=f".*{title_substring}.*")
        win.wait("visible", timeout=3)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            win.print_control_identifiers(depth=max_depth)
        return buf.getvalue()
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def _dump_window_tree(win, max_depth: int | None) -> str:
    """Print the UIA control tree for a pywinauto window wrapper.

    Shared helper used by both inspect_window and dump_ui.
    max_depth is passed to print_control_identifiers if provided;
    pywinauto's depth parameter is an int (no None support), so we
    default to 4 when not specified.
    """
    buf = io.StringIO()
    depth = max_depth if max_depth is not None else 4
    with contextlib.redirect_stdout(buf):
        win.print_control_identifiers(depth=depth)
    return buf.getvalue()


@mcp.tool
@with_touch
def dump_ui(
    max_depth: Annotated[
        Optional[int],
        Field(description="UI tree max depth (1-10). Defaults to 4 if not specified.", ge=1, le=10),
    ] = None,
) -> str:
    """Dump the UIA control tree for the current foreground window.

    Resolves the active window via win32gui.GetForegroundWindow() without
    requiring you to know the window title. Use inspect_window when you need
    to target a specific window by title substring.
    Note: max_depth is honored via pywinauto's print_control_identifiers(depth=).
    """
    import win32gui  # pywin32 (ships with pywinauto)
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return "ERROR: No foreground window detected"
        win = Desktop(backend="uia").window(title_re=f".*{title}.*")
        win.wait("visible", timeout=3)
        return _dump_window_tree(win, max_depth)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool
@with_touch
def focus_window(
    title_substring: Annotated[str, Field(description="Window whose title contains this substring")],
) -> dict:
    """Bring a window to the foreground."""
    try:
        win = Desktop(backend="uia").window(title_re=f".*{title_substring}.*")
        win.set_focus()
        return {"ok": True, "title": win.window_text()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================
#                     MOUSE / KEYBOARD
# ============================================================

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
    """Type via clipboard + Ctrl+V (Unicode-safe)."""
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    return {"ok": True, "len": len(text)}


@mcp.tool
@with_touch
def press_key(
    keys: Annotated[
        str,
        Field(description="Single key or combo, e.g. 'enter' / 'ctrl+s' / 'alt+f4' / 'win+d'"),
    ],
) -> dict:
    """Press a key or key combination."""
    parts = [k.strip() for k in keys.split("+")]
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
def launch_app(
    path: Annotated[str, Field(description="Executable path or PATH-resolvable command")],
    args: Annotated[Optional[list[str]], Field(description="Command-line arguments")] = None,
) -> dict:
    """Launch a Windows application; return its PID."""
    cmd = [path, *(args or [])]
    p = subprocess.Popen(cmd, shell=False)
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
def terminate_app(
    target: Annotated[
        str,
        Field(description="Process name (e.g. 'notepad.exe') or executable path substring to match"),
    ],
) -> dict:
    """Terminate all processes matching the given name or executable path.

    Enumerates running processes via psutil and kills every match. Use
    kill_process(pid) for precise single-process termination by PID.
    Returns a summary of how many processes were terminated.
    """
    target_lower = target.lower()
    terminated: list[dict] = []
    errors: list[dict] = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = p.info
            name = info.get("name") or ""
            exe = info.get("exe") or ""
            if target_lower in name.lower() or target_lower in exe.lower():
                p.kill()
                terminated.append({"pid": info["pid"], "name": name, "exe": exe})
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
def run_powershell(
    script: Annotated[str, Field(description="PowerShell script content")],
    timeout: Annotated[int, Field(ge=1, le=25, description=f"Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s. Use start_process for longer jobs.")] = 25,
) -> dict:
    """Execute a PowerShell script; return stdout / stderr / exit code. Max 25s — see start_process for longer jobs."""
    return _run_with_clamp(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        requested_timeout=timeout,
    )


# ============================================================
#                LONG-RUNNING PROCESS SESSIONS
# ============================================================

@mcp.tool
@with_touch
def start_process(
    command: Annotated[str, Field(description="Command line to execute")],
    shell: Annotated[
        str,
        Field(description="powershell / cmd / pwsh / direct (no shell)"),
    ] = "powershell",
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
    """Send a line of input to a running process's stdin (e.g. interactive REPL, prompt response)."""
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
    """Foreground app on the Windows host."""
    import win32gui, win32process  # pywin32 (ships with pywinauto)
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        name = psutil.Process(pid).name()
    except Exception:
        name = None
    return {"app": name, "title": title, "pid": pid}


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

if __name__ == "__main__":
    # Line-buffer stdio so log redirection (`python server.py > log 2>&1` from
    # launchers / Task Scheduler) flushes in real time instead of waiting for
    # server exit.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    # Bind 0.0.0.0; Windows Firewall scoped to Tailscale IP range gates access.
    #
    # Transport: streamable-http (FastMCP's "http" alias). Migrated from
    # SSE in v0.2.x; SSE long-lived event channels timed out at middle-
    # boxes during long tool calls (>60s) and every subsequent call hit
    # -32602 with a stale session_id. streamable-http is per-request and
    # auto-reconnects.
    #
    # Endpoint: http://<host>:8766/mcp  (was /sse)
    mcp.run(transport="http", host="0.0.0.0", port=8766)
