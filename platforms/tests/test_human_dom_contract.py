"""human_dom 能力的「文档事实 × 代码」一致性契约。

human_dom 是 **opt-in**：没有 `~/.fleet/human-dom-ready` 标记时工具根本不注册，所以
"代码里到底检查哪个路径、端口文件叫什么、注册几个工具"这些事实无法通过运行时验证。
但它们都是调用方按文档操作的依据（建错 marker = 工具永远不出现），因此用 AST/源码断言钉住。

对应文档：`platforms/common/skills/using-human-dom/SKILL.md` 的「两层启用模型」。
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
HUMAN_DOM = REPO / "platforms" / "common" / "capabilities" / "human_dom"


def _source(name: str) -> str:
    return (HUMAN_DOM / name).read_text(encoding="utf-8")


def test_marker_path_matches_docs():
    """文档写的是 `~/.fleet/human-dom-ready`，代码里**每一处**都必须用它。

    只断言"出现过"是抓不到改名的：源码里这个路径出现多次，改掉一处仍然能过
    （实测确认过）。
    """
    source = _source("_human_dom.py")
    # 后面不能再接 `-v2` 之类：用负向前瞻把"规范路径 + 额外后缀"区分开
    canonical = re.compile(r"~/\.fleet/human-dom-ready(?![-\w.])")
    assert canonical.search(source), "找不到规范 marker 路径"
    # 任何 `human-dom-ready` 出现处都必须正好是规范路径
    offenders = []
    for line in source.splitlines():
        if "human-dom-ready" not in line:
            continue
        if not canonical.search(line):
            offenders.append(line.strip())
    assert not offenders, f"出现非规范 marker 路径：{offenders}"


def test_port_file_naming_matches_docs():
    """端口文件名是 `~/.fleet/dom-bridge-<mcp_port>.port`（排障时按它找桥）。"""
    assert '~/.fleet/dom-bridge-{mcp_port}.port' in _source("_portfile.py")


def test_registers_five_tools():
    """`list_capabilities` 的 human_dom 分桶应是 5 个工具（README/文档按 5 写）。

    注意注册形态：这里是 `@mcp.tool` 直接挂在函数上（AST 里 decorator 是 `ast.Attribute`，
    func 才是 `mcp`），与 `@mcp.tool\ndef x()` 的写法等价；按 `@mcp.tool` 出现次数 + 
    `human_dom_*` 函数名一起核对，避免只数一边漏掉。
    """
    source = _source("_human_dom.py")
    tool_funcs = set(re.findall(r"def (human_dom_\w+)", source))
    # 断言**精确集合**而不只是数量：改名（status → state）同样要被抓到。
    assert tool_funcs == {
        "human_dom_locate", "human_dom_tap", "human_dom_fill",
        "human_dom_status", "human_dom_focused",
    }, f"human_dom 工具名变了：{sorted(tool_funcs)}"
    assert source.count("@mcp.tool") == 5, "装饰器数量与工具函数数量不一致"
    assert ast.parse(source).body  # 语法仍可解析


def test_skill_documents_the_marker_and_the_count():
    skill = (REPO / "platforms" / "common" / "skills" / "using-human-dom" / "SKILL.md").read_text(encoding="utf-8")
    assert "human-dom-ready" in skill
    assert "human_dom" in skill
