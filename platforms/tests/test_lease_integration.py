"""租约（lease）端到端集成测试：真起一个 MCP HTTP server，真开两个 session。

价值：设备租约是这套系统最容易出事、也最容易"只在真机上才知道"的机制——操作员在真机
上两次被它挡住/被它驱动。此前只有 `scripts/smoke_lease.py` 能在**真设备**上验。

做法：用 `_win_stubs` 把 Windows server 的 OS 依赖换掉（`get_screen_size` 等返回假值），
然后在本地随机端口起一个真的 streamable-http MCP server，用官方 client 开两个独立
session，验证：

1. A `acquire` 成功；B `acquire` 被拒且 `current_holder` 是 A；
2. B 调 core 工具 → `{ok:false, reason:"device_leased"}`；
3. A 调 core 工具 → 成功，并刷新 `last_used`（auto-renew）；
4. A `release` 后 B 立刻可用。

局限：验证的是**租约状态机与中间件**，不是任何 OS 行为。
"""
from __future__ import annotations

import asyncio
import pathlib
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

REPO = pathlib.Path(__file__).resolve().parents[2]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server_url():
    from _win_stubs import load_win_server

    win = load_win_server()
    port = _free_port()

    # 注意：租约中间件是在 `main()` 里挂到 app 上的，直接 `mcp.run()` 会**绕过**它
    # （第一版就是这么写的，于是 B 的 core 调用被放行——集成测试当场抓到）。
    # 这里复用 `main()` 的同一条挂载路径，只把 transport/端口换成本地。
    from _lease_gate import LeaseGate

    win.mcp.add_middleware(LeaseGate(win._state_registry,
                                    serial_for=lambda _ctx, _args: win._SERIAL))

    def serve():
        try:
            win.mcp.run(transport="http", host="127.0.0.1", port=port, show_banner=False)
        except Exception:  # pragma: no cover - server shutdown at process exit
            pass

    threading.Thread(target=serve, daemon=True).start()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover
        pytest.skip("stubbed MCP server did not start")
    return f"http://127.0.0.1:{port}/mcp"


def _transport():
    try:
        from mcp.client.streamable_http import streamablehttp_client as t   # 1.x
        return t
    except Exception:
        from mcp.client.streamable_http import streamable_http_client as t  # 2.x
        return t


def _payload(result):
    content = getattr(result, "structuredContent", None)
    if isinstance(content, dict):
        return content
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            import json
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}
    return {}


async def _run_lease_flow(url: str) -> dict:
    from mcp import ClientSession

    transport = _transport()

    async def session_call(session, name, args=None):
        return _payload(await session.call_tool(name, args or {}))

    async with transport(url) as streams_a:
        async with ClientSession(streams_a[0], streams_a[1]) as a:
            await a.initialize()
            a_acquire = await session_call(a, "acquire", {"holder_name": "integ-A"})
            before = (await session_call(a, "get_status", {})).get("last_used_at")
            await asyncio.sleep(0.01)          # 让时间戳有机会前进
            a_call = await session_call(a, "get_screen_size", {})
            a_status = await session_call(a, "get_status", {})

            async with transport(url) as streams_b:
                async with ClientSession(streams_b[0], streams_b[1]) as b:
                    await b.initialize()
                    b_acquire = await session_call(b, "acquire", {"holder_name": "integ-B"})
                    b_call = await session_call(b, "get_screen_size", {})

            a_release = await session_call(a, "release", {"holder_name": "integ-A"})

            async with transport(url) as streams_c:
                async with ClientSession(streams_c[0], streams_c[1]) as c:
                    await c.initialize()
                    c_acquire = await session_call(c, "acquire", {"holder_name": "integ-C"})
                    c_call = await session_call(c, "get_screen_size", {})
                    await session_call(c, "release", {"holder_name": "integ-C"})

    return {
        "a_acquire": a_acquire, "a_call": a_call, "a_status": a_status,
        "b_acquire": b_acquire, "b_call": b_call,
        "a_release": a_release, "c_acquire": c_acquire, "c_call": c_call,
        "before_last_used": before, "after_last_used": a_status.get("last_used_at"),
    }


def test_lease_is_enforced_across_sessions(server_url):
    out = asyncio.run(asyncio.wait_for(_run_lease_flow(server_url), timeout=60))

    assert out["a_acquire"].get("acquired") is True, out["a_acquire"]
    assert "width" in out["a_call"] and "height" in out["a_call"], out["a_call"]
    assert out["a_status"].get("holder") == "integ-A", out["a_status"]

    assert out["b_acquire"].get("acquired") is False, out["b_acquire"]
    assert out["b_acquire"].get("current_holder") == "integ-A", out["b_acquire"]

    assert out["b_call"].get("ok") is False, out["b_call"]
    assert out["b_call"].get("reason") == "device_leased", out["b_call"]

    assert out["a_release"].get("released") is True, out["a_release"]
    assert out["c_acquire"].get("acquired") is True, out["c_acquire"]
    assert "width" in out["c_call"] and "height" in out["c_call"], out["c_call"]


def test_discovery_and_structured_errors_over_mcp(server_url):
    """再验两条"通过真实 MCP 往返"的性质：

    1. `list_capabilities` 可调用且结构正确（这是"这台设备能干什么"的唯一运行时口径）；
    2. 非法参数返回**结构化**结果而不是把连接打挂（`wait_for(kind="bogus")`）。
    """
    async def flow(url):
        from mcp import ClientSession

        transport = _transport()
        async with transport(url) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                caps = _payload(await s.call_tool("list_capabilities", {}))
                bad = _payload(await s.call_tool("wait_for", {"kind": "bogus", "target": "x"}))
                screens = _payload(await s.call_tool("get_screen_size", {}))
                return caps, bad, screens

    caps, bad, screens = asyncio.run(asyncio.wait_for(flow(server_url), timeout=60))

    assert isinstance(caps.get("capabilities"), list) and caps["capabilities"], caps
    core = next(c for c in caps["capabilities"] if c["id"] == "core")
    assert "list_capabilities" in core["tools"]
    assert "wait_for" in core["tools"]

    assert bad.get("ok") is False and bad.get("reason") == "invalid_kind", bad
    assert "allowed_kinds" in bad

    # 服务仍然健康（错误没有把连接/进程打挂）
    assert "width" in screens and "height" in screens, screens


def test_run_actions_over_mcp(server_url, monkeypatch):
    """批量动作走完整 MCP 往返：参数校验收、顺序执行、失败短路。

    server 与测试在**同一进程**，所以可以直接替换工具函数来观察调用顺序
    （不必真去点鼠标）。
    """
    from _win_stubs import load_win_server

    win = load_win_server()
    calls = []

    def fake_tap(x=None, y=None, **kwargs):
        calls.append((x, y))
        return {"ok": True}

    monkeypatch.setattr(win, "tap", fake_tap)

    async def flow(url):
        from mcp import ClientSession

        transport = _transport()
        async with transport(url) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                ok_batch = _payload(await s.call_tool("run_actions", {"steps": [
                    {"tool": "tap", "args": {"x": 11, "y": 22}},
                    {"tool": "tap", "args": {"x": 33, "y": 44}},
                ]}))
                bad_batch = _payload(await s.call_tool("run_actions", {"steps": [
                    {"tool": "file_get", "args": {"path": "x"}},
                ]}))
                return ok_batch, bad_batch

    ok_batch, bad_batch = asyncio.run(asyncio.wait_for(flow(server_url), timeout=60))

    assert ok_batch.get("ok") is True and ok_batch.get("completed") == 2, ok_batch
    assert calls == [(11, 22), (33, 44)], calls

    # `file_get` 被刻意排除在白名单外（4 MiB base64 会灌爆批量响应）
    assert bad_batch.get("ok") is False and bad_batch.get("reason") == "invalid_steps", bad_batch
    assert "file_get" not in bad_batch.get("allowed_tools", [])


def test_wait_for_over_mcp_reports_the_right_reason(server_url, monkeypatch):
    """`wait_for` 的三种结果在**协议层**上是否如实（这是 agent 唯一能看到的东西）：

    * 元素不存在但探测正常 → `timeout`
    * 探测本身报错 → `probe_failed`（不是 timeout，语义不同）
    * `text_gone` 且本来就不在 → 立即成功
    """
    from _win_stubs import load_win_server

    win = load_win_server()

    def absent(*a, **k):
        return {"ok": True, "total_matched": 0, "elements": []}

    async def flow(url):
        from mcp import ClientSession

        transport = _transport()
        async with transport(url) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()

                monkeypatch.setattr(win, "_win_find_elements", absent)
                timed_out = _payload(await s.call_tool(
                    "wait_for", {"kind": "text", "target": "不存在", "timeout_ms": 400}))
                gone = _payload(await s.call_tool(
                    "wait_for", {"kind": "text_gone", "target": "对话框", "timeout_ms": 2000}))

                def boom(*a, **k):
                    raise RuntimeError("UIA exploded")

                monkeypatch.setattr(win, "_win_find_elements", boom)
                failed = _payload(await s.call_tool(
                    "wait_for", {"kind": "text", "target": "x", "timeout_ms": 400}))
                return timed_out, gone, failed

    timed_out, gone, failed = asyncio.run(asyncio.wait_for(flow(server_url), timeout=60))

    assert timed_out.get("reason") == "timeout", timed_out
    assert timed_out.get("attempts", 0) >= 2, timed_out
    assert gone.get("ok") is True and gone.get("kind") == "text_gone", gone
    assert failed.get("reason") == "probe_failed", failed


def test_core_call_renews_the_lease(server_url):
    """设备调用必须刷新 `last_used_at`。

    这正是 `smoke_lease` 真机 11/12 的那条判据：它原先用 `idle_seconds == 0` 判断续租，
    慢调用后 idle 必然大于 0（`human_dom_status` 在本机要 ~4s），于是把**正常续租**判成失败。
    这里在进程内用真实 server 断言时间戳前进，不依赖设备。
    """
    out = asyncio.run(asyncio.wait_for(_run_lease_flow(server_url), timeout=60))
    before = out["before_last_used"]
    after = out["after_last_used"]
    assert before and after, out
    assert str(after) > str(before), f"last_used_at 没有前进：{before} -> {after}"
