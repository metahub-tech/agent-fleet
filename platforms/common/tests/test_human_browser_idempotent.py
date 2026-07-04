"""human_browser_open 幂等复用(AgentHub #100 轮31)。

真实场景: 操作员 agent 把 human_browser_open 当"翻页/刷新"反复调(一个任务 17 次)。原实现每次
无条件重启 Chrome + 重跑 CDP 装扩展 → 慢 + 破坏(顶掉登录页)。这里验证工具层幂等:
同一 profile 连续 open → 只第一次冷启动 spawn+装扩展, 后续 reused:true、无新进程、无新标签、无 loadUnpacked 重跑。

纯合成/单元(无真机 Chrome): 靠 monkeypatch 拦 spawn/probe/loader, 计次断言。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # common/ for capabilities & _browser_lease

from capabilities.browser import _human_browser as _hb


# ── 测试替身 ─────────────────────────────────────────────────────────────────
class _FakeMCP:
    """捕获 @mcp.tool 注册的闭包(镜像 test_vision 的 _FakeMCP)。"""
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


class _FakeProc:
    """假 Popen 句柄: poll()==None 表存活。"""
    def __init__(self):
        self._alive = True

    def poll(self):
        return None if self._alive else 0


class _PopenRecorder:
    """记录每次 spawn(Popen/run)调用, 返回存活假进程。"""
    def __init__(self):
        self.calls = []

    def __call__(self, args, *a, **kw):
        self.calls.append(args)
        return _FakeProc()


def _open_fn(cap):
    m = _FakeMCP()
    cap.register(m)
    return m.tools["human_browser_open"]


# ── 单元: _same_origin ───────────────────────────────────────────────────────
def test_same_origin_true_diff_path():
    assert _hb._same_origin("https://mp.weixin.qq.com/home", "https://mp.weixin.qq.com/appmsg")

def test_same_origin_false_scheme():
    assert not _hb._same_origin("https://a.com/x", "http://a.com/x")

def test_same_origin_false_host():
    assert not _hb._same_origin("https://a.com", "https://b.com")

def test_same_origin_false_blank_or_newtab():
    assert not _hb._same_origin("", "https://a.com")
    assert not _hb._same_origin("chrome://newtab/", "https://a.com")


# ── 单元: _detect_reuse(探测冷/热)──────────────────────────────────────────
def test_detect_reuse_cold():
    _hb._LAUNCHED.clear()
    assert _hb._detect_reuse("k-cold", "/udd", _probe=lambda udd: None) is None

def test_detect_reuse_warm_via_debug_port():
    _hb._LAUNCHED.clear()
    r = _hb._detect_reuse("k-port", "/udd", _probe=lambda udd: 9222)
    assert r == {"port": 9222, "via": "debug-port"}

def test_detect_reuse_warm_via_inproc():
    _hb._LAUNCHED.clear()
    _hb._record_launch("k-inproc", _FakeProc())
    try:
        r = _hb._detect_reuse("k-inproc", "/udd", _probe=lambda udd: None)
        assert r == {"port": None, "via": "in-process"}
    finally:
        _hb._LAUNCHED.clear()

def test_detect_reuse_stale_inproc_dropped():
    _hb._LAUNCHED.clear()
    dead = _FakeProc(); dead._alive = False
    _hb._record_launch("k-stale", dead)
    try:
        assert _hb._detect_reuse("k-stale", "/udd", _probe=lambda udd: None) is None
        assert "k-stale" not in _hb._LAUNCHED  # 陈旧记录被清
    finally:
        _hb._LAUNCHED.clear()

def test_detect_reuse_prefers_port_over_inproc():
    # 盘上探到活端口即热(即便进程内无记录)——跨 server 重启也能复用。
    _hb._LAUNCHED.clear()
    r = _hb._detect_reuse("k-x", "/udd", _probe=lambda udd: 9333)
    assert r["via"] == "debug-port" and r["port"] == 9333


# ── 单元: _warm_navigate(复用路径的窗口内导航决策)──────────────────────────
def test_warm_navigate_no_url():
    assert _hb._warm_navigate(9222, "") == "no-url"

def test_warm_navigate_no_port():
    assert _hb._warm_navigate(None, "https://a.com") == "no-port"

def test_warm_navigate_same_origin_noop(monkeypatch):
    import capabilities.human_dom._loader as L
    monkeypatch.setattr(L, "_http_json",
                        lambda u, _open, timeout=3.0: [{"type": "page", "url": "https://a.com/home"}])
    monkeypatch.setattr(L, "_navigate",
                        lambda p, u, _open: (_ for _ in ()).throw(AssertionError("同源不应导航/重载")))
    assert _hb._warm_navigate(9222, "https://a.com/other") == "same-origin-noop"

def test_warm_navigate_different_origin(monkeypatch):
    import capabilities.human_dom._loader as L
    monkeypatch.setattr(L, "_http_json",
                        lambda u, _open, timeout=3.0: [{"type": "page", "url": "https://other.com/home"}])
    called = []
    monkeypatch.setattr(L, "_navigate", lambda p, u, _open: called.append(u) or True)
    assert _hb._warm_navigate(9222, "https://a.com/x") == "navigated"
    assert called == ["https://a.com/x"]  # 在现有窗口导航到目标(不新开标签)

def test_warm_navigate_nav_failed(monkeypatch):
    import capabilities.human_dom._loader as L
    monkeypatch.setattr(L, "_http_json", lambda u, _open, timeout=3.0: [{"type": "page", "url": "https://other.com/a"}])
    monkeypatch.setattr(L, "_navigate", lambda p, u, _open: False)
    assert _hb._warm_navigate(9222, "https://a.com/x") == "nav-failed"

def test_warm_navigate_multi_tab_noop(monkeypatch):
    # reviewer #1: 多标签时 CDP /json 无法可靠标出前台页, 盲选 page[0] 会顶掉已登录页 → 一律不动。
    import capabilities.human_dom._loader as L
    monkeypatch.setattr(L, "_http_json", lambda u, _open, timeout=3.0: [
        {"type": "page", "url": "https://mp.weixin.qq.com/editor"},   # 操作员正在编辑的登录页
        {"type": "page", "url": "https://other.com/popup"},           # 某次点开的第二个标签
    ])
    monkeypatch.setattr(L, "_navigate",
                        lambda p, u, _open: (_ for _ in ()).throw(AssertionError("多标签下绝不应盲导航")))
    # 即便目标与某个后台标签同源, 多标签也不误判 no-op、更不盲导航 —— 统一 multi-tab-noop
    assert _hb._warm_navigate(9222, "https://newsite.com/x") == "multi-tab-noop"
    assert _hb._warm_navigate(9222, "https://mp.weixin.qq.com/x") == "multi-tab-noop"

def test_warm_navigate_probe_failed(monkeypatch):
    import capabilities.human_dom._loader as L
    def boom(u, _open, timeout=3.0):
        raise ConnectionError("端点读取失败")
    monkeypatch.setattr(L, "_http_json", boom)
    monkeypatch.setattr(L, "_navigate",
                        lambda p, u, _open: (_ for _ in ()).throw(AssertionError("读不到标签态不应导航")))
    assert _hb._warm_navigate(9222, "https://a.com/x") == "probe-failed"


# ── 验收(合成): 连开 3 次 → 冷启动 1 次 + 复用 2 次 ───────────────────────────
def test_open_3x_non_human_dom_spawns_once(monkeypatch):
    """非 human_dom 专用 profile: 连开 3 次 → Popen 只 1 次, reused=[False,True,True]。"""
    _hb._LAUNCHED.clear()
    monkeypatch.setattr(_hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(_hb, "_ensure_human_dom_ext", lambda profile, port: None)
    monkeypatch.setattr(_hb, "_probe_debug_port", lambda udd, **kw: None)  # 无真机 → 只靠进程内注册表
    rec = _PopenRecorder()
    monkeypatch.setattr(_hb.subprocess, "Popen", rec)
    cap = _hb.HumanBrowserCapability()
    open_fn = _open_fn(cap)
    try:
        rs = [open_fn("https://mp.weixin.qq.com/x", profile="~/.fleet/op-idem-a") for _ in range(3)]
        assert [r["reused"] for r in rs] == [False, True, True]
        assert len(rec.calls) == 1                      # 只冷启动 spawn 一次(无新进程)
        assert rs[1]["reuse_via"] == "in-process"
    finally:
        _hb._LAUNCHED.clear()

def test_open_3x_human_dom_skips_reload_and_reinstall(monkeypatch):
    """human_dom 专用 profile: 连开 3 次 → Popen 1 次 + loadUnpacked 1 次, 后续复用不重装扩展。"""
    _hb._LAUNCHED.clear()
    monkeypatch.setattr(_hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(_hb, "_ensure_human_dom_ext", lambda profile, port: "/fake/ext")
    monkeypatch.setattr(_hb, "_probe_debug_port", lambda udd, **kw: None)
    load_calls = []
    monkeypatch.setattr(_hb, "_maybe_load_human_dom",
                        lambda udd, ext, **kw: load_calls.append(ext) or {"ok": True, "id": "x", "navigated": True})
    rec = _PopenRecorder()
    monkeypatch.setattr(_hb.subprocess, "Popen", rec)
    cap = _hb.HumanBrowserCapability(bridge_port=8779)
    open_fn = _open_fn(cap)
    try:
        rs = [open_fn("https://mp.weixin.qq.com/x", profile="~/.fleet/op-idem-b") for _ in range(3)]
        assert [r["reused"] for r in rs] == [False, True, True]
        assert len(rec.calls) == 1        # 无新进程
        assert len(load_calls) == 1       # CDP loadUnpacked 只跑一次(复用不重装)
        assert rs[0].get("human_dom", {}).get("ok") is True
    finally:
        _hb._LAUNCHED.clear()

def test_open_reuses_via_debug_port_after_restart(monkeypatch):
    """模拟 server 重启(进程内注册表空): 盘上探到活 debug 端口 → 纯复用, 零 spawn。"""
    _hb._LAUNCHED.clear()  # 重启后注册表为空
    monkeypatch.setattr(_hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(_hb, "_ensure_human_dom_ext", lambda p, port: "/fake/ext")
    monkeypatch.setattr(_hb, "_probe_debug_port", lambda udd, **kw: 9222)  # 盘上已有存活 CDP 端点
    import capabilities.human_dom._loader as L
    monkeypatch.setattr(L, "_http_json",
                        lambda u, _open, timeout=3.0: [{"type": "page", "url": "https://mp.weixin.qq.com/home"}])
    monkeypatch.setattr(L, "_navigate", lambda p, u, _open: True)
    rec = _PopenRecorder()
    monkeypatch.setattr(_hb.subprocess, "Popen", rec)
    cap = _hb.HumanBrowserCapability(bridge_port=8779)
    open_fn = _open_fn(cap)
    try:
        r = open_fn("https://mp.weixin.qq.com/x", profile="~/.fleet/op-idem-c")
        assert r["reused"] is True and r["reuse_via"] == "debug-port"
        assert len(rec.calls) == 0            # 零 spawn(纯复用)
        assert "同源" in r["note"]            # 同源 → 未重载(保护登录态)
    finally:
        _hb._LAUNCHED.clear()

def test_open_warm_does_not_call_ensure_ext(monkeypatch):
    """复用路径连 auto-bake 都跳过(更省)——_ensure_human_dom_ext 在热路径不被调。"""
    _hb._LAUNCHED.clear()
    monkeypatch.setattr(_hb, "_chrome_binary", lambda: "/fake/chrome")
    ensure_calls = []
    monkeypatch.setattr(_hb, "_ensure_human_dom_ext",
                        lambda profile, port: ensure_calls.append(profile) or None)
    monkeypatch.setattr(_hb, "_probe_debug_port", lambda udd, **kw: None)
    monkeypatch.setattr(_hb.subprocess, "Popen", _PopenRecorder())
    cap = _hb.HumanBrowserCapability()
    open_fn = _open_fn(cap)
    try:
        open_fn("https://a.com", profile="~/.fleet/op-idem-d")  # 冷: 调 1 次
        open_fn("https://a.com", profile="~/.fleet/op-idem-d")  # 热: 不调
        open_fn("https://a.com", profile="~/.fleet/op-idem-d")  # 热: 不调
        assert len(ensure_calls) == 1
    finally:
        _hb._LAUNCHED.clear()

def test_open_different_profiles_each_cold(monkeypatch):
    """不同 profile 各自冷启动一次(幂等按 profile_key 隔离, 不误判)。"""
    _hb._LAUNCHED.clear()
    monkeypatch.setattr(_hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(_hb, "_ensure_human_dom_ext", lambda profile, port: None)
    monkeypatch.setattr(_hb, "_probe_debug_port", lambda udd, **kw: None)
    rec = _PopenRecorder()
    monkeypatch.setattr(_hb.subprocess, "Popen", rec)
    cap = _hb.HumanBrowserCapability()
    open_fn = _open_fn(cap)
    try:
        r1 = open_fn("https://a.com", profile="~/.fleet/op-idem-e1")
        r2 = open_fn("https://a.com", profile="~/.fleet/op-idem-e2")
        assert r1["reused"] is False and r2["reused"] is False
        assert len(rec.calls) == 2  # 两个 profile 各冷启动一次
    finally:
        _hb._LAUNCHED.clear()


def test_open_concurrent_same_profile_spawns_once(monkeypatch):
    """并发(线程池)同一 profile open: per-key 锁保证只冷启动一次, 无双 spawn(reviewer #2 竞态)。"""
    import threading
    import time
    _hb._LAUNCHED.clear()
    _hb._KEY_LOCKS.clear()
    monkeypatch.setattr(_hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(_hb, "_ensure_human_dom_ext", lambda profile, port: None)
    monkeypatch.setattr(_hb, "_probe_debug_port", lambda udd, **kw: None)
    rec = _PopenRecorder()

    def slow_popen(args, *a, **kw):
        time.sleep(0.05)  # 放大竞态窗口: 无锁则两线程会双 spawn
        return rec(args, *a, **kw)

    monkeypatch.setattr(_hb.subprocess, "Popen", slow_popen)
    cap = _hb.HumanBrowserCapability()
    open_fn = _open_fn(cap)
    results = {}

    def go(i):
        results[i] = open_fn("https://a.com", profile="~/.fleet/op-idem-conc")

    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    try:
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(rec.calls) == 1  # per-key 锁 → 只冷启动一次(无双 spawn)
        assert sorted(r["reused"] for r in results.values()) == [False, True]
    finally:
        _hb._LAUNCHED.clear()
        _hb._KEY_LOCKS.clear()


# ── 默认日常 Chrome(无 profile): reused=False, 不参与专用 profile 幂等 ─────────
def test_default_daily_chrome_reused_false(monkeypatch):
    monkeypatch.setattr(_hb, "_chrome_path", lambda: "/fake/chrome")
    rec = _PopenRecorder()
    monkeypatch.setattr(_hb.subprocess, "Popen", rec)
    monkeypatch.setattr(_hb.subprocess, "run", rec)  # mac 走 run, 其余走 Popen —— 两者都记
    cap = _hb.HumanBrowserCapability()
    open_fn = _open_fn(cap)
    r = open_fn("https://a.com")  # 无 profile → 默认日常 Chrome
    assert r["reused"] is False and r["profile"] == "(default-daily)"
    assert len(rec.calls) == 1
