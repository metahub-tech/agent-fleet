"""human_browser_open activate 分派: 复用+activate=False 不调 foreground; 复用+True 调; 冷启动传 activate;
   default-daily 路径 activated=None。字段 activated/maximized 反映真实动作(不用 bool(fn))。
运行: cd platforms/common && python3 -m pytest tests/test_human_browser_activate.py -v"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.browser import _human_browser as hb


class _Mcp:
    def __init__(self): self.tools = {}
    def tool(self, fn): self.tools[fn.__name__] = fn; return fn


def _open_tool(monkeypatch, foreground_calls, warm):
    cap = hb.HumanBrowserCapability(
        bridge_port=None,
        maximize_fn=lambda udd, activate=True: (foreground_calls.append((udd, activate)) or True))
    monkeypatch.setattr(hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(hb, "_resolve_profile", lambda p: ("/udd/x", None, "keyx"))
    monkeypatch.setattr(hb, "_detect_reuse",
                        lambda key, udd, _probe=None: ({"port": None, "via": "in-process"} if warm else None))
    monkeypatch.setattr(hb, "_ensure_human_dom_ext", lambda profile, bp: None)
    monkeypatch.setattr(hb.subprocess, "Popen",
                        lambda *a, **k: type("P", (), {"poll": lambda self: None})())
    monkeypatch.setattr(hb, "_warm_navigate", lambda port, url: "no-url")
    m = _Mcp(); cap.register(m); return m.tools["human_browser_open"]


def test_warm_default_no_foreground(monkeypatch):
    calls = []
    open_ = _open_tool(monkeypatch, calls, warm=True)
    r = open_(url="", profile="~/.fleet/op-x")            # activate 默认 False
    assert calls == []                                     # 复用+默认 → 零调用(P0 治 #188)
    assert r["reused"] is True and r["maximized"] is False and r["activated"] is False


def test_warm_activate_true_calls_foreground(monkeypatch):
    calls = []
    open_ = _open_tool(monkeypatch, calls, warm=True)
    r = open_(url="", profile="~/.fleet/op-x", activate=True)
    assert calls == [("/udd/x", True)]                     # 复用+activate=True → 调 (udd, True)
    assert r["maximized"] is True and r["activated"] is True


def test_cold_passes_activate_false(monkeypatch):
    calls = []
    open_ = _open_tool(monkeypatch, calls, warm=False)
    r = open_(url="", profile="~/.fleet/op-x", activate=False)
    assert calls == [("/udd/x", False)]                    # 冷启动 → 调 (udd, False) 非激活最大化
    assert r["reused"] is False


def test_default_daily_activated_none(monkeypatch):
    # 无 profile → default-daily 路径: 不确定性控前台 → activated=None(非 False)
    monkeypatch.setattr(hb, "_chrome_path", lambda: "/fake/chrome")
    monkeypatch.setattr(hb.subprocess, "Popen",
                        lambda *a, **k: type("P", (), {"poll": lambda self: None})())
    cap = hb.HumanBrowserCapability(bridge_port=None, maximize_fn=lambda *a, **k: True)
    m = _Mcp(); cap.register(m)
    r = m.tools["human_browser_open"](url="https://x.com", profile="")
    assert r["ok"] is True and r["activated"] is None
