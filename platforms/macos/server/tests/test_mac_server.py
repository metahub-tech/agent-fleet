"""In-venv smoke tests for the wired macOS server. Runs ONLY on macOS (the server
imports pyautogui/pyobjc). Importing the module is the floor check (deps + the
`common` shared modules resolve); the rest exercise the delegation + single-device
tools without GUI side effects (no swipe/current_app — covered by the MCP smoke test)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # server dir
import mac_device_mcp as srv


def _fn(tool):
    """@mcp.tool may wrap the function as a Tool; the original is at .fn."""
    return getattr(tool, "fn", tool)


def _content(r):
    return r if isinstance(r, str) else r["content"]


def test_module_imports():
    assert srv is not None  # floor: wired server imports on real macOS


def test_ax_match_query_ranking():
    mq = srv._ax_match_query
    # exact title match; case-insensitive
    assert mq("SAVE", {"title": "save"}) == (True, "title", True)
    assert mq("sav", {"title": "Save Document"}) == (True, "title", False)
    # exact wins over substring even on a lower-priority field
    assert mq("ok", {"title": "ok cancel", "label": "ok"}) == (True, "label", True)
    # same exactness → higher-priority field wins (title > label)
    assert mq("9", {"title": "9", "label": "9"}) == (True, "title", True)
    # role is lowest priority but still matches; non-str value is ignored safely
    assert mq("axbutton", {"role": "AXButton", "value": None}) == (True, "role", True)
    assert mq("xyz", {"title": "abc"}) == (False, "", False)
    assert mq("", {"title": "abc"}) == (False, "", False)


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
        _fn(srv.write_file)(p, "hello mac")
        assert "hello mac" in _content(_fn(srv.read_file)(p))


def test_proc_delegation_runs_a_command():
    # default shell is zsh; echo round-trips through _proc + the mac ShellSpec.
    import time
    started = _fn(srv.start_process)("echo p1b_marker", "zsh")
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
