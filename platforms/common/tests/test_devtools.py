"""devtools 能力单测：纯辅助 + 四个工具对假 CDP 的行为。

本机（无 Chrome）可跑：所有网络入口都 monkeypatch 掉 `_cdp` 的函数，
断言的是**契约**（reason 枚举、不截断、后台标签语义），不是真浏览器行为。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capabilities.devtools import _devtools as dv


class FakeMcp:
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def _tools():
    cap = dv.DevtoolsCapability()
    mcp = FakeMcp()
    names = cap.register(mcp)
    assert names == ["cdp_port", "list_tabs", "activate_tab", "eval_in_profile"]
    return mcp.tools


# --- 纯辅助 ---------------------------------------------------------------

def test_normalize_tab_keeps_full_url():
    tab = dv.normalize_tab({"id": "T1", "url": "https://mp.weixin.qq.com/cgi-bin/appmsg?t=1&x=" + "a" * 200,
                            "title": "标题"})
    assert tab["target_id"] == "T1"
    assert tab["url"].endswith("a" * 200)      # 不截断
    assert tab["visibility"] == "unknown"


def test_pick_single_page():
    assert dv.pick_single_page([]) == (None, "no_target")
    page = {"id": "T1"}
    assert dv.pick_single_page([page]) == (page, None)
    assert dv.pick_single_page([{"id": "a"}, {"id": "b"}]) == (None, "page_ambiguous")


def test_match_pages_unique_and_ambiguous():
    pages = [{"id": "a", "url": "https://mp.weixin.qq.com/x"},
             {"id": "b", "url": "https://zhuanlan.zhihu.com/y"}]
    assert dv.match_pages(pages, "weixin")[0]["id"] == "a"
    assert dv.match_pages(pages, "https")[0] is None      # 多命中
    assert dv.match_pages(pages, "nope")[1] == []          # 0 命中
    assert dv.match_pages(pages, "")[0] is None


def test_value_size_bytes_counts_utf8_bytes_not_chars():
    assert dv.value_size_bytes("abc") == 5          # "abc" + 引号
    assert dv.value_size_bytes("中文") == len(json.dumps("中文", ensure_ascii=False).encode("utf-8"))
    assert dv.value_size_bytes("中文") > len(json.dumps("中文", ensure_ascii=False))


def test_classify_eval_error():
    assert dv.classify_eval_error({"reason": "cdp_error", "message": "Object couldn't be returned by value"},
                                  activated=True) == "not_serializable"
    # 未激活时的超时 → 冻结后台标签（调用方该先 activate）
    assert dv.classify_eval_error({"reason": "cdp_timeout", "message": "x"}, activated=False) == "frozen_background_tab"
    assert dv.classify_eval_error({"reason": "cdp_timeout", "message": "x"}, activated=True) == "cdp_timeout"


def test_find_frame_id_matches_id_and_url_recursively():
    tree = {"frame": {"id": "root", "url": "https://a/"}, "childFrames": [
        {"frame": {"id": "F1", "url": "https://mp.weixin.qq.com/editor"}},
    ]}
    assert dv.find_frame_id(tree, "F1") == "F1"
    assert dv.find_frame_id(tree, "weixin") == "F1"
    assert dv.find_frame_id(tree, "root") == "root"
    assert dv.find_frame_id(tree, "missing") is None


# --- cdp_port -------------------------------------------------------------

def test_cdp_port_missing_file(monkeypatch):
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: None)
    r = _tools()["cdp_port"](profile="")
    assert r["ok"] is False and r["alive"] is False
    assert r["reason"] == "port_file_missing"
    assert "port_file_age_ms" not in r
    assert isinstance(r["probe_ms"], int)


def test_cdp_port_probe_failed_reports_age(monkeypatch):
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 51392)
    monkeypatch.setattr(dv._cdp, "probe_version", lambda port: (None, "version_probe_failed"))
    monkeypatch.setattr(dv._cdp, "port_file_age_ms", lambda udd: (75_000, None))
    r = _tools()["cdp_port"](profile="")
    assert r["ok"] is False and r["reason"] == "version_probe_failed"
    assert r["port_file_age_ms"] == 75_000
    assert "note" not in r


def test_cdp_port_age_absent_for_other_reasons(monkeypatch):
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 51392)
    monkeypatch.setattr(dv._cdp, "probe_version", lambda port: ({"Browser": "Chrome/149"}, "handshake_timeout"))
    monkeypatch.setattr(dv._cdp, "port_file_age_ms", lambda udd: (1000, None))
    r = _tools()["cdp_port"](profile="")
    assert r["reason"] == "handshake_timeout"
    assert "port_file_age_ms" not in r          # 只在该 reason 下出现


def test_cdp_port_alive(monkeypatch):
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 51392)
    monkeypatch.setattr(dv._cdp, "probe_version",
                        lambda port: ({"Browser": "Chrome/149", "webSocketDebuggerUrl": "ws://127.0.0.1:51392/dev"}, None))
    r = _tools()["cdp_port"](profile="")
    assert r["ok"] is True and r["alive"] is True and r["port"] == 51392
    assert r["browser"] == "Chrome/149" and r["ws_url"].startswith("ws://")
    assert isinstance(r["probe_ms"], int)


# --- list_tabs ------------------------------------------------------------

def test_list_tabs_visibility_mapping_and_budget(monkeypatch):
    pages = [
        {"id": "T1", "url": "https://a/", "title": "A", "webSocketDebuggerUrl": "ws://x/1"},
        {"id": "T2", "url": "https://b/", "title": "B", "webSocketDebuggerUrl": "ws://x/2"},
    ]
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 1)
    monkeypatch.setattr(dv._cdp, "probe_version", lambda port: ({"Browser": "C"}, None))
    monkeypatch.setattr(dv._cdp, "page_targets", lambda port: (pages, None))

    calls = {"n": 0}

    def fake_ws(url, timeout=1.0):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("frozen")
        return object()

    def fake_call(sock, cid, method, params=None, timeout=1.0):
        return ({"result": {"result": {"value": "visible"}}}, None)

    monkeypatch.setattr(dv._cdp, "ws_connect", fake_ws)
    monkeypatch.setattr(dv._cdp, "call", fake_call)
    monkeypatch.setattr(dv._cdp, "close_quietly", lambda s: None)

    r = _tools()["list_tabs"](profile="", probe_budget_ms=5000)
    assert r["ok"] is True
    assert [t["visibility"] for t in r["tabs"]] == ["visible", "unknown"]
    assert all("frozen" not in t for t in r["tabs"])   # 不给 frozen 布尔
    assert isinstance(r["probe_ms"], int) and isinstance(r["duration_ms"], int)


def test_list_tabs_missing_port(monkeypatch):
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: None)
    r = _tools()["list_tabs"](profile="")
    assert r["ok"] is False and r["reason"] == "port_file_missing" and r["tabs"] == []


# --- activate_tab ---------------------------------------------------------

def test_activate_tab_ambiguous_lists_candidates(monkeypatch):
    pages = [{"id": "a", "url": "https://mp.weixin.qq.com/1"},
             {"id": "b", "url": "https://mp.weixin.qq.com/2"}]
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 1)
    monkeypatch.setattr(dv._cdp, "connect_browser", lambda udd, t: (object(), 1))
    monkeypatch.setattr(dv._cdp, "page_targets", lambda port: (pages, None))
    monkeypatch.setattr(dv._cdp, "close_quietly", lambda s: None)
    r = _tools()["activate_tab"](profile="", url_part="weixin")
    assert r["ok"] is False and r["reason"] == "PAGE_AMBIGUOUS"
    assert {c["target_id"] for c in r["candidates"]} == {"a", "b"}


def test_activate_tab_unique_hit(monkeypatch):
    pages = [{"id": "a", "url": "https://mp.weixin.qq.com/1", "webSocketDebuggerUrl": "ws://x"}]
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 1)
    monkeypatch.setattr(dv._cdp, "connect_browser", lambda udd, t: (object(), 1))
    monkeypatch.setattr(dv._cdp, "page_targets", lambda port: (pages, None))
    monkeypatch.setattr(dv._cdp, "call", lambda *a, **k: ({"result": {}}, None))
    monkeypatch.setattr(dv._cdp, "close_quietly", lambda s: None)
    r = _tools()["activate_tab"](profile="", url_part="weixin")
    assert r == {"ok": True, "target_id": "a", "url": "https://mp.weixin.qq.com/1"}


# --- eval_in_profile ------------------------------------------------------

def _patch_eval_env(monkeypatch, pages, eval_reply):
    monkeypatch.setattr(dv._cdp, "read_port_once", lambda udd: 1)
    monkeypatch.setattr(dv._cdp, "connect_browser", lambda udd, t: (object(), 1))
    monkeypatch.setattr(dv._cdp, "page_targets", lambda port: (pages, None))
    monkeypatch.setattr(dv._cdp, "ws_connect", lambda url, timeout=1.0: object())
    monkeypatch.setattr(dv._cdp, "close_quietly", lambda s: None)

    def fake_call(sock, cid, method, params=None, timeout=1.0):
        if method in ("Target.activateTarget",):
            return ({"result": {}}, None)
        return eval_reply

    monkeypatch.setattr(dv._cdp, "call", fake_call)


_PAGE = [{"id": "a", "url": "https://mp.weixin.qq.com/x", "webSocketDebuggerUrl": "ws://x"}]


def test_eval_ok(monkeypatch):
    _patch_eval_env(monkeypatch, _PAGE, ({"result": {"result": {"value": 42}}}, None))
    r = _tools()["eval_in_profile"](profile="", js="1+1")
    assert r["ok"] is True and r["value"] == 42 and r["activated"] is True
    assert r["size_bytes"] > 0


def test_eval_result_too_large_is_not_truncated(monkeypatch):
    big = "x" * 2048
    _patch_eval_env(monkeypatch, _PAGE, ({"result": {"result": {"value": big}}}, None))
    r = _tools()["eval_in_profile"](profile="", js="big", max_result_bytes=1024)
    assert r["ok"] is False and r["reason"] == "result_too_large"
    assert r["size_bytes"] > 1024
    assert "value" not in r                     # 绝不返回被截断的值


def test_eval_not_serializable(monkeypatch):
    _patch_eval_env(monkeypatch, _PAGE,
                    (None, {"reason": "cdp_error", "message": "Object couldn't be returned by value"}))
    r = _tools()["eval_in_profile"](profile="", js="document")
    assert r["reason"] == "not_serializable"


def test_eval_background_tab_without_activate(monkeypatch):
    _patch_eval_env(monkeypatch, _PAGE, (None, {"reason": "cdp_timeout", "message": "timed out"}))
    r = _tools()["eval_in_profile"](profile="", js="1", activate=False)
    assert r["ok"] is False and r["activated"] is False
    assert r["reason"] == "frozen_background_tab"


def test_eval_js_exception(monkeypatch):
    _patch_eval_env(monkeypatch, _PAGE,
                    ({"result": {"exceptionDetails": {"text": "Uncaught", "exception": {"description": "Error: boom"}}}}, None))
    r = _tools()["eval_in_profile"](profile="", js="throw new Error('boom')")
    assert r["reason"] == "js_exception" and "boom" in r["error"]


def test_eval_page_ambiguous(monkeypatch):
    pages = [{"id": "a", "url": "https://a/", "webSocketDebuggerUrl": "ws://1"},
             {"id": "b", "url": "https://b/", "webSocketDebuggerUrl": "ws://2"}]
    _patch_eval_env(monkeypatch, pages, ({"result": {"result": {"value": 1}}}, None))
    r = _tools()["eval_in_profile"](profile="", js="1")
    assert r["ok"] is False and r["reason"] == "page_ambiguous"
    assert len(r["candidates"]) == 2


def test_eval_frame_not_found(monkeypatch):
    _patch_eval_env(monkeypatch, _PAGE, ({"result": {"result": {"value": 1}}}, None))

    def fake_call(sock, cid, method, params=None, timeout=1.0):
        if method == "Target.activateTarget":
            return ({"result": {}}, None)
        if method == "Page.getFrameTree":
            return ({"result": {"frame": {"id": "root", "url": "https://a/"}}}, None)
        return ({"result": {"result": {"value": 1}}}, None)

    monkeypatch.setattr(dv._cdp, "call", fake_call)
    r = _tools()["eval_in_profile"](profile="", js="1", frame="nope")
    assert r["ok"] is False and r["reason"] == "frame_not_found"


# --- 选页：target_id / url_part（真机回执：profile 有 33 个标签页）-------

def _pages(n=3):
    return [{"id": f"T{i}", "url": f"https://example.com/p{i}", "title": f"p{i}",
             "webSocketDebuggerUrl": f"ws://x/{i}"} for i in range(n)]


def test_pick_page_by_target_id():
    page, reason = dv.pick_page(_pages(), target_id="T2")
    assert reason is None and page["id"] == "T2"


def test_pick_page_by_url_part():
    page, reason = dv.pick_page(_pages(), url_part="p1")
    assert reason is None and page["id"] == "T1"


def test_pick_page_url_part_ambiguous():
    pages = _pages() + [{"id": "T9", "url": "https://example.com/p1-dup",
                         "title": "dup", "webSocketDebuggerUrl": "ws://x/9"}]
    page, reason = dv.pick_page(pages, url_part="p1")
    assert page is None and reason == "page_ambiguous"


def test_pick_page_no_match_is_no_target():
    page, reason = dv.pick_page(_pages(), url_part="nope")
    assert page is None and reason == "no_target"
    page, reason = dv.pick_page(_pages(), target_id="T99")
    assert page is None and reason == "no_target"


def test_pick_page_falls_back_to_single_page_rule():
    page, reason = dv.pick_page(_pages(1))
    assert reason is None and page["id"] == "T0"
    page, reason = dv.pick_page(_pages(3))
    assert page is None and reason == "page_ambiguous"


# --- 并发 visibility 探测（真账号 profile 几十个标签页）-------------------

def _pages_n(n=12):
    return [{"id": f"T{i}", "url": f"https://e.com/{i}", "webSocketDebuggerUrl": f"ws://x/{i}"}
            for i in range(n)]


def test_probe_visibilities_covers_all_pages_concurrently():
    pages = _pages_n(12)
    seen = []

    def probe(page, remaining):
        seen.append(page["id"])
        return "visible" if page["id"] == "T7" else "hidden"

    out = dv.probe_visibilities(pages, probe, budget_s=1.0, max_workers=8)
    assert len(out) == 12
    assert out["T7"] == "visible"
    assert out["T0"] == "hidden"


def test_probe_visibilities_marks_unfinished_unknown_without_retry():
    import threading as _t

    pages = _pages_n(4)
    release = _t.Event()

    def probe(page, remaining):
        release.wait(0.05)
        return "visible"

    out = dv.probe_visibilities(pages, probe, budget_s=0.01, max_workers=4)
    # 预算极小 → 都应该是 unknown（不死等、不重试），且一个不少
    assert set(out) == {p["id"] for p in pages}
    assert all(v == "unknown" for v in out.values())


def test_probe_visibilities_treats_exceptions_as_unknown():
    pages = _pages_n(3)

    def probe(page, remaining):
        raise RuntimeError("ws dead")

    out = dv.probe_visibilities(pages, probe, budget_s=1.0)
    assert all(v == "unknown" for v in out.values())


def test_probe_visibilities_empty_list():
    assert dv.probe_visibilities([], lambda p, r: "visible", budget_s=1.0) == {}


def test_probe_visibilities_invalid_value_becomes_unknown():
    pages = _pages_n(2)
    out = dv.probe_visibilities(pages, lambda p, r: "frozen", budget_s=1.0)
    assert set(out.values()) == {"unknown"}
