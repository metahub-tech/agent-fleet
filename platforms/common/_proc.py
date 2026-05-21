"""Shared process/session management module.

Extracted from mac_device_mcp.py and win_device_mcp.py.  The only behavioral
difference between the two platforms is how ``start_process`` builds ``argv``,
which is parameterized via :class:`ShellSpec`.

Per-platform ShellSpec values (for P1b wiring):

# macOS:   ShellSpec(shells={"zsh":["/bin/zsh","-c"],"bash":["/bin/bash","-c"],"sh":["/bin/sh","-c"]}, default_shell="zsh", shlex_posix=True)
# Windows: ShellSpec(shells={"powershell":["powershell.exe","-NoProfile","-NonInteractive","-Command"],"pwsh":["pwsh.exe","-NoProfile","-NonInteractive","-Command"],"cmd":["cmd.exe","/c"]}, default_shell="powershell", shlex_posix=False)
"""

import shlex
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone


# ============================================================
#              ShellSpec — platform shell configuration
# ============================================================

@dataclass
class ShellSpec:
    """Encapsulates per-platform shell invocation details.

    Attributes:
        shells: Mapping from shell name to the FULL argv prefix.  The command
            string is appended as the single last element when invoking a
            shell.  E.g. ``{"bash": ["/bin/bash", "-c"]}`` means the argv for
            ``echo hello`` will be ``["/bin/bash", "-c", "echo hello"]``.
        default_shell: The shell name chosen when the caller does not specify
            an explicit shell name (or the name resolves to the platform
            default).
        shlex_posix: Passed to ``shlex.split`` in direct (no-shell) mode.
            ``True`` for POSIX platforms (macOS, Linux), ``False`` for Windows.
    """
    shells: dict[str, list[str]]
    default_shell: str
    shlex_posix: bool


# ============================================================
#              Module state
# ============================================================

_processes_lock = threading.Lock()
_processes: "OrderedDict[int, dict]" = OrderedDict()
_PROCESS_BUFFER_LINES = 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#              Internal helpers
# ============================================================

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


# ============================================================
#              Public API
# ============================================================

def start_process(
    command: str,
    shell: str = "direct",
    shell_spec: "ShellSpec | None" = None,
) -> dict:
    """Start a long-running process.

    Returns ``{"pid": int, "command": str, "shell": str}``.  Use
    :func:`read_process_output` to read accumulated output and
    :func:`force_terminate` to kill the process.

    Args:
        command:    Command line to execute.
        shell:      Shell name from ``shell_spec.shells``, ``"direct"`` to
                    skip shell wrapping and split ``command`` directly via
                    ``shlex.split``, or any other value treated as a shell name.
        shell_spec: Platform-specific :class:`ShellSpec`.  Required (must not
                    be ``None``) to determine how to build ``argv``.
    """
    if shell_spec is None:
        raise ValueError("shell_spec must be provided")

    if shell == "direct":
        argv = shlex.split(command, posix=shell_spec.shlex_posix)
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
        shell_name = shell if shell in shell_spec.shells else shell_spec.default_shell
        argv = shell_spec.shells[shell_name] + [command]
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


def read_process_output(
    pid: int,
    offset: int = -200,
    length: int = 200,
) -> dict:
    """Read accumulated stdout/stderr from a process started via :func:`start_process`.

    Args:
        pid:    PID returned by :func:`start_process`.
        offset: Start line.  ``0`` = from start; negative = tail N lines.
        length: Maximum number of lines to return (1–5000).
    """
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


def interact_with_process(
    pid: int,
    input_text: str,
) -> dict:
    """Send a line of input to a running process's stdin.

    Args:
        pid:        PID returned by :func:`start_process`.
        input_text: Text to send (a newline is appended automatically if not
                    already present).
    """
    with _processes_lock:
        slot = _processes.get(pid)
    if slot is None:
        return {"error": f"pid {pid} not in session map"}
    proc: subprocess.Popen = slot["proc"]
    # Writing stdin of an exited child raises OSError [Errno 22] on Windows
    # and BrokenPipeError on macOS/Linux. Python's file-object .closed flag
    # doesn't reflect the kernel PIPE handle being released. poll() is the
    # authoritative aliveness check, cross-platform.
    if proc.poll() is not None:
        return {
            "error": f"process pid {pid} already exited (exit_code={proc.returncode}); cannot send input"
        }
    if proc.stdin is None or proc.stdin.closed:
        return {"error": "stdin not available"}
    try:
        proc.stdin.write(input_text + ("\n" if not input_text.endswith("\n") else ""))
        proc.stdin.flush()
        return {"ok": True, "pid": pid, "wrote": len(input_text)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def force_terminate(
    pid: int,
) -> dict:
    """Kill a process started by :func:`start_process` and remove it from the session map.

    Args:
        pid: PID returned by :func:`start_process`.
    """
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
