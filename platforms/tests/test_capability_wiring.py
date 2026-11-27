"""能力接线契约：server 里 `_cap_registry.add(X(...))` 用到的 X 必须真的被 import。

为什么值得一个门禁：能力模块是**导入期**注册的，漏一个 import 不会在测试里报错
（测试通常不 import 真 server，因为要 pywinauto/pyautogui），但真机启动时会
`NameError` → 整个设备桥起不来、所有 agent 掉线。这类错误只能靠静态检查兜住。

本测试只读源码（ast），任何平台可跑。
"""
import ast
from pathlib import Path

import pytest

PLATFORMS_DIR = Path(__file__).resolve().parent.parent
SERVERS = sorted(PLATFORMS_DIR.glob("*/server/*_mcp.py"))


def _imported_capability_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "capabilities":
            names.update(alias.name for alias in node.names)
    return names


def _registered_names(tree: ast.Module) -> list[str]:
    """收集 `_cap_registry.add(<Name>(...))` 里的 Name。"""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add":
            continue
        owner = func.value
        if not (isinstance(owner, ast.Name) and owner.id == "_cap_registry"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            found.append(arg.func.id)
    return found


@pytest.mark.parametrize("server", SERVERS, ids=[p.parent.parent.name for p in SERVERS])
def test_registered_capabilities_are_imported(server: Path):
    tree = ast.parse(server.read_text(encoding="utf-8"))
    imported = _imported_capability_names(tree)
    registered = _registered_names(tree)
    assert registered, f"{server.name}: no _cap_registry.add(...) calls found — wiring changed?"
    missing = sorted(set(registered) - imported)
    assert not missing, (
        f"{server.name} 注册了未导入的能力类 {missing}：真机启动会 NameError，"
        "请在 `from capabilities import (...)` 里补上。"
    )


@pytest.mark.parametrize("server", SERVERS, ids=[p.parent.parent.name for p in SERVERS])
def test_every_imported_capability_is_added(server: Path):
    """反向：import 了但没 add 的能力（写好了却没接上）也要可见。"""
    tree = ast.parse(server.read_text(encoding="utf-8"))
    imported = {
        n for n in _imported_capability_names(tree)
        if n.endswith("Capability") and n not in {"CapabilityRegistry"}
    }
    registered = set(_registered_names(tree))
    unused = sorted(imported - registered)
    assert not unused, (
        f"{server.name} 导入了能力类但从未 add：{unused}（要么接上，要么删掉 import）"
    )
