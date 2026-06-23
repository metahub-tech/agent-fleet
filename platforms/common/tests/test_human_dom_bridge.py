import asyncio, json, sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capabilities"))
from human_dom._bridge import DomBridge

class FakeWS:
    def __init__(self): self.sent = []
    async def send_json(self, m): self.sent.append(m)

def test_auth_rejects_wrong_token():
    b = DomBridge(token="secret")
    assert b.check_auth({"token": "nope"}) is False
    assert b.check_auth({"token": "secret"}) is True

def test_locate_pairs_reply_by_id():
    b = DomBridge(token="")
    ws = FakeWS(); b.register(ws, tab_id="t1", url="x", active=True)
    async def scenario():
        task = asyncio.create_task(b.locate("发布", timeout=2.0))
        await asyncio.sleep(0.05)          # 让 locate 发出请求、注册 pending
        rid = ws.sent[0]["id"]
        b._deliver({"id": rid, "ok": True, "candidates": [], "viewport": {}})
        return await task
    out = asyncio.run(scenario())
    assert ws.sent[0]["op"] == "locate" and ws.sent[0]["query"] == "发布" and out["ok"] is True

def test_concurrent_locates_get_their_own_reply():
    b = DomBridge(token="")
    ws = FakeWS(); b.register(ws, tab_id="t1", url="x", active=True)
    async def scenario():
        t1 = asyncio.create_task(b.locate("A", timeout=2.0))
        t2 = asyncio.create_task(b.locate("B", timeout=2.0))
        await asyncio.sleep(0.05)
        id1 = next(m["id"] for m in ws.sent if m["query"] == "A")
        id2 = next(m["id"] for m in ws.sent if m["query"] == "B")
        # 逆序投递，验证不串话
        b._deliver({"id": id2, "ok": True, "candidates": [], "viewport": {"tag": "B"}})
        b._deliver({"id": id1, "ok": True, "candidates": [], "viewport": {"tag": "A"}})
        return await t1, await t2
    r1, r2 = asyncio.run(scenario())
    assert r1["viewport"]["tag"] == "A" and r2["viewport"]["tag"] == "B"

def test_locate_no_active_client_raises_timeout():
    import pytest
    b = DomBridge(token="")
    with pytest.raises(TimeoutError):
        asyncio.run(b.locate("发布", timeout=0.2))

def test_run_bridge_loopback_binds_127(monkeypatch):
    import human_dom._bridge as br
    captured = {}
    class _Cfg:
        def __init__(self, app, host, port, **kw): captured["host"]=host; captured["port"]=port
    class _Srv:
        def __init__(self, cfg): ...
        async def serve(self): ...
    monkeypatch.setattr(br, "make_ws_route", lambda b: ("/dom-bridge", lambda ws: None))
    import uvicorn; monkeypatch.setattr(uvicorn, "Config", _Cfg); monkeypatch.setattr(uvicorn, "Server", _Srv)
    # 线程会起但 _Srv.serve 立即返回; 只断言 host
    br.run_bridge_loopback(object(), host="127.0.0.1", port=8779)
    import time; time.sleep(0.1)
    assert captured["host"] == "127.0.0.1" and captured["port"] == 8779
