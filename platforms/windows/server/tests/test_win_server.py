"""In-venv smoke tests for the wired Windows server. Runs ONLY on Windows (the
server imports pyautogui/pywinauto). Importing the module is itself the floor check
(deps + the `common` shared modules resolve); the rest exercise the delegation +
single-device tools without GUI side effects (no swipe/current_app here — those move
the cursor / query the desktop and are covered by the MCP smoke test)."""
import os

import pytest
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


@pytest.mark.skipif(os.name != "nt", reason="needs PowerShell (Windows-only)")
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


# --- R1 坐标系确定性校正 on-host smoke（spec §5.2）---

def test_screenshot_and_vision_share_single_capture_primitive():
    # ①注入身份: vision 拿到的 capture_fn 就是单一原语(同一函数对象), 不是各写一份
    vis = srv._cap_registry._modules["vision"]
    assert vis._capture_fn is srv._capture_in_tap_space


def test_take_screenshot_delegates_to_single_primitive(monkeypatch):
    # ②委派证明: monkeypatch 单一原语 → take_screenshot 必调它(未各写一份 grab), 防复发闸
    called = {"n": 0}

    def spy(region=None):
        called["n"] += 1
        return b"\x89PNG_sentinel"

    monkeypatch.setattr(srv, "_capture_in_tap_space", spy)
    _fn(srv.take_screenshot)()
    assert called["n"] == 1


@pytest.mark.skipif(os.name != "nt", reason="DPI awareness needs Windows + win32 API")
def test_dpi_aware_and_scale_factor_exposed():
    # 正向锚点: Win10 1703+ 上 awareness 应成功; scale_factor 仅自检不进坐标
    ss = _fn(srv.get_screen_size)()
    assert "dpi_aware" in ss and "scale_factor" in ss
    assert ss["dpi_aware"] is True
    assert isinstance(ss["scale_factor"], (int, float)) and ss["scale_factor"] >= 1.0
    assert "dpi_aware" in _fn(srv.get_status)()


def test_dpi_awareness_report_pure():
    import win_input
    assert win_input.dpi_awareness_report(True) is None
    assert "漂移" in win_input.dpi_awareness_report(False)


# --- UIA 预算 + 「一字一节点」合并（2026-11-27，device-operator 社媒场景）---

class _FakeInfo:
    def __init__(self, name, control_type="Text", class_name="TextBlock", automation_id=""):
        self.name = name
        self.control_type = control_type
        self.class_name = class_name
        self.automation_id = automation_id


class _FakeRect:
    def __init__(self, left, top, width=20, height=24):
        self.left = left
        self.top = top
        self.right = left + width
        self.bottom = top + height


class _FakeElement:
    def __init__(self, name, left, top=0, control_type="Text", **kw):
        self.element_info = _FakeInfo(name, control_type=control_type, **kw)
        self._rect = _FakeRect(left, top)

    def rectangle(self):
        return self._rect


def test_glyph_text_runs_merges_single_char_leaves():
    descendants = [_FakeElement("订", 100), _FakeElement("阅", 120), _FakeElement("已", 140)]
    runs, meta = srv._glyph_text_runs(descendants)
    assert meta["applied"] is True and meta["glyph_nodes"] == 3
    assert len(runs) == 1
    assert runs[0]["name"] == "订阅已" and runs[0]["merged_from"] == 3


def test_collect_run_matches_clicks_only_matched_span():
    descendants = [_FakeElement("订", 100), _FakeElement("阅", 120), _FakeElement("已", 140)]
    runs, _meta = srv._glyph_text_runs(descendants)
    matched = srv._collect_run_matches(runs, "订阅", 1920, 1080)
    assert len(matched) == 1
    el = matched[0]
    assert el["merged"] is True
    # 「订阅」占前两个节点 → 中心 120，而不是整段中心 130
    assert el["center"] == [120, 12]
    assert el["rect"] == [100, 0, 140, 24]
    assert el["full_rect"] == [100, 0, 160, 24]


def test_glyph_merge_disabled_by_default_for_multi_char_labels():
    # 正常两字标签不该被拼起来（默认 max_run_chars=1）
    descendants = [_FakeElement("姓名", 100), _FakeElement("电话", 120)]
    runs, meta = srv._glyph_text_runs(descendants)
    assert runs == [] and meta["runs"] == 0
