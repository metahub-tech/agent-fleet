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
    assert _fn(srv.get_status)()["in_use"] is False
    a = _fn(srv.acquire)("tester")
    assert a.get("acquired") is True
    s1 = _fn(srv.get_status)()
    assert s1["in_use"] is True
    assert s1["holder"] == "tester"
    assert "auto_release_in_seconds" in s1
    assert _fn(srv.release)("tester").get("released") is True
    assert _fn(srv.get_status)()["in_use"] is False


def test_file_delegation_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.txt")
        _fn(srv.write_file)(p, "hello win")
        assert "hello win" in _content(_fn(srv.read_file)(p))


def test_console_window_detection():
    # console/terminal host classes are refused (their UIA tree hangs pywinauto)
    assert srv._is_console_window("ConsoleWindowClass") is True
    assert srv._is_console_window("CASCADIA_HOSTING_WINDOW_CLASS") is True
    assert srv._is_console_window("PseudoConsoleWindow") is True
    # ordinary GUI windows / empties pass through
    assert srv._is_console_window("Notepad") is False
    assert srv._is_console_window("") is False
    assert srv._is_console_window(None) is False
    msg = srv._console_skip_message("ConsoleWindowClass")
    assert "ConsoleWindowClass" in msg and "take_screenshot" in msg
    assert msg.startswith("ERROR: foreground window")
    # inspect_window path passes a custom target (not necessarily the foreground window)
    msg2 = srv._console_skip_message("ConsoleWindowClass", target="window matching 'foo'")
    assert "window matching 'foo'" in msg2 and "foreground window" not in msg2


def test_match_query_ranking():
    mq = srv._match_query
    # exact match beats substring; case-insensitive
    assert mq("SAVE", {"name": "save"}) == (True, "name", True)
    assert mq("sav", {"name": "Save Document"}) == (True, "name", False)
    # exact wins over substring even on a lower-priority field
    assert mq("ok", {"name": "ok cancel", "automation_id": "ok"}) == (True, "automation_id", True)
    # same exactness → higher-priority field wins (name > automation_id)
    assert mq("save", {"name": "save", "automation_id": "save"}) == (True, "name", True)
    # control_type / class_name are lowest priority but still match
    assert mq("button", {"control_type": "Button"}) == (True, "control_type", True)
    # no match / empty query
    assert mq("xyz", {"name": "abc"}) == (False, "", False)
    assert mq("", {"name": "abc"}) == (False, "", False)
    assert mq("a", {}) == (False, "", False)


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
