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
