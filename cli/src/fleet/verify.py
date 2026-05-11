from __future__ import annotations

import asyncio
import socket

from .types import VerifyResult


def probe_port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def probe_mcp_server(host: str, port: int) -> VerifyResult:
    """Probe an MCP streamable-http server. Returns VerifyResult with tool count."""
    if not probe_port_open(host, port):
        return VerifyResult(ok=False, error=f"port {port} on {host} not listening")
    url = f"http://{host}:{port}/mcp"
    try:
        tool_count = asyncio.run(_list_tools_count(url))
    except Exception as e:
        return VerifyResult(ok=False, error=f"MCP probe failed: {type(e).__name__}: {e}", details={"url": url})
    return VerifyResult(ok=True, tool_count=tool_count, details={"url": url})


async def _list_tools_count(url: str) -> int:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            return len(tools.tools)
