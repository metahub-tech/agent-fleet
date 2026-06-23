import asyncio, json, sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capabilities"))
from human_dom._bridge import DomBridge

class FakeWS:
    def __init__(self, incoming): self.incoming = list(incoming); self.sent = []
    async def send_json(self, m): self.sent.append(m)
    async def receive_json(self):
        if not self.incoming: raise asyncio.CancelledError()
        return self.incoming.pop(0)

def test_auth_rejects_wrong_token():
    b = DomBridge(token="secret")
    assert b.check_auth({"token": "nope"}) is False
    assert b.check_auth({"token": "secret"}) is True

def test_locate_dispatches_to_active_client_and_returns_reply():
    b = DomBridge(token="")
    reply = {"id": 1, "ok": True, "candidates": [], "viewport": {}}
    ws = FakeWS([reply])
    b.register(ws, tab_id="t1", url="https://x", active=True)
    out = asyncio.run(b.locate("发布", timeout=1.0))
    assert ws.sent[0]["op"] == "locate" and ws.sent[0]["query"] == "发布"
    assert out["ok"] is True

def test_locate_no_active_client_raises_timeout():
    b = DomBridge(token="")
    import pytest
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
