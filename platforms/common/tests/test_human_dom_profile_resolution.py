"""human_dom profile 解析硬化: 桥活跃 operator 解析 + resolve_profile_id + 工具接线 + _do_fill 重试。
纯 Python 本机可跑(不依赖 numpy)。运行: cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -v"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._bridge import DomBridge


class FakeWS:
    async def send_json(self, m): pass


def _reg(b, ws, pid, active=True, ts=0.0):
    """register 一个客户端并设显式 last_active_ts(确定性排序)。"""
    b.register(ws, profile_id=pid, tab_id="t", url="u", active=active)
    for c in b._clients:
        if c["ws"] is ws:
            c["last_active_ts"] = ts


def test_active_operator_unique():
    b = DomBridge()
    _reg(b, FakeWS(), "default", ts=5.0)
    _reg(b, FakeWS(), "op-aaa", ts=1.0)
    assert b.active_operator_profile() == "op-aaa"        # 唯一 operator, 忽略 default


def test_active_operator_most_recent():
    b = DomBridge()
    _reg(b, FakeWS(), "op-aaa", ts=1.0)
    _reg(b, FakeWS(), "op-bbb", ts=9.0)                   # 更近活跃
    assert b.active_operator_profile() == "op-bbb"


def test_active_operator_prefers_active_over_ts():
    b = DomBridge()
    _reg(b, FakeWS(), "op-old", active=True, ts=1.0)
    _reg(b, FakeWS(), "op-inactive", active=False, ts=9.0)  # ts 更近但非 active
    assert b.active_operator_profile() == "op-old"       # active 优先于 ts


def test_active_operator_none_when_only_default():
    b = DomBridge()
    _reg(b, FakeWS(), "default", ts=1.0)
    assert b.active_operator_profile() is None            # 仅 default → None → 调用方回退 default


def test_active_operator_none_when_empty():
    assert DomBridge().active_operator_profile() is None


# --- resolve_profile_id ---
from capabilities.human_dom._ident import resolve_profile_id, human_dom_profile_id


class _FakeBridge:
    def __init__(self, op): self._op = op; self._clients = []
    def active_operator_profile(self): return self._op


class _RaisingBridge:
    _clients = []
    def active_operator_profile(self):
        raise AssertionError("显式 profile 不该问桥")


def test_resolve_explicit_does_not_consult_bridge():
    # 显式 profile → 走 human_dom_profile_id, 不问桥(RaisingBridge 若被问会抛)
    assert resolve_profile_id(_RaisingBridge(), "~/.fleet/foo") == human_dom_profile_id("~/.fleet/foo")


def test_resolve_omitted_uses_operator():
    assert resolve_profile_id(_FakeBridge("op-aaa"), "") == "op-aaa"
    assert resolve_profile_id(_FakeBridge("op-aaa"), None) == "op-aaa"
    assert resolve_profile_id(_FakeBridge("op-aaa"), "   ") == "op-aaa"   # 纯空白视为省略


def test_resolve_omitted_falls_back_default():
    assert resolve_profile_id(_FakeBridge(None), "") == "default"          # 无 operator → default


# --- 工具接线: locate/tap 用 resolve_profile_id + 成功带 resolved_profile ---
from capabilities.human_dom import _human_dom
from capabilities.human_dom._human_dom import HumanDomCapability


class FakeMcp:
    def __init__(self): self.tools = {}
    def tool(self, fn): self.tools[fn.__name__] = fn; return fn   # 捕获原 async fn


def _tools(bridge, tap=None, fill=None):
    cap = HumanDomCapability(bridge, tap_fn=tap or (lambda x, y: None), fill_fn=fill or (lambda s: None))
    m = FakeMcp(); cap.register(m); return m.tools


def test_locate_omitted_resolves_operator_and_marks(monkeypatch):
    async def fake_resolve(bridge, q, css=None, max_results=10, profile_id="default", timeout=3.0):
        fake_resolve.pid = profile_id
        return {"ok": True, "candidates": [{"text": "x", "center": [10, 20], "box": [0, 0, 1, 1]}]}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    tools = _tools(_FakeBridge("op-aaa"))
    r = asyncio.run(tools["human_dom_locate"]("q"))              # 省略 profile
    assert r["ok"] and r["resolved_profile"] == "op-aaa"        # 解析到 operator + 可观测
    assert fake_resolve.pid == "op-aaa"                          # 真的用 operator 去 locate


def test_tap_omitted_resolves_operator_and_marks(monkeypatch):
    async def fake_resolve(bridge, q, css=None, profile_id="default", timeout=3.0):
        return {"ok": True, "candidates": [{"center": [30, 40]}]}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    taps = []
    tools = _tools(_FakeBridge("op-bbb"), tap=lambda x, y: taps.append((x, y)))
    r = asyncio.run(tools["human_dom_tap"]("q"))
    assert r["ok"] and r["tapped"] == [30, 40] and r["resolved_profile"] == "op-bbb"
    assert taps == [(30, 40)]
