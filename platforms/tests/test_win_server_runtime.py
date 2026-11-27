"""Windows server 的**行为**测试（用桩在 Linux 上真跑，不是 AST 断言）。

`_win_stubs.load_win_server()` 把 pywinauto/pyautogui/pyperclip 换成最小桩后真实导入
被测 server，于是 `wait_for` / `run_actions` 的判定逻辑可以被真跑：

* kind 解析（含 `*_gone`）与非法 kind 的报错形态；
* `timeout` / `probe_failed` 的区分；
* `run_actions` 的整批预校验与 `file_get` **不在**白名单（4 MiB base64 会灌爆响应）。

不验证 OS 行为：桩不做任何真实操作，真机行为由 device-operator 的验收覆盖。
"""
from __future__ import annotations

import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _win_stubs import load_win_server  # noqa: E402


@pytest.fixture(scope="module")
def win():
    return load_win_server()


def _tool_fn(obj):
    return getattr(obj, "fn", obj)


def test_wait_for_rejects_unknown_kind_and_lists_gone_variants(win):
    out = _tool_fn(win.wait_for)(kind="nonsense", target="x")
    assert out["ok"] is False and out["reason"] == "invalid_kind"
    allowed = set(out["allowed_kinds"])
    assert {"window", "text", "foreground"} <= allowed
    assert {"window_gone", "text_gone", "foreground_gone"} <= allowed, out["allowed_kinds"]


def test_wait_for_text_gone_succeeds_when_absent(win, monkeypatch):
    monkeypatch.setattr(win, "_win_find_elements",
                        lambda *a, **k: {"ok": True, "total_matched": 0, "elements": []})
    out = _tool_fn(win.wait_for)(kind="text_gone", target="打开", timeout_ms=2000)
    assert out["ok"] is True and out["kind"] == "text_gone", out


def test_wait_for_text_times_out_with_multiple_attempts(win, monkeypatch):
    monkeypatch.setattr(win, "_win_find_elements",
                        lambda *a, **k: {"ok": True, "total_matched": 0, "elements": []})
    out = _tool_fn(win.wait_for)(kind="text", target="不存在", timeout_ms=400)
    assert out["ok"] is False and out["reason"] == "timeout", out
    assert out["attempts"] >= 2, "预算内应当多次采样（探测预算不能吃满等待预算）"


def test_wait_for_probe_failure_reports_probe_failed(win, monkeypatch):
    monkeypatch.setattr(win, "_win_find_elements",
                        lambda *a, **k: {"ok": False, "reason": "uia_timeout", "error": "boom"})
    out = _tool_fn(win.wait_for)(kind="text", target="x", timeout_ms=400)
    assert out["ok"] is False
    assert out["reason"] == "probe_failed", out
    assert "uia_timeout" in (out.get("last_error") or "") + str(out.get("detail"))


def test_batch_allowlist_excludes_file_get(win):
    assert "file_get" not in win._BATCH_ALLOWLIST, "4 MiB base64 不应进批量响应"
    assert "wait_for" in win._BATCH_ALLOWLIST
    assert "file_put" in win._BATCH_ALLOWLIST


def test_run_actions_rejects_whole_batch_up_front(win):
    out = _tool_fn(win.run_actions)(steps=[{"tool": "does_not_exist"}])
    assert out["ok"] is False and out["reason"] == "invalid_steps"
    allowed = set(out["allowed_tools"])
    assert "file_get" not in allowed
    assert "wait_for" in allowed


def test_run_actions_executes_and_short_circuits(win, monkeypatch):
    calls = []

    def fake_tap(x=None, y=None, **kwargs):
        calls.append((x, y))
        return {"ok": True}

    monkeypatch.setattr(win, "tap", fake_tap)
    out = _tool_fn(win.run_actions)(
        steps=[{"tool": "tap", "args": {"x": 1, "y": 2}},
               {"tool": "tap", "args": {"x": 3, "y": 4}}])
    assert out["ok"] is True and out["completed"] == 2, out
    assert calls == [(1, 2), (3, 4)]

    monkeypatch.setattr(win, "tap", lambda x=None, y=None, **k: {"ok": False, "reason": "boom"})
    out2 = _tool_fn(win.run_actions)(
        steps=[{"tool": "tap", "args": {"x": 9, "y": 9}},
               {"tool": "tap", "args": {"x": 8, "y": 8}}])
    assert out2["ok"] is False and out2["failed_at"] == 0
    assert out2["steps"][1]["status"] == "skipped", out2
