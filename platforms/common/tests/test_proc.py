"""Tests for _proc.py — process/session management.

Run from platforms/common/:
    python3 -m pytest tests/test_proc.py -q
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _proc

# Linux ShellSpec used for all tests on this platform
LINUX_SHELL = _proc.ShellSpec(
    shells={"bash": ["/bin/bash", "-c"], "sh": ["/bin/sh", "-c"]},
    default_shell="bash",
    shlex_posix=True,
)


def _poll_for(pid: int, needle: str, timeout: float = 5.0) -> list[str]:
    """Poll read_process_output until *needle* appears in output or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _proc.read_process_output(pid, offset=0, length=5000)
        lines = result.get("lines", [])
        if any(needle in line for line in lines):
            return lines
        time.sleep(0.05)
    result = _proc.read_process_output(pid, offset=0, length=5000)
    return result.get("lines", [])


# ---------------------------------------------------------------------------
# Test 1: shell mode — echo hello via bash
# ---------------------------------------------------------------------------
def test_shell_mode_echo():
    result = _proc.start_process("echo hello", shell="bash", shell_spec=LINUX_SHELL)
    pid = result["pid"]
    assert pid > 0
    assert result["command"] == "echo hello"
    assert result["shell"] == "bash"

    try:
        lines = _poll_for(pid, "hello", timeout=5.0)
        assert any("hello" in line for line in lines), f"Expected 'hello' in output, got: {lines}"

        # list_sessions should contain this pid
        sessions = _proc.list_sessions()
        pids = [s["pid"] for s in sessions]
        assert pid in pids, f"pid {pid} not in list_sessions: {sessions}"
    finally:
        _proc.force_terminate(pid)


# ---------------------------------------------------------------------------
# Test 2: direct mode — /bin/echo hi
# ---------------------------------------------------------------------------
def test_direct_mode_echo():
    result = _proc.start_process("/bin/echo hi", shell="direct", shell_spec=LINUX_SHELL)
    pid = result["pid"]
    assert pid > 0
    assert result["shell"] == "direct"

    try:
        lines = _poll_for(pid, "hi", timeout=5.0)
        assert any("hi" in line for line in lines), f"Expected 'hi' in output, got: {lines}"
    finally:
        _proc.force_terminate(pid)


# ---------------------------------------------------------------------------
# Test 3: interact_with_process — cat echoes stdin back
# ---------------------------------------------------------------------------
def test_interact_with_process():
    result = _proc.start_process("cat", shell="bash", shell_spec=LINUX_SHELL)
    pid = result["pid"]
    assert pid > 0

    try:
        # Wait briefly to ensure process is ready
        time.sleep(0.1)

        resp = _proc.interact_with_process(pid, "ping")
        assert resp.get("ok") is True, f"interact_with_process failed: {resp}"

        lines = _poll_for(pid, "ping", timeout=5.0)
        assert any("ping" in line for line in lines), f"Expected 'ping' echoed back, got: {lines}"
    finally:
        _proc.force_terminate(pid)


# ---------------------------------------------------------------------------
# Test 4: force_terminate removes pid from sessions
# ---------------------------------------------------------------------------
def test_force_terminate_removes_session():
    result = _proc.start_process("sleep 60", shell="bash", shell_spec=LINUX_SHELL)
    pid = result["pid"]
    assert pid > 0

    # Verify it's tracked
    sessions = _proc.list_sessions()
    assert any(s["pid"] == pid for s in sessions)

    term_result = _proc.force_terminate(pid)
    assert term_result.get("ok") is True
    assert term_result["pid"] == pid

    # Should no longer be tracked
    sessions_after = _proc.list_sessions()
    assert not any(s["pid"] == pid for s in sessions_after)


# ---------------------------------------------------------------------------
# Test 5: force_terminate on unknown pid returns error
# ---------------------------------------------------------------------------
def test_force_terminate_unknown_pid():
    result = _proc.force_terminate(99999999)
    assert "error" in result


# ---------------------------------------------------------------------------
# Test 6: read_process_output on unknown pid returns error
# ---------------------------------------------------------------------------
def test_read_output_unknown_pid():
    result = _proc.read_process_output(99999999)
    assert "error" in result


# ---------------------------------------------------------------------------
# Test 7: list_sessions structure
# ---------------------------------------------------------------------------
def test_list_sessions_structure():
    result = _proc.start_process("sleep 60", shell="bash", shell_spec=LINUX_SHELL)
    pid = result["pid"]
    try:
        sessions = _proc.list_sessions()
        match = next((s for s in sessions if s["pid"] == pid), None)
        assert match is not None
        for key in ("pid", "command", "shell", "started_at", "buffered_lines", "done", "exit_code"):
            assert key in match, f"Missing key '{key}' in session: {match}"
        assert match["command"] == "sleep 60"
        assert match["shell"] == "bash"
        assert isinstance(match["started_at"], str)
    finally:
        _proc.force_terminate(pid)


# ---------------------------------------------------------------------------
# Test 8: default_shell used when shell arg matches default
# ---------------------------------------------------------------------------
def test_default_shell_via_spec():
    # Use default_shell by passing shell=LINUX_SHELL.default_shell
    result = _proc.start_process(
        "echo default_shell_test",
        shell=LINUX_SHELL.default_shell,
        shell_spec=LINUX_SHELL,
    )
    pid = result["pid"]
    try:
        lines = _poll_for(pid, "default_shell_test", timeout=5.0)
        assert any("default_shell_test" in line for line in lines)
    finally:
        _proc.force_terminate(pid)


# ---------------------------------------------------------------------------
# Test 9: sh shell also works (tests multiple shells in spec)
# ---------------------------------------------------------------------------
def test_sh_shell():
    result = _proc.start_process("echo from_sh", shell="sh", shell_spec=LINUX_SHELL)
    pid = result["pid"]
    try:
        lines = _poll_for(pid, "from_sh", timeout=5.0)
        assert any("from_sh" in line for line in lines), f"Expected 'from_sh', got: {lines}"
    finally:
        _proc.force_terminate(pid)
