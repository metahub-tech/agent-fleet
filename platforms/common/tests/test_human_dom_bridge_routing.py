import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._bridge import DomBridge

class FakeWS:
    def __init__(self): self.sent = []
    async def send_json(self, m): self.sent.append(m)

def test_active_scoped_to_profile():
    b = DomBridge()
    wa, wb = FakeWS(), FakeWS()
    b.register(wa, profile_id="A", tab_id="1", url="a", active=True)
    b.register(wb, profile_id="B", tab_id="2", url="b", active=True)
    assert b._active("A")["ws"] is wa
    assert b._active("B")["ws"] is wb
    assert b._active("C") is None

def test_locate_routes_to_requested_profile():
    b = DomBridge()
    wa, wb = FakeWS(), FakeWS()
    b.register(wa, profile_id="A", tab_id="1", url="a", active=True)
    b.register(wb, profile_id="B", tab_id="2", url="b", active=True)
    async def run():
        task = asyncio.create_task(b.locate("q", css=None, profile_id="B", timeout=1.0))
        await asyncio.sleep(0.05)
        assert len(wb.sent) == 1 and wb.sent[0]["op"] == "locate"
        assert wa.sent == []
        rid = wb.sent[0]["id"]
        b._deliver({"id": rid, "ok": True, "candidates": [], "viewport": {}})
        return await task
    res = asyncio.run(run())
    assert res["ok"] is True

def test_locate_no_profile_raises():
    import pytest
    b = DomBridge()
    with pytest.raises(Exception):
        asyncio.run(b.locate("q", css=None, profile_id="ZZZ", timeout=0.4))

def test_bridge_app_has_route():
    from capabilities.human_dom._bridge import make_bridge_app, DomBridge
    app = make_bridge_app(DomBridge())
    assert any(getattr(r, "path", None) == "/dom-bridge" for r in app.routes)


def test_deliver_uses_future_loop_call_soon_threadsafe():
    """跨线程加固单元验证: _pending 存 (fut, loop), _deliver 走 future 自己的
    loop.call_soon_threadsafe(从桥线程调也安全)。这里 mock loop 截获 call_soon_threadsafe,
    直接调度即视为'桥线程把 set_result 安全投回主 loop'。"""
    b = DomBridge()

    class _FakeLoop:
        def __init__(self): self.calls = []
        def call_soon_threadsafe(self, cb, *args):
            self.calls.append((cb, args)); cb(*args)   # 立即执行模拟投回主 loop

    floop = _FakeLoop()
    loop = asyncio.new_event_loop()
    fut = asyncio.Future(loop=loop)  # 不在本线程跑, 只验 set_result 经 call_soon_threadsafe
    b._pending[7] = (fut, floop)
    b._deliver({"id": 7, "ok": True, "candidates": []})
    assert len(floop.calls) == 1                          # 没直接 set_result, 而是经 call_soon_threadsafe
    assert fut.done() and fut.result()["ok"] is True
    assert 7 not in b._pending                            # 投递后从 _pending 摘除
    loop.close()


def test_deliver_on_cancelled_future_is_safe():
    """竞态加固: fut 在调度后、回调执行前被 cancel(wait_for 超时), _safe_set 回调内
    再判 done() → 不对 cancelled future set_result(否则 InvalidStateError)。
    这里模拟 call_soon_threadsafe 延迟执行: 先记下回调, cancel 掉 fut, 再触发回调。"""
    b = DomBridge()

    class _DeferLoop:
        def __init__(self): self.pending = []
        def call_soon_threadsafe(self, cb, *args): self.pending.append((cb, args))
        def flush(self):
            for cb, args in self.pending: cb(*args)

    floop = _DeferLoop()
    loop = asyncio.new_event_loop()
    fut = asyncio.Future(loop=loop)
    b._pending[8] = (fut, floop)
    b._deliver({"id": 8, "ok": True})   # 此刻只是把 _safe_set 排进 _DeferLoop, 未执行
    fut.cancel()                        # 模拟 wait_for 超时取消(调度后、回调前)
    floop.flush()                       # 触发 _safe_set: 必须因 done()=True 而跳过, 不抛
    assert fut.cancelled()
    loop.close()


def test_deliver_unknown_id_is_noop():
    """未知 id 的 reply 不应炸(无对应 pending)。"""
    b = DomBridge()
    b._deliver({"id": 999, "ok": True})   # 不抛即通过


def test_real_cross_thread_bridge_locate(monkeypatch):
    """真跨线程集成: run_bridge_loopback 起独立线程+独立 loop 跑真 WS server;
    主 loop 连真 websockets client 注册 tab, 再从主 loop 调 bridge.locate ——
    验证 ws.send_json 经 run_coroutine_threadsafe 投到桥 loop、reply 经
    _deliver→call_soon_threadsafe 跨线程 resolve 主 loop 的 future。"""
    import pytest
    websockets = pytest.importorskip("websockets")
    pytest.importorskip("uvicorn"); pytest.importorskip("starlette")
    import socket, time
    from capabilities.human_dom._bridge import DomBridge, run_bridge_loopback

    # 选一个空闲端口
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()

    bridge = DomBridge(token="")
    run_bridge_loopback(bridge, host="127.0.0.1", port=port)
    # 等桥线程把 server + _bridge_loop 起来
    for _ in range(50):
        if bridge._bridge_loop is not None:
            break
        time.sleep(0.05)
    assert bridge._bridge_loop is not None, "桥线程未在超时内存回 _bridge_loop"

    async def scenario():
        uri = f"ws://127.0.0.1:{port}/dom-bridge"
        # 重试连接, 等 uvicorn 真正起监听
        client = None
        for _ in range(50):
            try:
                client = await websockets.connect(uri)
                break
            except OSError:
                await asyncio.sleep(0.05)
        assert client is not None, "无法连上桥 WS server"
        async with client as ws:
            # 首帧 auth + 注册(active=True)
            await ws.send(json.dumps({"token": "", "profile_id": "default",
                                      "tab_id": "t1", "url": "x", "active": True}))
            # content script 侧循环: 收到 locate op → 回带同 id 的 reply
            async def responder():
                raw = await ws.recv()
                req = json.loads(raw)
                assert req["op"] == "locate" and req["query"] == "hello"
                await ws.send(json.dumps({"id": req["id"], "ok": True,
                                          "candidates": [{"x": 1}], "viewport": {"w": 100}}))
            resp_task = asyncio.create_task(responder())
            # 从主 loop 调 locate(跨线程发 ws + 跨线程 resolve future)
            res = await bridge.locate("hello", profile_id="default", timeout=5.0)
            await resp_task
            return res

    res = asyncio.run(scenario())
    assert res["ok"] is True and res["viewport"]["w"] == 100
    assert res["candidates"] == [{"x": 1}]
