"""桥 focus_state: 前台检查带外查(document.hasFocus 值)。旧扩展无 focused 键必须落 None(不 False)。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities", "human_dom"))
from _bridge import DomBridge


class _WS:  # 唯一身份用于 register/unregister 匹配
    pass


def _reg(b, profile_id, active, focused="__absent__"):
    ws = _WS()
    if focused == "__absent__":
        # 模拟旧扩展: 首帧不带 focused 键 → 走 register 默认
        b.register(ws, profile_id, tab_id="t", url="u", active=active)
    else:
        b.register(ws, profile_id, tab_id="t", url="u", active=active, focused=focused)
    return ws


def test_focused_true():
    b = DomBridge()
    _reg(b, "op-x", active=True, focused=True)
    assert b.focus_state("op-x") is True


def test_focused_false_not_none():
    b = DomBridge()
    _reg(b, "op-x", active=True, focused=False)
    assert b.focus_state("op-x") is False   # 连着且确定不聚焦 → False, 不能是 None


def test_no_client_is_none():
    b = DomBridge()
    assert b.focus_state("op-missing") is None


def test_old_extension_no_focused_key_is_none():
    b = DomBridge()
    _reg(b, "op-x", active=True)             # 旧扩展: 首帧无 focused → 存 None
    assert b.focus_state("op-x") is None     # 关键: None 而非 False (spec §6.4 ⑤)


def test_set_active_updates_focused():
    b = DomBridge()
    ws = _reg(b, "op-x", active=True, focused=False)
    b.set_active(ws, active=True, focused=True)
    assert b.focus_state("op-x") is True


def test_focused_does_not_break_active_dispatch():
    # 分离守卫: focused 存取不改 _active 的派发(仍按 active 选)
    b = DomBridge()
    _reg(b, "op-x", active=False, focused=True)
    c = _reg(b, "op-x", active=True, focused=False)
    assert b._active("op-x")["ws"] is c      # 选 active=True 那个, 与 focused 无关
