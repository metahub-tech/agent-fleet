"""macOS server 的**行为**测试（桩模块，Linux 可跑）。

验证 `wait_for` 的三种结果、批量白名单，以及 **AX 预算真的被用上**：

* `_ax_walk_budgeted` 必须在预算内抛 `UiaTimeout`（不是无限等）；
* `wait_for` 的 text 探测必须用小预算（否则 10s 等待只采样 1–2 次）。

mac 真机（pyobjc）仍未验证；这里只保证"接线与判定"没有退化。
"""
from __future__ import annotations

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _mac_stubs import load_mac_server  # noqa: E402


@pytest.fixture(scope="module")
def mac():
    return load_mac_server()


def _tool_fn(obj):
    return getattr(obj, "fn", obj)


def test_wait_for_lists_gone_variants(mac):
    out = _tool_fn(mac.wait_for)(kind="nope", target="x")
    assert out["ok"] is False and out["reason"] == "invalid_kind"
    allowed = set(out["allowed_kinds"])
    assert {"app", "foreground", "text"} <= allowed
    assert {"app_gone", "foreground_gone", "text_gone"} <= allowed, allowed


def test_wait_for_text_gone_succeeds_when_absent(mac, monkeypatch):
    monkeypatch.setattr(mac, "_mac_find_elements",
                        lambda *a, **k: {"ok": True, "total_matched": 0, "elements": []})
    out = _tool_fn(mac.wait_for)(kind="text_gone", target="sheet", timeout_ms=2000)
    assert out["ok"] is True and out["kind"] == "text_gone", out


def test_wait_for_text_probe_receives_small_budget(mac, monkeypatch):
    """text 探测必须带上 `budget_s`（比 AX 总预算小）。

    注意：桩里 find 是瞬时的，所以**不能**用 `attempts` 来判断预算是否被裁剪
    （那样即使丢掉 budget_s 也测不出来）。这里直接记录调用参数。
    """
    seen = {}

    def fake_find(*args, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "total_matched": 0, "elements": []}

    monkeypatch.setattr(mac, "_mac_find_elements", fake_find)
    out = _tool_fn(mac.wait_for)(kind="text", target="missing", timeout_ms=800)
    assert out["ok"] is False and out["reason"] == "timeout", out
    assert "budget_s" in seen, f"探测没有传预算：{seen}"
    assert seen["budget_s"] <= mac.WAIT_PROBE_BUDGET_S
    assert seen["budget_s"] < mac.AX_TIMEOUT_S


def test_wait_for_probe_failure_reports_probe_failed(mac, monkeypatch):
    monkeypatch.setattr(mac, "_mac_find_elements",
                        lambda *a, **k: {"ok": False, "reason": "uia_timeout"})
    out = _tool_fn(mac.wait_for)(kind="text", target="x", timeout_ms=400)
    assert out["reason"] == "probe_failed", out


def test_ax_walk_budget_raises_uia_timeout(monkeypatch):
    """AX 遍历必须在预算内返回（抛 UiaTimeout），不能被卡死的树拖住。"""
    from _uia_bounds import UiaTimeout, run_with_timeout

    def hang():
        time.sleep(5)

    started = time.monotonic()
    with pytest.raises(UiaTimeout):
        run_with_timeout(hang, 0.2, "ax_walk")
    assert time.monotonic() - started < 2.0


def test_batch_allowlist_has_no_install_or_upload(mac):
    allow = set(mac._MAC_BATCH_ALLOWLIST)
    assert "wait_for" in allow and "find_elements" in allow
    assert not (allow & {"install_app", "uninstall_app", "upload_to_photos", "upload_to_app"})


def test_run_actions_rejects_whole_batch_up_front(mac):
    out = _tool_fn(mac.run_actions)(steps=[{"tool": "nope"}])
    assert out["ok"] is False and out["reason"] == "invalid_steps"
    assert "install_app" not in out["allowed_tools"]
