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
