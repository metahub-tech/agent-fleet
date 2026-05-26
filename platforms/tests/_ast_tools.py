"""Statically extract @mcp.tool function names + param names from a server file.

Never imports the module (win/mac/android servers can't import on Linux CI)."""
from __future__ import annotations

import ast
from pathlib import Path


def _is_mcp_tool(dec) -> bool:
    # matches @mcp.tool and @mcp.tool(...)
    node = dec.func if isinstance(dec, ast.Call) else dec
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "tool"
        and isinstance(node.value, ast.Name)
        and node.value.id == "mcp"
    )


def _param_names(fn) -> list[str]:
    a = fn.args
    return [p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)]


def extract_mcp_tools(path: str | Path) -> dict[str, list[str]]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_is_mcp_tool(d) for d in node.decorator_list):
                out[node.name] = _param_names(node)
    return out


def func_return_annotation(path: str | Path, func_name: str) -> str | None:
    """Source text of a top-level function's return annotation (e.g. 'dict',
    'str'), or None if the function is missing / has no annotation. AST-only —
    never imports the module (servers can't import on Linux CI)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return None if node.returns is None else ast.unparse(node.returns)
    return None
