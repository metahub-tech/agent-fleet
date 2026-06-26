import asyncio, sys
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
