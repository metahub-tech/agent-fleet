"""Tests for scripts/gen_docs.py."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import gen_docs


def test_render_port_table_contains_all_manifest_ports():
    table = gen_docs.render_port_table()
    for port in (8766, 8767, 8768, 8769):
        assert str(port) in table, f"Port {port} missing from port table:\n{table}"
    # HarmonyOS planned row
    assert "8770" in table, f"Port 8770 (HarmonyOS planned) missing from port table:\n{table}"


def test_check_passes_on_fresh_docs():
    r = subprocess.run(
        [sys.executable, "scripts/gen_docs.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# --- 平台 README / setup guide 工具数门禁 ----------------------------------

def test_platform_doc_counts_are_clean_on_this_tree():
    assert gen_docs.check_platform_doc_counts() == []


@pytest.mark.parametrize("text,expected", [
    ("**固定工具数 57**（48 core + …）", "57"),
    ("固定工具数 51（42 core + …）", "51"),
    ("固定工具数 **55**", "55"),
])
def test_fixed_count_regex_handles_markdown(text, expected):
    assert gen_docs._FIXED_COUNT_RE.findall(text) == [expected]


@pytest.mark.parametrize("text,expected", [
    ("除上面 48 个 core 工具外，…", "48"),
    ("除上面 **42** 个 core 工具外", None),   # 加粗写法不受支持 → 不误报
])
def test_core_count_regex(text, expected):
    found = gen_docs._CORE_COUNT_RE.findall(text)
    assert (found[0] if found else None) == expected


def test_appendix_core_regex():
    assert gen_docs._APPENDIX_CORE_RE.findall("### 附录 A · core 工具（48 个）") == ["48"]
    assert gen_docs._APPENDIX_CORE_RE.findall("### core 工具（43 个）") == ["43"]


# --- CHANGELOG 结构门禁（仅 [Unreleased]）---------------------------------

def test_changelog_unreleased_extracts_only_that_section():
    text = "# Log\n\n## [Unreleased]\n\n### 新增\n\n- a\n\n## [0.1.0] - x\n\n### 新增\n\n- b\n"
    section = gen_docs.changelog_unreleased(text)
    assert "- a" in section and "- b" not in section


def test_duplicate_subsection_headings_detects_and_dedupes():
    section = "### 新增\n- a\n\n### 修复\n- b\n\n### 新增\n- c\n"
    assert gen_docs.duplicate_subsection_headings(section) == ["新增"]
    assert gen_docs.duplicate_subsection_headings("### 新增\n- a\n") == []


def test_changelog_structure_is_clean_now():
    assert gen_docs.check_changelog_structure() == []


def test_changelog_gate_would_have_caught_the_regression():
    """反向验证：把 [Unreleased] 造出两个「新增」时就该报错。"""
    text = "## [Unreleased]\n\n### 新增\n- a\n\n### 新增\n- b\n\n## [0.1.0]\n"
    section = gen_docs.changelog_unreleased(text)
    assert gen_docs.duplicate_subsection_headings(section) == ["新增"]
