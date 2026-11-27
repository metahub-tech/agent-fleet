"""macOS server 的"兜底接线"静态契约测试（无 pyobjc，Linux 可跑）。

`platforms/macos/server/mac_device_mcp.py` 依赖 pyobjc / ApplicationServices，Linux 上
导入即失败。mac 对等能力（AX 预算、`wait_for`、`run_actions`）**没有任何真机执行记录**，
所以这里用 AST 断言关键结构仍然存在，防止它们被静默重构掉：

1. 三处 AX 遍历（`dump_ui` / `find_elements` / `inspect_window`）都必须走
   `_ax_walk_budgeted` —— 否则 mac 端会退回到"一次遍历卡死到底"；
2. `wait_for` 必须保留 `negate_probe`（`*_gone` 能力）且 allowed_kinds 含 `_gone`；
3. `run_actions` 的白名单不得包含安装 / 上传类工具（这些不该被批处理）。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

MAC_SERVER = pathlib.Path(__file__).resolve().parents[2] / "platforms" / "macos" / "server" / "mac_device_mcp.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(MAC_SERVER.read_text(encoding="utf-8"))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {MAC_SERVER.name}")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


@pytest.mark.parametrize("func_name", ["dump_ui", "_mac_find_elements", "list_ui_elements"])
def test_ax_walk_goes_through_budget(tree, func_name):
    """所有真正遍历 AX 树的地方都必须在预算包装里。

    注意 `find_elements` 是对外工具、内部转调 `_mac_find_elements`，所以断言后者。
    想加新的 AX 遍历工具时，记得也走 `_ax_walk_budgeted`，否则这条测试不会覆盖它。
    """
    func = _func(tree, func_name)
    assert "_ax_walk_budgeted" in _called_names(func), f"{func_name} 不再走 AX 预算包装"


def test_wait_for_keeps_gone_variant(tree):
    func = _func(tree, "wait_for")
    assert "negate_probe" in _called_names(func), "wait_for 的 *_gone 能力被移除"
    assert "_gone" in ast.unparse(func), "allowed_kinds 不再包含 *_gone"


def test_run_actions_excludes_install_and_upload():
    source = MAC_SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = _func(tree, "run_actions")
    assert "validate_steps" in _called_names(func), "批量执行不再做整体预校验"
    # 白名单常量里不应出现安装 / 上传类工具
    allowlist = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_MAC_BATCH_ALLOWLIST" for t in node.targets
        ):
            allowlist = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    assert allowlist, "_MAC_BATCH_ALLOWLIST 不存在"
    forbidden = {"install_app", "uninstall_app", "upload_to_photos", "upload_to_app"}
    assert not (set(allowlist) & forbidden), f"白名单混入了不该批处理的能力: {set(allowlist) & forbidden}"


def test_wait_for_text_probe_uses_shorter_ax_budget(tree):
    """等待场景的 AX 探测不能吃满整段预算（否则 10s 等待只采样 1-2 次）。"""
    func = _func(tree, "wait_for")
    source = ast.unparse(func)
    assert "WAIT_PROBE_BUDGET_S" in source, "wait_for 的 text 探测又用回整段 AX 预算"
    assert "budget_s=" in source, "find_elements 调用没有传 budget_s"


def test_ax_walk_accepts_optional_budget(tree):
    func = _func(tree, "_ax_walk_budgeted")
    args = [a.arg for a in func.args.args]
    assert "budget_s" in args, "_ax_walk_budgeted 不再接受 budget_s，等待场景无法缩短探测"
