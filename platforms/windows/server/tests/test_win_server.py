"""In-venv smoke tests for the wired Windows server. Runs ONLY on Windows (the
server imports pyautogui/pywinauto). Importing the module is itself the floor check
(deps + the `common` shared modules resolve); the rest exercise the delegation +
single-device tools without GUI side effects (no swipe/current_app here — those move
the cursor / query the desktop and are covered by the MCP smoke test)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # server dir
import win_device_mcp as srv


def _fn(tool):
    """@mcp.tool may wrap the function as a Tool; the original is at .fn."""
    return getattr(tool, "fn", tool)


def _content(r):
    return r if isinstance(r, str) else r["content"]


def test_module_imports():
    assert srv is not None  # floor: wired server imports on real Windows


def test_list_devices_single_host():
    devs = _fn(srv.list_devices)()
    assert isinstance(devs, list) and len(devs) == 1
    assert devs[0]["serial"] == "host"
    assert devs[0]["default"] is True


def test_default_device_helpers():
    assert _fn(srv.get_default_device)()["default"] == "host"
    assert _fn(srv.set_default_device)("whatever")["default"] == "host"


def test_holder_roundtrip():
    assert _fn(srv.get_winpc_status)()["in_use"] is False
    a = _fn(srv.acquire_winpc)("tester")
    assert a.get("acquired") is True
    s1 = _fn(srv.get_winpc_status)()
    assert s1["in_use"] is True
    assert s1["holder"] == "tester"
    assert "auto_release_in_seconds" in s1
    assert _fn(srv.release_winpc)("tester").get("released") is True
    assert _fn(srv.get_winpc_status)()["in_use"] is False


def test_file_delegation_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.txt")
        _fn(srv.write_file)(p, "hello win")
        assert "hello win" in _content(_fn(srv.read_file)(p))


def test_proc_delegation_runs_a_command():
    # default shell is powershell; echo round-trips through _proc + the win ShellSpec.
    import time
    started = _fn(srv.start_process)("echo p1b_marker", "powershell")
    pid = started["pid"]
    try:
        out = ""
        for _ in range(60):
            out = str(_fn(srv.read_process_output)(pid))
            if "p1b_marker" in out:
                break
            time.sleep(0.05)
        assert "p1b_marker" in out
    finally:
        _fn(srv.force_terminate)(pid)
