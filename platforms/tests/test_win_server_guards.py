"""Windows server 的"兜底接线"静态契约测试（无 pywinauto，Linux 可跑）。

为什么要这种测试：`platforms/windows/server/win_device_mcp.py` 依赖 pywinauto / win32，
在 CI 的 Linux 上**导入即失败**，于是"异常兜底被删掉"这类回归没有任何用例能发现。
这里用 AST 断言**结构存在**，而不是断言行为：

1. `list_windows` 必须把 `run_with_timeout` 包在 `try` 里，并且有一个**宽泛**的
   `except Exception`（真机出现过裸 `OSError [Errno 22]`，只有超时兜底不够）；
2. `_resolve_uia_window` 必须用共享的 `is_ambiguous_error` / `ambiguous_window_payload`，
   否则又会退回到抛裸异常 `There are N elements that match the criteria`；
3. `wait_for` 必须支持 `*_gone`（`negate_probe` 出现），否则"等对话框消失"的能力会静默丢失。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

WIN_SERVER = pathlib.Path(__file__).resolve().parents[2] / "platforms" / "windows" / "server" / "win_device_mcp.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(WIN_SERVER.read_text(encoding="utf-8"))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {WIN_SERVER.name}")


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


def test_list_windows_catches_non_timeout_errors(tree):
    func = _func(tree, "list_windows")
    guards = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Try):
            continue
        body_calls = _called_names(ast.Module(body=node.body, type_ignores=[]))
        if "run_with_timeout" not in body_calls:
            continue
        for handler in node.handlers:
            type_name = ast.unparse(handler.type) if handler.type is not None else "bare"
            guards.append(type_name)
    assert guards, "list_windows 没有把 run_with_timeout 包在 try 里"
    assert any(g in ("Exception", "OSError", "BaseException") for g in guards), (
        f"list_windows 只兜了 {guards}；真机出现过裸 OSError [Errno 22]，需要宽泛兜底"
    )


def test_resolve_window_uses_shared_ambiguity_helpers(tree):
    func = _func(tree, "_resolve_uia_window")
    names = _called_names(func)
    assert "is_ambiguous_error" in names, "歧义识别被移除 → 又会抛裸异常"
    assert "ambiguous_window_payload" in names, "歧义载荷构造被移除 → 调用方拿不到结构化 reason"


def test_wait_for_supports_gone_variant(tree):
    func = _func(tree, "wait_for")
    names = _called_names(func)
    assert "negate_probe" in names, "wait_for 的 *_gone 能力被移除"
    # 允许的 kind 列表里应出现拼接出的 *_gone（源码里是 f"{k}_gone"）
    source = ast.unparse(func)
    assert "_gone" in source, "wait_for 的 allowed_kinds 不再包含 *_gone"


def test_list_windows_logs_slow_calls(tree):
    """慢调用必须留痕。

    真机出现过一次 `list_windows` 客户端观测 11.98s、但预算 8s 且既没超时也没异常——
    没有"完成了但很慢"这行日志，就永远分不清是服务端慢还是客户端/session 开销。
    """
    func = _func(tree, "list_windows")
    names = _called_names(func)
    assert "monotonic" in names, "list_windows 不再计时 → 慢调用无法归因"
    source = ast.unparse(func)
    assert "UIA_SLOW_LOG_S" in source, "慢调用阈值没被使用"
    assert "[uia] list_windows completed in" in source, "慢调用告警文案被移除"


def test_wait_for_text_probe_uses_shorter_budget(tree):
    """等待场景的单次探测不能吃满整段预算，否则 10s 的 wait 只采样 1-2 次。"""
    func = _func(tree, "wait_for")
    source = ast.unparse(func)
    assert "WAIT_PROBE_BUDGET_S" in source, "wait_for 的 text 探测又用回整段 UIA 预算"
    assert "budget_s=" in source, "find_elements 调用没有传 budget_s"
