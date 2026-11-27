"""MCP 客户端小工具：**只做"拿结果"，不做判定**。

为什么抽出来：三个验收脚本（`smoke_ops` / `smoke_devtools` / `smoke_lease`）各自实现了
几乎相同的两件事，而 `probe_multi.py` 又需要第三份：

1. **payload 归一化** —— FastMCP 对返回 `list[...]` 的工具会给结构化内容包一层
   `{"result": [...]}`，老客户端还会拿到纯 text content。不同 SDK 版本字段名也不同
   （`structuredContent` / `structured_content`）。归一化逻辑必须只有一份，否则三个脚本
   会对同一台设备给出不同读数；
2. **streamable-http 连接器** —— MCP SDK 1.x 叫 `streamablehttp_client`，2.x 改成
   `streamable_http_client`（带下划线）。旧写法会在只装了 2.x 的环境里直接报
   "MCP client SDK not available"。

这些脚本都是**直接运行**的（`python scripts/smoke_ops.py`），所以同目录 import 可用；
`scripts/tests` 里通过 `import smoke_ops` 访问，仍然可用（各脚本保留同名兼容别名）。

⚠️ **三条输出契约（改这里会同时影响三条验收脚本，改前先读）**：

| 情形 | 归一化结果 | 谁依赖它 |
|---|---|---|
| 结构化内容是 dict | 原样返回 | 三者都用（`ok`/`reason` 直接读字段） |
| 结构化内容是非 dict（如 list） | 调用方包成 `{"_value": …}` | `smoke_ops` / `smoke_devtools` / `smoke_lease` |
| 只有 text 且能 `json.loads` | 返回解析值 | 同上 |
| 只有 text 且不能解析 | `{"_raw": text}` | 同上（**不静默丢内容**，便于人看现场） |
| 完全没有内容 | `[]`（调用方按空处理成 `{}`） | 同上 |

这里的"顺手简化"（比如把 `_raw` 改成抛异常、或把 `_value` 拆平）会改变三份验收脚本的
判定语义，而不是只改一个工具函数——请当成**跨脚本契约**对待。
"""
from __future__ import annotations

import json
from typing import Any, Optional


def payload_of(result: Any) -> Any:
    """把 MCP 的 `CallToolResult` 归一成 Python 值。

    优先级：``structuredContent`` → ``structured_content``（SDK v2 改名）→ 逐个 text part
    尝试 ``json.loads``。**单条 text** 返回解析值；多条返回列表；纯文本解析失败时包成
    ``{"_raw": text}``（让调用方仍能看到原始内容，而不是静默丢掉）。
    """
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    parts = []
    for block in (getattr(result, "content", None) or []):
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            parts.append(json.loads(text))
        except Exception:
            parts.append({"_raw": text})
    if len(parts) == 1:
        return parts[0]
    return parts


def load_transport() -> Optional[Any]:
    """返回 streamable-http 连接器；两个 SDK 版本的名字都试一遍，都拿不到时返回 None。"""
    try:
        from mcp.client.streamable_http import streamablehttp_client as _t   # 1.x
        return _t
    except Exception:
        pass
    try:
        from mcp.client.streamable_http import streamable_http_client as _t  # 2.x
        return _t
    except Exception:
        return None


#: 连接器缺失时给用户的提示（避免把环境问题读成设备问题）
TRANSPORT_HINT = (
    'MCP client SDK not available. Install it in the environment that runs this '
    'command: `pip install "mcp<2"` (1.x) or `pip install mcp` (2.x).'
)
