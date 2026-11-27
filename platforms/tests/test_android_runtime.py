"""Android server 的**可执行**测试（Linux 上也能跑）。

做法：把 `ATB_ANDROID_ADB` 指到 `/bin/true`，这个 server 就能在 Linux 上 import ——
于是"只能靠读代码"的移动端接线可以真跑一遍：

* `_dump_ui_impl` / `_find_elements_impl` 抽出来后带显式 serial + 可调超时；
* `wait_for` 的 text 探测**必须用更小的单次预算**（一次 uiautomator dump 默认 15s，
  会直接吃掉 `wait_for` 默认 10s 的总预算 ⇒ 等待永远超时）；
* `run_actions` / `wait_for` 必须把 ctx 传到内层（会话默认设备）。

注意：这套测试不连真机，`adb` 是 `/bin/true`，所以只验证**接线与预算**，不验证真机行为。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVER = REPO / "platforms" / "android" / "server" / "android_device_mcp.py"


@pytest.fixture(scope="module")
def android(monkeypatch_module=None):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("ATB_ANDROID_ADB", "/bin/true")
    for p in (str(REPO / "platforms" / "common"),
              str(REPO / "platforms" / "android" / "server"),
              str(REPO / "platforms")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("android_device_mcp_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    monkeypatch.undo()


def _tool_fn(obj):
    """fastmcp 2.x 的 `@mcp.tool` 返回 FunctionTool（有 `.fn`），3.x 直接返回函数。"""
    return getattr(obj, "fn", obj)


def test_server_imports_and_registers_core_tools(android):
    for name in ("dump_ui", "find_elements", "tap_element", "wait_for", "run_actions"):
        assert callable(_tool_fn(getattr(android, name))), f"{name} 没有注册"
    # 派生出来的单次探测预算必须明显小于默认等待总预算（10s），否则等待永远超时
    dump_s, cat_s = android._probe_budgets(10_000)
    assert 1.0 <= dump_s < 10.0 and 1.0 <= cat_s < 10.0
    assert dump_s + cat_s < 10.0
    # 长等待可以放大，但不超过上限
    long_dump, long_cat = android._probe_budgets(60_000)
    assert long_dump == android.WAIT_PROBE_DUMP_TIMEOUT_S
    assert long_cat == android.WAIT_PROBE_CAT_TIMEOUT_S


def test_dump_ui_impl_returns_structured_error_without_a_device(android):
    """假 adb 下走完整个 dump 路径，必须返回结构化 dict 而不是抛异常。"""
    result = android._dump_ui_impl("fake-serial")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "error" in result


def test_find_elements_impl_also_structured(android):
    result = android._find_elements_impl("fake-serial", text="设置")
    assert isinstance(result, dict) and result["ok"] is False


def test_wait_for_text_probe_uses_smaller_budget(android, monkeypatch):
    """`wait_for(text)` 的探测必须带小预算，且必须复用已解析的 serial（不丢 ctx）。"""
    seen = {}

    def fake_find(serial, **kwargs):
        seen["serial"] = serial
        seen["kwargs"] = kwargs
        return {"ok": True, "elements": [{"text": "命中"}], "total_matched": 1}

    monkeypatch.setattr(android, "_find_elements_impl", fake_find)
    monkeypatch.setattr(android, "_resolve_device", lambda device, default=None: "fake-serial")
    out = _tool_fn(android.wait_for)(kind="text", target="命中", device=None, ctx=None)
    assert out["ok"] is True
    assert seen["serial"] == "fake-serial"
    expected_dump, expected_cat = android._probe_budgets(10_000)
    assert seen["kwargs"]["dump_timeout"] == expected_dump
    assert seen["kwargs"]["cat_timeout"] == expected_cat


def test_wait_for_rejects_unknown_kind(android):
    out = _tool_fn(android.wait_for)(kind="nonsense", target="x", device=None, ctx=None)
    assert out["ok"] is False and out["reason"] == "invalid_kind"


def test_run_actions_rejects_bad_step_up_front(android, monkeypatch):
    monkeypatch.setattr(android, "_resolve_device", lambda device, default=None: "fake-serial")
    out = _tool_fn(android.run_actions)(steps=[{"tool": "does_not_exist"}], ctx=None)
    assert out["ok"] is False and out["reason"] == "invalid_steps"
    assert "wait_for" in out["allowed_tools"]


# --- iOS 同款测试（同样可在 Linux import）---------------------------------

@pytest.fixture(scope="module")
def ios():
    monkeypatch = pytest.MonkeyPatch()
    for p in (str(REPO / "platforms" / "common"),
              str(REPO / "platforms" / "ios" / "server"),
              str(REPO / "platforms")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "ios_device_mcp_under_test", REPO / "platforms" / "ios" / "server" / "ios_device_mcp.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    monkeypatch.undo()


def test_ios_probe_query_timeout_is_fraction_of_wait(ios):
    # 默认 10s 等待 → 查询预算约为 1/3，绝不能到默认的 20s
    assert 1.0 <= ios._probe_query_timeout(10_000) < 10.0
    assert ios._probe_query_timeout(10_000) < ios.WAIT_PROBE_QUERY_TIMEOUT_S
    # 长等待放大，但不超过上限
    assert ios._probe_query_timeout(60_000) == ios.WAIT_PROBE_QUERY_TIMEOUT_S
    # 极小预算仍给 1s 下限，避免直接判死
    assert ios._probe_query_timeout(0) == 1.0


def test_ios_wait_for_text_probe_uses_budget_and_udid(ios, monkeypatch):
    seen = {}

    def fake_find(udid, using, value, timeout=None):
        seen.update(udid=udid, using=using, value=value, timeout=timeout)
        return [{"ELEMENT": "1", "name": "命中"}]

    monkeypatch.setattr(ios, "_find_elements_impl", fake_find)
    monkeypatch.setattr(ios, "_resolve_device", lambda device, default=None: "fake-udid")
    out = getattr(ios.wait_for, "fn", ios.wait_for)(kind="text", target="命中", device=None, ctx=None)
    assert out["ok"] is True
    assert seen["udid"] == "fake-udid"
    assert seen["using"] == "predicate string"
    assert 1.0 <= seen["timeout"] < 10.0
