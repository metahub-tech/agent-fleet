"""跨平台契约：四个平台的**运行时** core 工具集必须都包含 Universal Tool Set。

`docs/architecture.md` 的「工具公约」写着这些工具"✓ all"，但在本轮之前**没有任何测试**
验证过这句话——四个 server 各自演化，很容易某一端少一个（历史 bug 就是 android/ios
没有 `run_actions` / `wait_for`）。

做法：用桩把四个 server 都在 Linux 上 import（`_win_stubs` / `_mac_stubs`，
Android/iOS 只要有假 adb 就能导入），读 `list_capabilities()` 的**运行时**清单。
这样断言的是"对外真正注册了什么"，而不是 AST 里写了什么。
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

REPO = pathlib.Path(__file__).resolve().parents[2]

#: `docs/architecture.md` 标 "✓ all" 的工具（跨平台最小公约）
UNIVERSAL = (
    "get_screen_size", "take_screenshot",
    "dump_ui", "find_elements", "tap_element",
    "tap", "swipe", "type_text", "press_key",
    "launch_app", "terminate_app", "current_app",
    "acquire", "release", "get_status", "list_devices",
    "set_default_device", "get_default_device",
    "list_capabilities",
    # 2026-11 新增的编排原语，四平台同语义
    "run_actions", "wait_for",
)

_MODULES: dict[str, object] = {}


def _load(platform: str):
    if platform in _MODULES:
        return _MODULES[platform]
    if platform == "windows":
        from _win_stubs import load_win_server
        module = load_win_server()
    elif platform == "macos":
        from _mac_stubs import load_mac_server
        module = load_mac_server()
    else:
        server_dir = REPO / "platforms" / platform / "server"
        for p in (str(REPO / "platforms" / "common"), str(server_dir), str(REPO / "platforms")):
            if p not in sys.path:
                sys.path.insert(0, p)
        monkey = pytest.MonkeyPatch()
        monkey.setenv("ATB_ANDROID_ADB", "/bin/true")
        spec = importlib.util.spec_from_file_location(
            f"{platform}_device_mcp_conformance", server_dir / f"{platform}_device_mcp.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        monkey.undo()
    _MODULES[platform] = module
    return module


def _core_tools(module) -> set[str]:
    payload = asyncio.run(module._cap_registry.payload(module.mcp))
    core = next(c for c in payload["capabilities"] if c["id"] == "core")
    return set(core["tools"])


@pytest.mark.parametrize("platform", ["windows", "macos", "android", "ios"])
def test_platform_exposes_universal_tool_set(platform):
    module = _load(platform)
    tools = _core_tools(module)
    missing = [t for t in UNIVERSAL if t not in tools]
    assert not missing, f"{platform}: 运行时缺少 Universal Tool Set 成员 {missing}"


@pytest.mark.parametrize("platform", ["windows", "macos", "android", "ios"])
def test_tool_names_are_unique(platform):
    module = _load(platform)
    payload = asyncio.run(module._cap_registry.payload(module.mcp))
    core = next(c for c in payload["capabilities"] if c["id"] == "core")["tools"]
    assert len(core) == len(set(core)), f"{platform}: core 里有重复工具名"
