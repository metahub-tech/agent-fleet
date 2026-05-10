"""Windows MCP Server (winpc-gui).

Single FastMCP server exposing all Windows control: GUI (screenshot / mouse /
keyboard / windows) + shell (PowerShell / processes) + filesystem (read /
write / list / search) for agent-driven testing and remote operation.

This file used to be the GUI-only half; the shell side was a separate
mcp-proxy + desktop-commander chain on port 8765. That stack hit several
single-client / npm / IPv6 issues, so we consolidated into one FastMCP
server (multi-client native, all-in-one venv).

Transport: streamable-http on 0.0.0.0:8766/mcp. Windows Firewall + Tailscale ACL gate
who can reach it.

In-use state model: advisory single-holder. acquire_winpc / release_winpc
let agents coordinate explicitly; get_winpc_status reports current state.
Idle timeout (10 min) auto-clears stale holders. Foundation for future
multi-agent enforcement.
"""

from __future__ import annotations

import contextlib
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

from pywinauto import Desktop

# Disable pyautogui's "mouse-to-corner = abort" failsafe (remote agents trip it accidentally).
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


mcp = FastMCP("winpc-gui")


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
    """Caller must hold _state_lock. Drops holder if idle past timeout."""
    global _holder
    if _holder is not None and (_now() - _holder.last_used_at) > _IDLE_TIMEOUT:
        _holder = None


def _touch() -> None:
    """Mark current holder (if any) as recently active. No-op if free."""
    with _state_lock:
        _check_idle_release_locked()
        if _holder is not None:
            _holder.last_used_at = _now()


def with_touch(fn):
    """Decorator: every non-state tool calls _touch() before its body so the
    holder's idle timer resets on real usage."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _touch()
        return fn(*args, **kwargs)

    return wrapper


@mcp.tool
def acquire_winpc(
    holder_name: Annotated[
        str,
        Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')"),
    ] = "anonymous",
) -> dict:
    """Claim exclusive use of this Windows test machine.

    Advisory: tools still work for everyone, but get_winpc_status will show
    your name as the active holder. Use this as a polite signal in
    multi-agent setups so others know the box is busy.
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
def release_winpc(
    holder_name: Annotated[
        str,
        Field(description="Must match the holder_name used in acquire_winpc"),
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
def get_winpc_status() -> dict:
    """Show whether the Windows test machine is currently claimed and by whom."""
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
def run_powershell(
    script: Annotated[str, Field(description="PowerShell script content")],
    timeout: Annotated[int, Field(ge=1, le=600)] = 60,
) -> dict:
    """Execute a PowerShell script; return stdout / stderr / exit code."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
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
# Map pid -> {proc, started_at, command, lines, done, exit_code, lock}
_processes_lock = threading.Lock()
_processes: "OrderedDict[int, dict]" = OrderedDict()
_PROCESS_BUFFER_LINES = 5000


def _pump_output(pid: int, proc: subprocess.Popen) -> None:
    """Background thread: read child stdout line-by-line into the per-pid buffer."""
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
                # Cap buffer
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
        Field(description="powershell / cmd / pwsh / direct (no shell)"),
    ] = "powershell",
) -> dict:
    """Start a long-running process. Returns pid; use read_process_output to read its output, force_terminate to kill."""
    if shell == "direct":
        # Split simple command line
        import shlex
        argv = shlex.split(command, posix=False)
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
        shell_exe = {"powershell": "powershell.exe", "pwsh": "pwsh.exe", "cmd": "cmd.exe"}.get(shell, "powershell.exe")
        if shell_exe == "cmd.exe":
            argv = [shell_exe, "/c", command]
        else:
            argv = [shell_exe, "-NoProfile", "-NonInteractive", "-Command", command]
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
    """Send a line of input to a running process's stdin (e.g. interactive REPL, prompt response)."""
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
    p = Path(path)
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
    p = Path(path)
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
    p = Path(path)
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
    p = Path(path)
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
    p = Path(path)
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
    s = Path(src)
    d = Path(dst)
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
    p = Path(path)
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
# Each search runs in a background thread, accumulates matches.
_searches_lock = threading.Lock()
_searches: dict[str, dict] = {}
_search_id_counter = 0
_SEARCH_BUFFER_LIMIT = 5000  # max matches kept in memory


def _run_search(search_id: str, root: Path, regex: re.Pattern, file_glob: str) -> None:
    """Background grep walker; populates the matches list."""
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
    root = Path(path)
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
