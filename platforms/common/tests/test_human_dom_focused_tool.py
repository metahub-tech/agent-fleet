"""human_dom_focused: 带外前台检查工具。三态 true/false/None → reason 分类; 省略 profile 走 resolve。
纯 Python 本机可跑。运行: cd platforms/common && python3 -m pytest tests/test_human_dom_focused_tool.py -v"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._human_dom import HumanDomCapability


class FakeBridge:
    def __init__(self, focus_map, op=None):
        self._focus = focus_map            # profile_id -> bool|None
        self._op = op                      # active_operator_profile 返回值
        self._clients = []
    def active_operator_profile(self): return self._op
    def focus_state(self, pid): return self._focus.get(pid)


class FakeMcp:
    def __init__(self): self.tools = {}
    def tool(self, fn): self.tools[fn.__name__] = fn; return fn


def _focused_tool(focus_map, op=None):
    cap = HumanDomCapability(FakeBridge(focus_map, op), tap_fn=lambda x, y: None, fill_fn=lambda s: None)
    m = FakeMcp(); cap.register(m); return m.tools["human_dom_focused"]


def _run(coro): return asyncio.new_event_loop().run_until_complete(coro)


def test_focused_true_via_active_operator():
    tool = _focused_tool({"op-x": True}, op="op-x")
    r = _run(tool(profile=""))                 # 省略 → resolve 到活跃 operator op-x
    assert r["ok"] is True and r["focused"] is True and r["profile"] == "op-x" and r["reason"] == "focused"


def test_not_focused():
    tool = _focused_tool({"op-x": False}, op="op-x")
    r = _run(tool(profile=""))
    assert r["focused"] is False and r["reason"] == "not_focused"


def test_no_signal_none():
    tool = _focused_tool({"op-x": None}, op="op-x")
    r = _run(tool(profile=""))
    assert r["focused"] is None and r["reason"] == "no_signal"


def test_no_operator_falls_default_none():
    # 无 operator → resolve 到 "default"; focus_map 无 default → None
    tool = _focused_tool({}, op=None)
    r = _run(tool(profile=""))
    assert r["profile"] == "default" and r["focused"] is None and r["reason"] == "no_signal"
