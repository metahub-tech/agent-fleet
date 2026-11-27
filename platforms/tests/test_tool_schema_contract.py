"""工具 schema 契约（运行时，四平台各跑一遍）。

agent 靠 `description` 与参数说明决定怎么调工具；空描述或参数漂移是**静默**的质量损失。
这里用四端都能在 Linux import 的条件，检查：

1. **每个 core 工具都有非空 description**（>= 15 字），且参数都带 `description`；
2. **编排原语的关键参数一致**：`wait_for` 必须有 `kind` / `target` / `timeout_ms`，
   `run_actions` 必须有 `steps` / `stop_on_error` / `delay_ms`；
3. `wait_for` 的 `kind` 说明里要提到 `_gone`（否则调用方不知道有这个能力）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

REPO = pathlib.Path(__file__).resolve().parents[2]
PLATFORMS = ("windows", "macos", "android", "ios")

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
            f"{platform}_device_mcp_schema", server_dir / f"{platform}_device_mcp.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        monkey.undo()
    _MODULES[platform] = module
    return module


def _tools(module) -> dict:
    return {t.name: t for t in asyncio.run(module.mcp.list_tools())}


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_tool_has_a_description(platform):
    tools = _tools(_load(platform))
    thin = {name: len(t.description or "") for name, t in tools.items()
            if len(t.description or "") < 15}
    assert not thin, f"{platform}: 这些工具缺描述或描述过短 {thin}"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_parameter_descriptions_are_present(platform):
    """参数没有 description 时，agent 只能靠猜 —— 尤其是 `window_title` 这种作用域参数。"""
    missing = []
    for name, tool in _tools(_load(platform)).items():
        for prop, spec in ((tool.parameters or {}).get("properties") or {}).items():
            if not (spec.get("description") or "").strip():
                missing.append(f"{name}.{prop}")
    assert not missing, f"{platform}: 参数缺 description: {missing[:8]}"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_orchestration_primitives_keep_their_contract(platform):
    tools = _tools(_load(platform))
    wait_for = tools["wait_for"].parameters or {}
    props = set((wait_for.get("properties") or {}))
    assert {"kind", "target", "timeout_ms"} <= props, f"{platform}: wait_for 参数漂移 {props}"
    assert wait_for.get("required") == ["kind"], f"{platform}: wait_for 必填项变了"

    run_actions = tools["run_actions"].parameters or {}
    props2 = set((run_actions.get("properties") or {}))
    assert {"steps", "stop_on_error", "delay_ms"} <= props2, f"{platform}: run_actions 参数漂移 {props2}"
    assert run_actions.get("required") == ["steps"], f"{platform}: run_actions 必填项变了"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_wait_for_kind_mentions_gone(platform):
    """`*_gone` 是新增能力；说明里不提，调用方就不会用。"""
    doc = ((_tools(_load(platform))["wait_for"]).parameters or {})
    kind_desc = ((doc.get("properties") or {}).get("kind") or {}).get("description", "")
    assert "_gone" in kind_desc, f"{platform}: wait_for 的 kind 说明里没有提到 *_gone"
