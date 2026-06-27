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
