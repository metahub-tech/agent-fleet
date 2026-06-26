"""生成某 profile 专属的 human_dom 扩展目录(烤入 port+profile_id)+ meta.json。"""
from __future__ import annotations
import json, shutil
from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parent / "extension"

def prepare_extension(out_dir: str, bridge_port: int, profile_id: str, template_dir=None) -> str:
    tpl = Path(template_dir) if template_dir else _TEMPLATE
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(tpl, out)
    cjs = out / "content.js"
    # 必须显式 utf-8: content.js 含中文注释, Windows 默认 GBK 编码读会 UnicodeDecodeError(真机踩过)。
    s = cjs.read_text(encoding="utf-8")
    s = s.replace("__AF_PORT__", str(int(bridge_port)))
    # 用 json.dumps 替换整个带引号的占位符 -> 合法 JS 字符串字面量,
    # 避免 profile_id 含双引号/反斜杠时破坏 content.js 语法。
    s = s.replace('"__AF_PROFILE_ID__"', json.dumps(profile_id))
    cjs.write_text(s, encoding="utf-8")
    baked = cjs.read_text(encoding="utf-8")
    assert "__AF_PORT__" not in baked and "__AF_PROFILE_ID__" not in baked, \
        "prepare_extension: 占位未完全替换(模板格式变了?)"
    (out / "meta.json").write_text(json.dumps({"profile_id": profile_id, "bridge_port": int(bridge_port)}), encoding="utf-8")
    return str(out)
