"""macOS MCP Server (mac-device).

Single FastMCP server exposing macOS control: GUI (screenshot / mouse /
keyboard) + shell (zsh / processes / AppleScript) + filesystem (read /
write / list / search) for agent-driven testing and remote operation.

Mirrors the architecture of the Windows win-device server. Same tool
contract for cross-platform Universal Tool Set compliance, with macOS-
specific extensions (run_applescript, open_app).

Transport: streamable-http on 0.0.0.0:8767/mcp. macOS Application Firewall (or pf, if
enabled) + Tailscale ACL gate who can reach it.

In-use state model: advisory single-holder. acquire_mac / release_mac
let agents coordinate explicitly; get_mac_status reports current state.
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
import re
import shutil
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

import psutil
import pyautogui
import pyperclip
from PIL import ImageGrab
from pydantic import Field

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

# Disable pyautogui's "mouse-to-corner = abort" failsafe (remote agents trip it accidentally).
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


mcp = FastMCP("mac-device")


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
def acquire_mac(
    holder_name: Annotated[
        str,
        Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')"),
    ] = "anonymous",
) -> dict:
    """Claim exclusive use of this Mac test machine.

    Advisory: tools still work for everyone, but get_mac_status will show
    your name as the active holder. Use as a polite signal in multi-agent
    setups so others know the box is busy.
    """
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
def release_mac(
    holder_name: Annotated[
        str,
        Field(description="Must match the holder_name used in acquire_mac"),
    ] = "anonymous",
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
def get_mac_status() -> dict:
    """Show whether the Mac test machine is currently claimed and by whom."""
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
def click(
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

@mcp.tool
@with_touch
def run_zsh(
    script: Annotated[str, Field(description="zsh script content")],
    timeout: Annotated[int, Field(ge=1, le=600)] = 60,
) -> dict:
    """Execute a zsh script; return stdout / stderr / exit code."""
    r = subprocess.run(
        ["/bin/zsh", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


@mcp.tool
@with_touch
def run_applescript(
    script: Annotated[str, Field(description="AppleScript content")],
    timeout: Annotated[int, Field(ge=1, le=600)] = 30,
) -> dict:
    """Execute AppleScript via 'osascript'.

    Powerful for controlling other apps:
      tell application "Safari" to activate
      tell application "System Events" to keystroke "a" using {command down}

    Requires Automation permission (System Settings > Privacy & Security >
    Automation > python3 -> tick the controlled app).
    """
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


# ============================================================
#                LONG-RUNNING PROCESS SESSIONS
# ============================================================
_processes_lock = threading.Lock()
_processes: "OrderedDict[int, dict]" = OrderedDict()
_PROCESS_BUFFER_LINES = 5000


def _pump_output(pid: int, proc: subprocess.Popen) -> None:
    try:
        if proc.stdout is None:
            return
        for raw in proc.stdout:
            line = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
            line = line.rstrip("\r\n")
            with _processes_lock:
                slot = _processes.get(pid)
                if slot is None:
                    return
                slot["lines"].append(line)
                excess = len(slot["lines"]) - _PROCESS_BUFFER_LINES
                if excess > 0:
                    del slot["lines"][:excess]
    finally:
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        with _processes_lock:
            slot = _processes.get(pid)
            if slot is not None:
                slot["done"] = True
                slot["exit_code"] = proc.returncode


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
    if shell == "direct":
        import shlex
        argv = shlex.split(command)
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    else:
        shell_path = {"zsh": "/bin/zsh", "bash": "/bin/bash", "sh": "/bin/sh"}.get(shell, "/bin/zsh")
        proc = subprocess.Popen(
            [shell_path, "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    pid = proc.pid
    with _processes_lock:
        _processes[pid] = {
            "proc": proc,
            "started_at": _now(),
            "command": command,
            "shell": shell,
            "lines": [],
            "done": False,
            "exit_code": None,
        }
    threading.Thread(target=_pump_output, args=(pid, proc), daemon=True).start()
    return {"pid": pid, "command": command, "shell": shell}


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
    with _processes_lock:
        slot = _processes.get(pid)
        if slot is None:
            return {"error": f"pid {pid} not in session map"}
        all_lines = list(slot["lines"])
        done = slot["done"]
        exit_code = slot["exit_code"]
        total = len(all_lines)

    if offset < 0:
        start = max(0, total + offset)
    else:
        start = min(offset, total)
    end = min(start + length, total)
    return {
        "pid": pid,
        "total_lines": total,
        "from_line": start,
        "to_line": end,
        "lines": all_lines[start:end],
        "done": done,
        "exit_code": exit_code,
    }


@mcp.tool
@with_touch
def interact_with_process(
    pid: Annotated[int, Field(description="PID returned by start_process")],
    input_text: Annotated[str, Field(description="Text to send to the process stdin (newline added automatically)")],
) -> dict:
    """Send a line of input to a running process's stdin."""
    with _processes_lock:
        slot = _processes.get(pid)
    if slot is None:
        return {"error": f"pid {pid} not in session map"}
    proc: subprocess.Popen = slot["proc"]
    if proc.stdin is None or proc.stdin.closed:
        return {"error": "stdin not available"}
    try:
        proc.stdin.write(input_text + ("\n" if not input_text.endswith("\n") else ""))
        proc.stdin.flush()
        return {"ok": True, "pid": pid, "wrote": len(input_text)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool
@with_touch
def force_terminate(
    pid: Annotated[int, Field(description="PID returned by start_process")],
) -> dict:
    """Kill a process started by start_process and remove it from the session map."""
    with _processes_lock:
        slot = _processes.pop(pid, None)
    if slot is None:
        return {"error": f"pid {pid} not in session map"}
    proc: subprocess.Popen = slot["proc"]
    try:
        proc.kill()
        proc.wait(timeout=3)
    except Exception:
        pass
    return {"ok": True, "pid": pid, "exit_code": proc.returncode}


@mcp.tool
@with_touch
def list_sessions() -> list[dict]:
    """List all processes currently tracked in the session map."""
    out: list[dict] = []
    with _processes_lock:
        for pid, slot in _processes.items():
            out.append(
                {
                    "pid": pid,
                    "command": slot["command"],
                    "shell": slot["shell"],
                    "started_at": slot["started_at"].isoformat(),
                    "buffered_lines": len(slot["lines"]),
                    "done": slot["done"],
                    "exit_code": slot["exit_code"],
                }
            )
    return out


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
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"path not found: {path}"}
    if not p.is_file():
        return {"error": f"not a file: {path}"}
    size = p.stat().st_size
    try:
        with p.open("r", encoding=encoding, errors="replace") as f:
            all_lines = f.read().splitlines()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "size_bytes": size}

    total = len(all_lines)
    if offset < 0:
        start = max(0, total + offset)
    else:
        start = min(offset, total)
    end = min(start + length, total)
    return {
        "path": str(p),
        "size_bytes": size,
        "total_lines": total,
        "from_line": start,
        "to_line": end,
        "content": "\n".join(all_lines[start:end]),
    }


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
    if mode not in ("rewrite", "append"):
        return {"error": "mode must be 'rewrite' or 'append'"}
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with p.open("a" if mode == "append" else "w", encoding=encoding) as f:
            f.write(content)
        return {"ok": True, "path": str(p), "bytes_written": len(content.encode(encoding))}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


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
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"path not found: {path}"}
    try:
        text = p.read_text(encoding=encoding)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    count = text.count(old_string)
    if count == 0:
        return {"error": "old_string not found", "occurrences": 0}
    if count > 1 and not replace_all:
        return {"error": "old_string not unique; pass replace_all=True or extend with surrounding context", "occurrences": count}
    new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    p.write_text(new_text, encoding=encoding)
    return {"ok": True, "path": str(p), "replaced": count if replace_all else 1}


@mcp.tool
@with_touch
def list_directory(
    path: Annotated[str, Field(description="Absolute directory path")],
    depth: Annotated[int, Field(description="Recursion depth (1 = direct children only)", ge=1, le=10)] = 1,
    include_hidden: Annotated[bool, Field(description="Include dotfiles")] = False,
) -> dict:
    """List entries in a directory."""
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        return {"error": f"not a directory: {path}"}

    entries: list[dict] = []

    def walk(d: Path, current_depth: int) -> None:
        try:
            for child in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if not include_hidden and child.name.startswith("."):
                    continue
                try:
                    is_dir = child.is_dir()
                    entry: dict[str, Any] = {
                        "name": child.name,
                        "path": str(child),
                        "type": "dir" if is_dir else "file",
                    }
                    if not is_dir:
                        try:
                            entry["size"] = child.stat().st_size
                        except OSError:
                            entry["size"] = None
                    entries.append(entry)
                    if is_dir and current_depth < depth:
                        walk(child, current_depth + 1)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            return

    walk(p, 1)
    return {"path": str(p), "entries": entries, "count": len(entries)}


@mcp.tool
@with_touch
def create_directory(
    path: Annotated[str, Field(description="Absolute directory path")],
) -> dict:
    """Create a directory (mkdir -p semantics)."""
    p = Path(path).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool
@with_touch
def move_file(
    src: Annotated[str, Field(description="Absolute source path")],
    dst: Annotated[str, Field(description="Absolute destination path")],
) -> dict:
    """Move or rename a file or directory."""
    s = Path(src).expanduser()
    d = Path(dst).expanduser()
    if not s.exists():
        return {"error": f"src not found: {src}"}
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return {"ok": True, "src": str(s), "dst": str(d)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool
@with_touch
def get_file_info(
    path: Annotated[str, Field(description="Absolute path to file or directory")],
) -> dict:
    """Return stat-like metadata for a path."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"path not found: {path}"}
    try:
        st = p.stat()
        return {
            "path": str(p),
            "type": "dir" if p.is_dir() else "file",
            "size_bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "ctime": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
            "is_symlink": p.is_symlink(),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ============================================================
#                  FILE-CONTENT SEARCH
# ============================================================
_searches_lock = threading.Lock()
_searches: dict[str, dict] = {}
_search_id_counter = 0
_SEARCH_BUFFER_LIMIT = 5000


def _run_search(search_id: str, root: Path, regex: re.Pattern, file_glob: str) -> None:
    try:
        for f in root.rglob(file_glob):
            with _searches_lock:
                slot = _searches.get(search_id)
                if slot is None or slot["stop"]:
                    return
            if not f.is_file():
                continue
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    for ln, line in enumerate(fh, start=1):
                        if regex.search(line):
                            with _searches_lock:
                                slot = _searches.get(search_id)
                                if slot is None or slot["stop"]:
                                    return
                                if len(slot["matches"]) < _SEARCH_BUFFER_LIMIT:
                                    slot["matches"].append(
                                        {"file": str(f), "line": ln, "text": line.rstrip("\r\n")}
                                    )
                                else:
                                    slot["truncated"] = True
                                    return
            except (PermissionError, OSError, UnicodeDecodeError):
                continue
    finally:
        with _searches_lock:
            slot = _searches.get(search_id)
            if slot is not None:
                slot["done"] = True


@mcp.tool
@with_touch
def start_search(
    path: Annotated[str, Field(description="Root directory to search")],
    pattern: Annotated[str, Field(description="Regex pattern (Python re syntax)")],
    file_glob: Annotated[str, Field(description="Filename glob, e.g. '*.py' or '*'")] = "*",
    case_sensitive: Annotated[bool, Field(description="Case-sensitive matching")] = False,
) -> dict:
    """Start a recursive file-content search. Returns search_id; poll with get_more_search_results."""
    global _search_id_counter
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return {"error": f"not a directory: {path}"}
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"error": f"invalid regex: {e}"}

    with _searches_lock:
        _search_id_counter += 1
        search_id = f"s{_search_id_counter}"
        _searches[search_id] = {
            "started_at": _now(),
            "root": str(root),
            "pattern": pattern,
            "file_glob": file_glob,
            "case_sensitive": case_sensitive,
            "matches": [],
            "done": False,
            "stop": False,
            "truncated": False,
        }
    threading.Thread(target=_run_search, args=(search_id, root, regex, file_glob), daemon=True).start()
    return {"search_id": search_id, "started_at": _searches[search_id]["started_at"].isoformat()}


@mcp.tool
@with_touch
def get_more_search_results(
    search_id: Annotated[str, Field(description="Returned by start_search")],
    offset: Annotated[int, Field(description="Start match index (0-based)")] = 0,
    length: Annotated[int, Field(description="Max matches to return", ge=1, le=1000)] = 100,
) -> dict:
    """Fetch matches from a running or completed search."""
    with _searches_lock:
        slot = _searches.get(search_id)
        if slot is None:
            return {"error": f"search_id {search_id} not found"}
        all_matches = list(slot["matches"])
        done = slot["done"]
        truncated = slot["truncated"]

    total = len(all_matches)
    end = min(offset + length, total)
    return {
        "search_id": search_id,
        "total_matches": total,
        "from_index": offset,
        "to_index": end,
        "matches": all_matches[offset:end],
        "done": done,
        "truncated": truncated,
    }


@mcp.tool
@with_touch
def list_searches() -> list[dict]:
    """List all in-flight or recent searches."""
    out: list[dict] = []
    with _searches_lock:
        for sid, slot in _searches.items():
            out.append(
                {
                    "search_id": sid,
                    "root": slot["root"],
                    "pattern": slot["pattern"],
                    "started_at": slot["started_at"].isoformat(),
                    "matches": len(slot["matches"]),
                    "done": slot["done"],
                    "truncated": slot["truncated"],
                }
            )
    return out


@mcp.tool
@with_touch
def stop_search(
    search_id: Annotated[str, Field(description="Returned by start_search")],
) -> dict:
    """Cancel a running search."""
    with _searches_lock:
        slot = _searches.get(search_id)
        if slot is None:
            return {"error": f"search_id {search_id} not found"}
        slot["stop"] = True
    return {"ok": True, "search_id": search_id}


# ============================================================

if __name__ == "__main__":
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
