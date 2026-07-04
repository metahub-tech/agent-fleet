import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._setup import prepare_extension, template_hash

def test_prepare_bakes_port_profile_and_meta(tmp_path):
    out = tmp_path / "ext"
    prepare_extension(str(out), bridge_port=8780, profile_id="wechat-ab12cd34")
    cjs = (out / "content.js").read_text()
    assert "const PORT = (8780" in cjs
    assert 'PROFILE_ID = ("wechat-ab12cd34"' in cjs
    assert "__AF_PORT__" not in cjs and "__AF_PROFILE_ID__" not in cjs
    assert (out / "manifest.json").exists()
    json.loads((out / "manifest.json").read_text())
    meta = json.loads((out / "meta.json").read_text())
    assert meta["profile_id"] == "wechat-ab12cd34" and meta["bridge_port"] == 8780
    # tpl_hash: content.js 模板 hash, 供 _ensure_human_dom_ext 识别模板改动重烤
    assert meta["tpl_hash"] and meta["tpl_hash"] == template_hash()

def test_template_hash_stable_nonempty():
    assert template_hash() and template_hash() == template_hash()  # 稳定、非空

def test_baked_content_reads_data_placeholder():
    # R1: 模板 content.js 的 visibleText 补读 data-placeholder / aria-placeholder(ProseMirror 占位)
    cjs = (Path(__file__).resolve().parent.parent
           / "capabilities/human_dom/extension/content.js").read_text(encoding="utf-8")
    assert "data-placeholder" in cjs and "aria-placeholder" in cjs
    # R3: 候选按 editable 排序(真编辑体 > 占位 widget)
    assert "isContentEditable" in cjs and "_editable" in cjs


def test_prepare_overwrites_existing_out_dir(tmp_path):
    out = tmp_path / "ext"
    out.mkdir()
    stale = out / "stale.txt"
    stale.write_text("old")
    prepare_extension(str(out), bridge_port=8780, profile_id="wechat-ab12cd34")
    assert not stale.exists()
    assert (out / "content.js").exists()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["bridge_port"] == 8780


def test_prepare_preserves_nonascii_utf8(tmp_path):
    # content.js 含中文注释; prepare_extension 必须显式 utf-8 读写
    # (Windows 默认 GBK 会 UnicodeDecodeError, 真机踩过)。验中文经 bake 后完好。
    out = tmp_path / "ext"
    prepare_extension(str(out), bridge_port=8779, profile_id="default")
    baked = (out / "content.js").read_text(encoding="utf-8")
    assert "只读" in baked  # 模板首行注释「只读铁律...」应原样保留


def test_prepare_escapes_profile_id_with_special_chars(tmp_path):
    out = tmp_path / "ext"
    pid = 'we"ird\\id'
    prepare_extension(str(out), bridge_port=8780, profile_id=pid)
    cjs = (out / "content.js").read_text()
    # content.js 仍是合法 JS: profile_id 被正确转义为字符串字面量
    assert json.dumps(pid) in cjs
    assert "__AF_PROFILE_ID__" not in cjs
    # meta.json 保留原始未转义值
    meta = json.loads((out / "meta.json").read_text())
    assert meta["profile_id"] == pid
