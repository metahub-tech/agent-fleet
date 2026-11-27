"""devtools 能力的「工具面 × 调用方文档」一致性契约。

devtools 是**可选能力**，在 Linux 上不会注册（`applies_to` 只认 win/mac），所以它的
工具名无法用运行时接口核对。这里从 `_devtools.py` 的 AST 取**实际注册的 4 个工具**，
再核对三处调用方文档都认识它们：

1. `platforms/common/skills/using-human-browser/SKILL.md`（agent 读的产品契约）；
2. `docs/platforms/windows.md`（平台附录）；
3. `docs/social-publishing-playbook.md`（社媒 SOP）。

反向也要查：文档里提到的 devtools 工具名不能是"源码里不存在的"（拼错或改名的残留）。
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DEVTOOLS = REPO / "platforms" / "common" / "capabilities" / "devtools" / "_devtools.py"

DOCS = {
    "skill": REPO / "platforms" / "common" / "skills" / "using-human-browser" / "SKILL.md",
    "windows.md": REPO / "docs" / "platforms" / "windows.md",
    "playbook": REPO / "docs" / "social-publishing-playbook.md",
}

#: 文档里可能出现的、但不是工具的 devtools 概念词（避免误判）
NON_TOOL_WORDS = {"devtools", "cdp", "chrome", "profile", "visibility"}


def registered_tools() -> set[str]:
    tree = ast.parse(DEVTOOLS.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Attribute) and dec.attr == "tool":
                    names.add(node.name)
    return names


def test_devtools_registers_the_documented_four():
    tools = registered_tools()
    assert tools == {"cdp_port", "list_tabs", "activate_tab", "eval_in_profile"}, (
        f"devtools 工具面变了：{sorted(tools)}（文档与 skill 需要同步）"
    )


@pytest.mark.parametrize("label", sorted(DOCS))
def test_every_devtools_tool_is_documented(label):
    doc = DOCS[label].read_text(encoding="utf-8")
    missing = [t for t in sorted(registered_tools()) if t not in doc]
    assert not missing, f"{DOCS[label].name} 没提到这些 devtools 工具: {missing}"


def test_docs_do_not_reference_phantom_devtools_tools():
    """文档里形如 `xxx_in_profile` / `cdp_xxx` / `list_tabs` 的名字都必须是真工具。"""
    tools = registered_tools() | NON_TOOL_WORDS
    # 只认**工具名**形态：`cdp_port` 精确匹配（`cdp_timeout` 之类是 reason 码，不是工具），
    # 外加 `*_in_profile` 与两个标签工具。
    pattern = re.compile(r"`(cdp_port|[a-z_]+_in_profile|list_tabs|activate_tab)`")
    phantom = {}
    for label, path in DOCS.items():
        text = path.read_text(encoding="utf-8")
        for name in set(pattern.findall(text)):
            if name not in tools:
                phantom.setdefault(label, set()).add(name)
    assert not phantom, f"文档引用了不存在的 devtools 工具: {phantom}"
