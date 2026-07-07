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
