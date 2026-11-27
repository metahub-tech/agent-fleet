"""`platforms/tests` 的环境提示（不跳过、不改变任何测试行为）。

为什么需要：这套测试要 import 四端 server 与 MCP client，缺依赖时会一次性冒出几十条
`ModuleNotFoundError`，很容易被误读成"代码坏了"。这里在 pytest 输出**顶部**先给一句
可执行的安装命令，让人第一眼就知道是环境问题。
"""
from __future__ import annotations

import importlib.util

#: 跑这套测试需要的第三方包（仓库没有根级 dev 依赖声明，只能在这里集中说明）
REQUIRED = ("pytest", "fastmcp", "psutil", "PIL", "pydantic", "mcp")

INSTALL_HINT = (
    'python -m pip install -q pytest "fastmcp>=2.3.2" psutil pillow "mcp[cli]" pydantic'
)


def _missing() -> list[str]:
    missing = []
    for name in REQUIRED:
        module = "PIL" if name == "PIL" else name
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def _message(missing: list[str]) -> str:
    return (
        "platforms/tests: 缺少依赖 " + ", ".join(missing) + " —— 后续失败多半是 "
        "ModuleNotFoundError（**环境问题，不是回归**）。装：\n  " + INSTALL_HINT
    )


def pytest_collection_modifyitems(session, config, items):  # noqa: ARG001
    """在收集阶段直接打印（`-q` 下 `pytest_report_header` 会被隐藏）。"""
    missing = _missing()
    if not missing:
        return
    message = _message(missing)
    reporter = config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(message)
    else:  # pragma: no cover - 非终端 runner
        print(message)
