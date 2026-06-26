import asyncio, sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capabilities"))
from human_dom._locate import resolve_locate

class FakeBridge:
    def __init__(self, reply): self._reply = reply
    async def locate(self, query, css=None, max_results=10, profile_id="default", timeout=3.0): return self._reply

GEOM = {"screenX":0,"screenY":0,"innerW":1000,"innerH":900,"outerW":1000,"outerH":900,"dpr":1,"scrollX":0,"scrollY":0}

def test_hit_maps_candidates_to_screen():
    reply = {"ok": True, "viewport": GEOM, "candidates": [
        {"text":"发布","role":"button","rectViewport":{"left":10,"top":20,"width":40,"height":10},"visible":True,"clickable":True}]}
    out = asyncio.run(resolve_locate(FakeBridge(reply), "发布"))
    assert out["ok"] is True
    assert out["candidates"][0]["center"] == [30.0, 25.0]
    assert out["candidates"][0]["text"] == "发布"

def test_miss_returns_dom_sample_and_fallback_hint():
    reply = {"ok": False, "viewport": GEOM, "dom_candidates": ["登录","注册","首页"]}
    out = asyncio.run(resolve_locate(FakeBridge(reply), "发布"))
    assert out["ok"] is False
    assert out["dom_sample"] == ["登录","注册","首页"]
    assert out["suggest"] == "vision_locate"

def test_bridge_no_client_returns_structured_error():
    class NoClient:
        async def locate(self, *a, **k): raise TimeoutError("no active tab")
    out = asyncio.run(resolve_locate(NoClient(), "发布"))
    assert out["ok"] is False and out["reason"] == "no_tab_for_profile"
    assert out["profile"] == "default"
