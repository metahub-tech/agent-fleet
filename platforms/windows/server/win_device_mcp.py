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
import re
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

from win_input import _ensure_dpi_awareness, _send_unicode

# 进程尽早设为 per-monitor DPI aware: 否则 DPI 缩放≠100% 机器上 take_screenshot(物理像素)与
# tap/get_screen_size(逻辑像素)坐标系错位, 视觉点击漂移(AgentHub #100 P1-A)。幂等、失败不阻断。
_ensure_dpi_awareness()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
import _fsops, _proc, _search
import _server_runtime
from _device_state import DeviceStateRegistry
from _manifest import load_manifest
from capabilities import (
    AgentBrowserCapability,
    CapabilityRegistry,
    CoreCapability,
    HumanBrowserCapability,
    HumanDomCapability,
    VisionCapability,
    current_host_os,
    resolve_enabled_capabilities,
)
from capabilities.human_dom._bridge import DomBridge, run_bridge_loopback
from capabilities.human_dom._portfile import resolve_bridge_port
from _server_runtime import parse_server_args

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
    """Return the primary screen resolution in PHYSICAL pixels.

    Process is per-monitor DPI-aware, so this matches take_screenshot's pixel
    space and tap(x,y) coordinates exactly — tap in the same space you read off
    the screenshot (AgentHub #100 P1-A: no more physical-vs-logical mismatch)."""
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
        # A top-level class read is safe on consoles (list_windows does the same on
        # every window, consoles included); only the deep recursive walk in
        # print_control_identifiers hangs — which is exactly what we skip below.
        try:
            cls = win.class_name()
        except Exception:
            cls = ""
        if _is_console_window(cls):
            return _console_skip_message(cls, target=f"window matching '{title_substring}'")
        return _dump_window_tree(win, max_depth)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# Console / terminal host windows whose UIA tree makes pywinauto's
# print_control_identifiers walk the (huge, often streaming) text buffer and hang.
# We refuse to dump these and point at screenshot / process-output tools instead.
_CONSOLE_WINDOW_CLASSES = frozenset(
    {
        "ConsoleWindowClass",             # classic conhost: cmd.exe, powershell.exe
        "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
        "PseudoConsoleWindow",
    }
)


def _is_console_window(class_name: str | None) -> bool:
    """True if a window class is a console/terminal host that hangs UIA dumps."""
    return (class_name or "") in _CONSOLE_WINDOW_CLASSES


def _console_skip_message(class_name: str, target: str = "foreground window") -> str:
    return (
        f"ERROR: {target} is a console/terminal ('{class_name}'); its UIA tree hangs "
        "pywinauto's control walk. Use take_screenshot to view it, or the process "
        "tools (start_process / read_process_output / run_shell) to read console text."
    )


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


import concurrent.futures as _cf

# Ordered identifying attributes for find_elements/tap_element query matching;
# earlier = higher priority (a Name hit ranks above a ControlType hit).
_WIN_MATCH_FIELDS = ("name", "automation_id", "control_type", "class_name")


def _match_query(query: str, fields: dict) -> tuple:
    """Case-insensitive match of `query` against the ordered identifying fields.
    Returns (matched, match_field, is_exact): the highest-priority field that
    matches wins, with an exact (==) match preferred over a substring one. Pure
    (no pywinauto) — unit-testable on any platform."""
    q = (query or "").strip().lower()
    if not q:
        return (False, "", False)
    best = None  # (priority_index, is_exact, field)
    for i, f in enumerate(_WIN_MATCH_FIELDS):
        v = (fields.get(f) or "").lower()
        if not v:
            continue
        if v == q:
            cand = (i, True, f)
        elif q in v:
            cand = (i, False, f)
        else:
            continue
        if best is None or (cand[1], -cand[0]) > (best[1], -best[0]):
            best = cand
    return (True, best[2], best[1]) if best else (False, "", False)


def _uia_descendants_with_timeout(win, control_type, timeout_s: int = 8):
    """Run pywinauto's `descendants()` under a hard timeout. UIA traversal can
    block for seconds (or hang) on complex windows and would otherwise wedge the
    whole MCP server; a worker thread + timeout keeps the tool responsive."""
    ex = _cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(
        (lambda: win.descendants(control_type=control_type)) if control_type else win.descendants
    )
    try:
        return fut.result(timeout=timeout_s)
    finally:
        # NOT a `with` block: its shutdown(wait=True) would block on the wedged
        # worker and defeat the timeout. Detach (wait=False) so a hung UIA call
        # dies in the background while the tool returns promptly.
        ex.shutdown(wait=False)


def _resolve_uia_window(window_title):
    """Return (win, error_dict): the target UIA window. Default = foreground
    window; refuse console windows (their UIA tree hangs the walk — same guard
    as dump_ui)."""
    import win32gui
    if window_title:
        win = Desktop(backend="uia").window(title_re=f".*{re.escape(window_title)}.*")
        win.wait("visible", timeout=3)
        try:
            cls = win.class_name()
        except Exception:
            cls = ""
        if _is_console_window(cls):
            return None, {"ok": False, "reason": "console_window",
                          "error": _console_skip_message(cls, target=f"window matching {window_title!r}")}
        return win, None
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    if not title:
        return None, {"ok": False, "error": "No foreground window detected"}
    cls = win32gui.GetClassName(hwnd)
    if _is_console_window(cls):
        return None, {"ok": False, "reason": "console_window", "error": _console_skip_message(cls)}
    win = Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")
    win.wait("visible", timeout=3)
    return win, None


def _win_find_elements(query, window_title, control_type, include_disabled, max_results):
    """Core UIA element search shared by find_elements + tap_element."""
    win, err = _resolve_uia_window(window_title)
    if err:
        return err
    try:
        descendants = _uia_descendants_with_timeout(win, control_type, timeout_s=8)
    except _cf.TimeoutError:
        return {"ok": False, "reason": "uia_timeout",
                "error": "UIA tree traversal timed out (8s); narrow with control_type or window_title"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sw, sh = pyautogui.size()
    matched = []
    for e in descendants:
        try:
            info = e.element_info
            fields = {
                "name": info.name or "",
                "automation_id": info.automation_id or "",
                "control_type": info.control_type or "",
                "class_name": info.class_name or "",
            }
            ok, field, exact = _match_query(query, fields)
            if not ok:
                continue
            enabled = bool(e.is_enabled())
            if not include_disabled and not enabled:
                continue
            r = e.rectangle()
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            matched.append({
                "name": fields["name"], "automation_id": fields["automation_id"],
                "control_type": fields["control_type"], "class_name": fields["class_name"],
                "rect": [r.left, r.top, r.right, r.bottom], "center": [cx, cy],
                "enabled": enabled, "visible": bool(e.is_visible()),
                "on_screen": 0 <= cx < sw and 0 <= cy < sh,
                "match_field": field, "exact": exact,
            })
        except Exception:
            continue
    # on-screen first (only those are clickable; avoids auto-picking off-screen
    # zero-geometry nodes like closed menu items), then exact, then field priority.
    matched.sort(key=lambda m: (0 if m["on_screen"] else 1, 0 if m["exact"] else 1, _WIN_MATCH_FIELDS.index(m["match_field"])))
    total = len(matched)
    return {"ok": True, "count": min(total, max_results), "total_matched": total,
            "truncated": total > max_results, "elements": matched[:max_results]}


@mcp.tool
@with_touch
def dump_ui(
    max_depth: Annotated[
        Optional[int],
        Field(description="UI tree max depth (1-10). Defaults to 4 if not specified.", ge=1, le=10),
    ] = None,
) -> dict:
    """Dump the UIA control tree for the current foreground window.

    Resolves the active window via win32gui.GetForegroundWindow() without
    requiring you to know the window title. Use inspect_window when you need
    to target a specific window by title substring.
    Note: max_depth is honored via pywinauto's print_control_identifiers(depth=).

    Returns {"ok": True, "window", "max_depth", "tree"} on success; on failure
    {"ok": False, "error", ...} — same structured contract as the other
    platforms' dump_ui (mac/android/ios), so agents can branch on `ok`.
    """
    import win32gui  # pywin32 (ships with pywinauto)
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return {"ok": False, "error": "no foreground window detected"}
        cls = win32gui.GetClassName(hwnd)
        if _is_console_window(cls):
            return {"ok": False, "reason": "console_window", "error": _console_skip_message(cls)}
        win = Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")
        win.wait("visible", timeout=3)
        tree = _dump_window_tree(win, max_depth)
        return {"ok": True, "window": title,
                "max_depth": max_depth if max_depth is not None else 4, "tree": tree}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@mcp.tool
@with_touch
def find_elements(
    query: Annotated[str, Field(description="Case-insensitive substring matched against an element's name / automation-id / control-type / class-name (highest-priority field wins; exact match ranks first). e.g. 'Save', 'Submit'")],
    window_title: Annotated[Optional[str], Field(description="Restrict to the window whose title contains this; default = current foreground window")] = None,
    control_type: Annotated[Optional[str], Field(description="Pre-filter by UIA control type (e.g. 'Button', 'Edit', 'MenuItem', 'CheckBox') to narrow + speed up the search")] = None,
    include_disabled: Annotated[bool, Field(description="Include disabled elements (default: only enabled)")] = False,
    max_results: Annotated[int, Field(ge=1, le=100, description="Cap on returned candidates")] = 20,
) -> dict:
    """Locate UI elements in a window's UIA tree by a single query string.

    Element-located alternative to guessing coordinates off a screenshot: finds
    LIVE elements by accessibility attributes (resilient to layout/scroll/size
    changes) and returns ranked candidates with center coords. Prefer this +
    tap_element over screenshot+tap for native UI. NOTE: a browser's web page
    content is NOT exposed via UIA — for web / no-UIA-tree apps, fall back to
    vision_locate / vision_tap (像素级定位, if the vision capability is enabled)
    rather than guessing coords off a screenshot.
    """
    return _win_find_elements(query, window_title, control_type, include_disabled, max_results)


@mcp.tool
@with_touch
def tap_element(
    query: Annotated[str, Field(description="Element query (see find_elements). The best-ranked match is clicked.")],
    window_title: Annotated[Optional[str], Field(description="Restrict to this window; default = foreground")] = None,
    control_type: Annotated[Optional[str], Field(description="Pre-filter by UIA control type")] = None,
    nth: Annotated[Optional[int], Field(ge=0, description="Click the nth candidate (0 = first/best-ranked). Omit for auto (single/exact → click; multiple ambiguous → returns candidates). Pass an explicit nth after find_elements to disambiguate.")] = None,
    button: Annotated[str, Field(description="left / right / middle")] = "left",
    include_disabled: Annotated[bool, Field(description="Allow clicking disabled elements")] = False,
) -> dict:
    """Find an element by query and click its current center (element-located click).

    Resilient to layout changes vs hardcoded tap(x,y) since it locates the element
    live. On 'not_found' refine the query (use dump_ui to see real attributes);
    on 'ambiguous' pass a more specific query or an nth from find_elements; for
    browser web / no-UIA-tree content fall back to vision_tap (if enabled).
    """
    res = _win_find_elements(query, window_title, control_type, include_disabled, max_results=20)
    if not res.get("ok"):
        return res
    els = res["elements"]
    if not els:
        return {"ok": False, "reason": "not_found", "error": f"no element matched query={query!r}", "total_matched": 0}
    if nth is not None:
        if nth >= len(els):
            return {"ok": False, "reason": "nth_out_of_range",
                    "error": f"only {len(els)} candidate(s), requested nth={nth}", "total_matched": res["total_matched"]}
        chosen = els[nth]
    elif len(els) == 1 or els[0]["exact"]:
        chosen = els[0]
    else:
        return {"ok": False, "reason": "ambiguous",
                "error": f"{len(els)} elements matched query={query!r}; refine the query or pass nth",
                "candidates": els[:10], "total_matched": res["total_matched"]}
    cx, cy = chosen["center"]
    pyautogui.click(x=cx, y=cy, button=button)
    resp = {"ok": True, "action_type": "coordinate_click", "clicked_at": [cx, cy],
            "element": chosen, "total_matched": res["total_matched"]}
    if not chosen["on_screen"]:
        resp["warning"] = "element_may_be_off_screen"
    return resp


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
    text: Annotated[str, Field(description="Text to type (Unicode-safe, IME-proof)")],
    interval: Annotated[float, Field(description="Per-char delay in seconds")] = 0.0,
) -> dict:
    """Type text at the focused control via KEYEVENTF_UNICODE (injects Unicode code
    points directly, bypassing keyboard layout AND IME).

    Root-fixes the Chinese-IME hijack where the old VK-based typewrite turned `/`
    into `、` (AgentHub #100 P2). Handles any Unicode incl. CJK; for very long/rich
    text paste_text (clipboard) is still preferable."""
    _send_unicode(text, interval=interval)
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
    target: Annotated[str, Field(description="Executable path or PATH-resolvable command")],
    args: Annotated[Optional[list[str]], Field(description="Command-line arguments")] = None,
) -> dict:
    """Launch a Windows application; return its PID."""
    cmd = [target, *(args or [])]
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
        Field(description="Process name (e.g. 'notepad.exe') or executable path substring to match. "
                          "Short or generic substrings can over-match unintended processes; prefer the full process name."),
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
def run_shell(
    script: Annotated[str, Field(description="PowerShell script content")],
    timeout: Annotated[int, Field(ge=1, le=25, description=f"Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s. Use start_process for longer jobs.")] = 25,
) -> dict:
    """Execute a shell script (PowerShell); return stdout / stderr / exit code. Max 25s — see start_process for longer jobs."""
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
#                  CAPABILITY MODULE FRAMEWORK
# ============================================================
# core tools (above) stay inline — registered the normal way (zero behavior
# change). The registry adds list_capabilities() and registers optional
# capability modules (browser, ...) when enabled in config. Static registration
# at import → the client defers tool schemas (design §1), no upfront token cost.
_PLATFORM_DIR = Path(__file__).resolve().parent.parent      # platforms/windows
_REPO_ROOT = _PLATFORM_DIR.parent.parent                    # repo root
try:
    _enabled_caps = resolve_enabled_capabilities(
        load_manifest(_PLATFORM_DIR / "platform.toml").capabilities, _REPO_ROOT
    )
except Exception as e:  # never let capability config crash server startup
    print(f"[capabilities] config load failed, defaulting to core only: "
          f"{type(e).__name__}: {e}", file=sys.stderr)
    _enabled_caps = ["core"]

# OS 原语 helpers 注入 vision(capability 不 import server, 破循环依赖)。
def _capture_logical_png() -> bytes:
    """全屏抓图 → PNG bytes(同 take_screenshot, 供 vision 注入)。"""
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _os_tap(x: int, y: int) -> None:
    pyautogui.click(x=x, y=y)


def _os_fill(s: str) -> None:
    """聚焦后填充: 全选 + 剪贴板粘贴(支持中文, 覆盖原内容)。win 用 Ctrl(非 Cmd)。"""
    pyautogui.hotkey("ctrl", "a")
    pyperclip.copy(s)
    pyautogui.hotkey("ctrl", "v")


# 桥端口在 server 启动时一次确定(随 --port 派生 / --dom-bridge-port 覆盖 / 持久值复用),
# 必须在 _cap_registry.setup() 之前算好——human_dom_status 工具在 register() 时就把
# bridge_port 捕获进闭包(_human_dom.py),晚于 setup 再改来不及了。所以在【模块导入期】
# 解析一次 args(取 --port/--dom-bridge-port);main() 复用同一份(serve(args=_server_args)
# + run_bridge_loopback(port=_bridge_port)),不二次 parse。
# 注:本模块也被 server 测试以 `import win_device_mcp` 形式导入(此时 sys.argv 是 pytest 的),
# 故 parse 失败(SystemExit/未知参数)退回纯默认端口,保证导入期 floor check 不被打断。
try:
    _server_args = parse_server_args(prog="agent-fleet-win", default_port=8766)
except SystemExit:
    _server_args = parse_server_args(prog="agent-fleet-win", default_port=8766, argv=[])
_bridge_port = resolve_bridge_port(_server_args.port, override=_server_args.dom_bridge_port)

_dom_bridge = DomBridge(token="")   # v1: 127.0.0.1-only, 暂无 WS token
_cap_registry = CapabilityRegistry(host_os=current_host_os())
_cap_registry.add(CoreCapability(skill="using-win"))
_cap_registry.add(AgentBrowserCapability())
_cap_registry.add(HumanBrowserCapability(bridge_port=_bridge_port))  # 起专用 profile 时 auto-bake human_dom 扩展副本
_cap_registry.add(VisionCapability(capture_fn=_capture_logical_png, tap_fn=_os_tap))
_cap_registry.add(HumanDomCapability(_dom_bridge, tap_fn=_os_tap, fill_fn=_os_fill, bridge_port=_bridge_port))
_cap_registry.setup(mcp, _enabled_caps)


# ============================================================

def main() -> None:
    """Console entry point.

    Line-buffer stdio first so log redirection (`python win_device_mcp.py > log
    2>&1` from launchers / Task Scheduler / a parent process such as AgentHub
    desktop) flushes in real time instead of waiting for server exit.

    Bind/port/auth come from --host / --port / --token (env fallbacks
    FLEET_HOST / FLEET_PORT / FLEET_AUTH_TOKEN), resolved in _server_runtime:

      - default host stays 0.0.0.0 (Windows Firewall scoped to the Tailscale IP
        range gates access); pass --host 127.0.0.1 for loopback-only.
      - default port 8766; a parent can pass a free port to dodge a busy one.
      - --token enables a shared-secret bearer gate on every request except
        GET /health (the liveness probe a parent uses before routing traffic).

    Transport: streamable-http (FastMCP's "http" alias). Migrated from SSE in
    v0.2.x; SSE long-lived event channels timed out at middleboxes during long
    tool calls (>60s) and every subsequent call hit -32602 with a stale
    session_id. streamable-http is per-request and auto-reconnects.

    Endpoint: http://<host>:<port>/mcp  (was /sse)
    """
    run_bridge_loopback(_dom_bridge, host="127.0.0.1", port=_bridge_port)
    print(f"[human_dom] bridge on 127.0.0.1:{_bridge_port}", file=sys.stderr)
    _server_runtime.serve(mcp, prog="agent-fleet-win", default_port=8766, args=_server_args)


if __name__ == "__main__":
    main()
