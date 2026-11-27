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

#: core 桶的工具数（AST core + 框架注入的 `list_capabilities`）。
#: 这个数与宿主平台无关，所以四端都能断言。
#: 注意：README 的"固定工具数"（win 57 / mac 53）还包含 devtools/human_browser/vision
#: 等可选能力，而它们在 Linux 宿主上会因 `applies_to(host_os)` 而**不注册**——
#: 所以这里只断言 core 桶，可选能力交给 `gen_docs` 的 AST 口径。
EXPECTED_CORE = {"windows": 49, "macos": 45, "android": 33, "ios": 32}


def _load(platform: str):
    if platform in ("windows", "macos"):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        if platform == "windows":
            from _win_stubs import load_win_server
            return load_win_server(), None
        from _mac_stubs import load_mac_server
        return load_mac_server(), None
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


@pytest.mark.parametrize("platform", sorted(EXPECTED_CORE))
def test_runtime_core_tool_count_matches_docs(platform):
    module, monkeypatch = _load(platform)
    try:
        payload = asyncio.run(module._cap_registry.payload(module.mcp))
    finally:
        if monkeypatch is not None:
            monkeypatch.undo()
    core = next(c for c in payload["capabilities"] if c["id"] == "core")
    core_tools = core["tools"]
    assert len(core_tools) == EXPECTED_CORE[platform], (
        f"{platform}: 运行时 core 工具数 {len(core_tools)} ≠ 文档的 {EXPECTED_CORE[platform]}"
        "（改工具后请同步平台 README 与 gen_docs 口径）"
    )
    assert "list_capabilities" in core_tools
    assert len(set(core_tools)) == len(core_tools), f"{platform}: 存在重复工具名"
