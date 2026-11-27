"""运行时工具数（`list_capabilities().payload()`）与文档口径一致。

为什么值得单测：文档里的"固定工具数"是人手改的，`extract_mcp_tools` 只数 AST，
**真正对外的是什么**只有运行时注册表知道。Android / iOS 的 server 在 Linux 上
（`ATB_ANDROID_ADB=/bin/true`）可以 import，于是这两端的数字可以**真跑一次**核对。

Windows / macOS 依赖 pywinauto / pyobjc，Linux 上导入失败，仍由
`scripts/gen_docs.py --check` 的 AST 口径兜（两者相加才是完整核对）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: 与各平台 README 的「固定工具数」口径一致（core + list_capabilities + 本仓库实现的可选能力）
EXPECTED = {"android": 33, "ios": 32}


def _load(platform: str):
    server_dir = REPO / "platforms" / platform / "server"
    pool = [
        str(REPO / "platforms" / "common"),
        str(server_dir),
        str(REPO / "platforms"),
    ]
    for p in pool:
        if p not in sys.path:
            sys.path.insert(0, p)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("ATB_ANDROID_ADB", "/bin/true")
    spec = importlib.util.spec_from_file_location(
        f"{platform}_device_mcp_counts", server_dir / f"{platform}_device_mcp.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, monkeypatch


@pytest.mark.parametrize("platform", sorted(EXPECTED))
def test_runtime_tool_count_matches_docs(platform):
    module, monkeypatch = _load(platform)
    try:
        payload = asyncio.run(module._cap_registry.payload(module.mcp))
    finally:
        monkeypatch.undo()
    caps = payload["capabilities"]
    assert len(caps) == 1 and caps[0]["id"] == "core", f"{platform}: 只有 core 能力时不该出现别的条目"
    core_tools = caps[0]["tools"]
    assert len(core_tools) == EXPECTED[platform], (
        f"{platform}: 运行时 core 工具数 {len(core_tools)} ≠ README 的 {EXPECTED[platform]}"
        "（改工具后请同步 README 与 gen_docs 口径）"
    )
    assert "list_capabilities" in core_tools
    assert len(set(core_tools)) == len(core_tools), f"{platform}: 存在重复工具名"
