"""R2(AgentHub #100): human_dom_fill 回读校验杀假成功。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom import _human_dom


def test_fill_snippet_strips_and_caps():
    assert _human_dom._fill_snippet("  标题ABC  ") == "标题ABC"
    assert _human_dom._fill_snippet("x" * 50, n=16) == "x" * 16
    assert _human_dom._fill_snippet("") == "" and _human_dom._fill_snippet("   ") == ""


def _patch_locate(monkeypatch, reply):
    async def fake(bridge, q, css=None, profile_id="default", timeout=3.0):
        fake.q = q
        return reply
    monkeypatch.setattr(_human_dom, "resolve_locate", fake)
    return fake


def test_verify_fill_true_when_filled_snippet_appears(monkeypatch):
    # 回读到某候选 visibleText 含【填入片段本身】→ 真落字
    _patch_locate(monkeypatch, {"ok": True, "candidates": [{"text": "前缀 填入内容ABC 后缀"}]})
    assert asyncio.run(_human_dom._verify_fill(None, "填入内容ABC", None, "p")) is True


def test_verify_fill_false_when_snippet_missing(monkeypatch):
    # 关键: 候选非空但【不含填入片段】(如空 ProseMirror 的占位串) → 判假成功
    _patch_locate(monkeypatch, {"ok": True, "candidates": [{"text": "从这里开始写正文"}]})
    assert asyncio.run(_human_dom._verify_fill(None, "填入内容ABC", None, "p")) is False


def test_verify_fill_false_when_locate_not_ok(monkeypatch):
    _patch_locate(monkeypatch, {"ok": False, "reason": "not_found"})
    assert asyncio.run(_human_dom._verify_fill(None, "填入内容ABC", None, "p")) is False


def test_verify_fill_empty_text_passes_without_locate(monkeypatch):
    fake = _patch_locate(monkeypatch, {"ok": True, "candidates": []})
    assert asyncio.run(_human_dom._verify_fill(None, "   ", None, "p")) is True
    assert not hasattr(fake, "q")  # 空串不 locate
