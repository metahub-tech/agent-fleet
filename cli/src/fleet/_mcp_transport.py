"""MCP streamable-http 传输的加载器（兼容 SDK 1.x / 2.x）。

1.x: ``mcp.client.streamable_http.streamablehttp_client``
2.x: ``mcp.client.streamable_http.streamable_http_client``（带下划线）

两者接受同一个 URL，返回的上下文管理器都是 ``(read, write, ...)`` 元组，
所以调用方统一按 ``streams[0] / streams[1]`` 解包即可。
"""
from __future__ import annotations

from typing import Any, Optional


def load_transport() -> Optional[Any]:
    """返回可用的 streamable-http 连接器；两个名字都拿不到时返回 ``None``。"""
    try:                                   # 1.x
        from mcp.client.streamable_http import streamablehttp_client as _t
        return _t
    except Exception:
        pass
    try:                                   # 2.x
        from mcp.client.streamable_http import streamable_http_client as _t
        return _t
    except Exception:
        return None


def require_transport() -> Any:
    """同 :func:`load_transport`，但拿不到时抛出带安装提示的 RuntimeError。"""
    transport = load_transport()
    if transport is None:
        raise RuntimeError(
            'MCP client SDK not available. Install it (`pip install "mcp<2"` or '
            '`pip install mcp`) in the environment that runs this command.'
        )
    return transport
