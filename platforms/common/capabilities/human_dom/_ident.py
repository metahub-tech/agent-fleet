"""human_dom profile 标识规范化: install 与 locate 必须用同一套。"""
from __future__ import annotations
import os, re, hashlib
from _browser_lease import _resolve_profile

def human_dom_profile_id(profile_str: "str | None") -> str:
    s = (profile_str or "").strip()
    if not s:
        return "default"
    udd, _pdir, key = _resolve_profile(s)
    # 直接用 _resolve_profile 已规范化好的 key 做 hash, 保证 install 与 locate
    # 走同一套路径解析(含 profile_directory 维度), 不再自行二次 expanduser/realpath。
    h = hashlib.sha1(key.encode()).hexdigest()[:8]
    base = os.path.basename(udd.rstrip("/\\")) or "p"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:24] or "p"
    return f"{slug}-{h}"


def resolve_profile_id(bridge, profile_str: "str | None") -> str:
    """显式 profile → human_dom_profile_id(行为完全不变); 省略/纯空白 → 桥的活跃 operator profile,
    无则 "default"(保默认日常 Chrome 用例)。修 P6: 省略 profile 不再硬默认 default(错落无 tab 的
    default), 而继承当前活跃 operator(桥连接客户端=真活跃证据)。"""
    s = (profile_str or "").strip()
    if s:
        return human_dom_profile_id(s)
    op = bridge.active_operator_profile()
    return op if op else "default"
