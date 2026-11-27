"""smoke_devtools 纯判据单测（无网络、无 MCP SDK，本机可跑）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smoke_devtools as sd


# --- 能力开关 -------------------------------------------------------------

def test_capability_enabled():
    ok, detail = sd.check_capability_enabled(
        {"capabilities": [{"id": "devtools", "status": "enabled", "tools": ["a", "b", "c", "d"]}]})
    assert ok is True and "4 tool" in detail


def test_capability_disabled_is_actionable():
    ok, detail = sd.check_capability_enabled({"capabilities": [{"id": "devtools", "status": "disabled"}]})
    assert ok is False
    assert "capabilities].enabled" in detail and "restart" in detail


def test_capability_missing():
    ok, detail = sd.check_capability_enabled({"capabilities": []})
    assert ok is False and "not registered" in detail
    assert sd.check_capability_enabled({})[0] is False


# --- cdp_port -------------------------------------------------------------

def test_cdp_port_alive():
    ok, detail = sd.check_cdp_port({"ok": True, "alive": True, "port": 51392,
                                    "ws_url": "ws://127.0.0.1:51392/devtools/browser/x",
                                    "browser": "Chrome/149", "probe_ms": 7})
    assert ok is True and "51392" in detail


def test_cdp_port_alive_requires_probe_ms():
    ok, detail = sd.check_cdp_port({"ok": True, "alive": True, "port": 1,
                                    "ws_url": "ws://x"})
    assert ok is False and "probe_ms" in detail


def test_cdp_port_missing_file_is_actionable():
    ok, detail = sd.check_cdp_port({"ok": False, "alive": False, "port": None,
                                    "reason": "port_file_missing", "probe_ms": 0})
    assert ok is False and "human_browser_open" in detail


def test_cdp_port_probe_failed_reports_age():
    ok, detail = sd.check_cdp_port({"ok": False, "reason": "version_probe_failed",
                                    "port": 51392, "port_file_age_ms": 75_000,
                                    "note": "clock_skew"})
    assert ok is False and "75000" in detail and "clock_skew" in detail


# --- list_tabs ------------------------------------------------------------

def _tabs(visibility="visible", duration=200):
    return {"ok": True, "duration_ms": duration, "probe_ms": 12,
            "tabs": [{"target_id": "T1", "url": "https://mp.weixin.qq.com/x?y=" + "z" * 100,
                      "title": "公众号", "visibility": visibility}]}


def test_list_tabs_ok_and_full_url():
    ok, detail = sd.check_list_tabs(_tabs())
    assert ok is True and "duration_ms=200" in detail


def test_list_tabs_rejects_frozen_key():
    payload = _tabs()
    payload["tabs"][0]["frozen"] = False
    ok, detail = sd.check_list_tabs(payload)
    assert ok is False and "frozen" in detail


def test_list_tabs_rejects_hang():
    ok, detail = sd.check_list_tabs(_tabs(duration=1500))
    assert ok is False and "1500" in detail


def test_list_tabs_rejects_bad_visibility():
    ok, detail = sd.check_list_tabs(_tabs(visibility="frozen"))
    assert ok is False and "visibility" in detail


def test_list_tabs_empty():
    ok, detail = sd.check_list_tabs({"ok": True, "duration_ms": 5, "tabs": []})
    assert ok is False and "no page tabs" in detail


# --- eval -----------------------------------------------------------------

def test_eval_visibility_ok():
    ok, detail = sd.check_eval_visibility({"ok": True, "value": "visible",
                                           "activated": True, "size_bytes": 9})
    assert ok is True and "visible" in detail


def test_eval_requires_activated_true():
    ok, detail = sd.check_eval_visibility({"ok": True, "value": "visible", "activated": False})
    assert ok is False and "activated" in detail


def test_eval_wrong_value():
    ok, _ = sd.check_eval_visibility({"ok": True, "value": "hidden-ish", "activated": True})
    assert ok is False


# --- 超限必须报错且不截断 --------------------------------------------------

def test_oversize_rejected_correctly():
    ok, detail = sd.check_oversize_is_rejected(
        {"ok": False, "reason": "result_too_large", "size_bytes": 4096,
         "activated": True, "max_result_bytes": 1024}, 1024)
    assert ok is True and "4096" in detail


def test_oversize_accepted_is_failure():
    ok, detail = sd.check_oversize_is_rejected({"ok": True, "value": "xxxx"}, 1024)
    assert ok is False and "must fail" in detail


def test_oversize_with_truncated_value_is_failure():
    ok, detail = sd.check_oversize_is_rejected(
        {"ok": False, "reason": "result_too_large", "size_bytes": 4096, "value": "trunc"}, 1024)
    assert ok is False and "truncated" in detail


def test_oversize_wrong_reason_is_failure():
    ok, detail = sd.check_oversize_is_rejected(
        {"ok": False, "reason": "cdp_timeout", "size_bytes": 4096}, 1024)
    assert ok is False and "result_too_large" in detail


# --- activate -------------------------------------------------------------

def test_activate_ok():
    ok, detail = sd.check_activate({"ok": True, "target_id": "T1", "url": "https://a/"})
    assert ok is True and "T1" in detail


def test_activate_ambiguous_is_failure_with_hint():
    ok, detail = sd.check_activate({"ok": False, "reason": "PAGE_AMBIGUOUS",
                                    "candidates": [{"target_id": "a"}, {"target_id": "b"}]})
    assert ok is False and "unique url_part" in detail


def test_tab_visible_after_activate():
    after = {"ok": True, "tabs": [{"target_id": "T1", "visibility": "visible"}]}
    assert sd.check_tab_visible_after_activate(after, "T1")[0] is True
    unknown = {"ok": True, "tabs": [{"target_id": "T1", "visibility": "unknown"}]}
    assert sd.check_tab_visible_after_activate(unknown, "T1")[0] is True   # 预算内，不算挂
    hidden = {"ok": True, "tabs": [{"target_id": "T1", "visibility": "hidden"}]}
    assert sd.check_tab_visible_after_activate(hidden, "T1")[0] is False
    missing = {"ok": True, "tabs": []}
    assert sd.check_tab_visible_after_activate(missing, "T1")[0] is False


# --- profile 引号剥离（真机回执：PowerShell 传成字面量导致 port_file_missing）---

def test_normalize_profile_strips_quotes():
    assert sd.normalize_profile('"~/.fleet/op-1"') == "~/.fleet/op-1"
    assert sd.normalize_profile("'~/.fleet/op-1'") == "~/.fleet/op-1"
    assert sd.normalize_profile('  "~/.fleet/op-1"  ') == "~/.fleet/op-1"


def test_normalize_profile_leaves_plain_values_alone():
    assert sd.normalize_profile("~/.fleet/op-1") == "~/.fleet/op-1"
    assert sd.normalize_profile("") == ""
    assert sd.normalize_profile('"') == '"'          # 单字符不当引号处理


def test_resolve_timeout_clamps_and_falls_back():
    assert sd.resolve_timeout(1) == sd.MIN_TIMEOUT_S
    assert sd.resolve_timeout(45) == 45.0
    assert sd.resolve_timeout(object()) == 180.0


# --- 选页：撞重复 URL 时退回 target_id（真机 v3 回执）---------------------

def test_choose_target_prefers_unique_url():
    tabs = [{"id": "A", "url": "https://a.example/x"},
            {"id": "B", "url": "https://b.example/y"},
            {"id": "C", "url": "https://b.example/y"}]
    url, tid = sd.choose_target(tabs)
    assert url == "https://a.example/x" and tid == ""


def test_choose_target_falls_back_to_target_id_when_all_urls_duplicate():
    tabs = [{"id": "A", "url": "https://zhihu.com/creator"},
            {"id": "B", "url": "https://zhihu.com/creator"}]
    url, tid = sd.choose_target(tabs)
    assert url == "" and tid == "A"


def test_choose_target_ignores_non_http_tabs():
    tabs = [{"id": "A", "url": "about:blank"}, {"id": "B", "url": "chrome://settings"}]
    assert sd.choose_target(tabs) == ("", "")


def test_choose_target_handles_empty():
    assert sd.choose_target([]) == ("", "")
