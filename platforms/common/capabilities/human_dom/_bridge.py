"""human_dom 本地桥: content script 直连的 WS 客户端注册表 + locate 派发 + WS 认证。
绑 127.0.0.1; WS 不经 BearerAuthMiddleware, 首帧 {type:'auth',token} 自校验。"""
from __future__ import annotations
import asyncio, hmac, itertools

class DomBridge:
    def __init__(self, token: str = ""):
        self._token = token or ""
        self._clients = []          # [{ws, tab_id, url, active}]
        self._ids = itertools.count(1)
        self._pending = {}          # id -> Future (2A 收口用)

    def check_auth(self, first_frame: dict) -> bool:
        if not self._token: return True
        return hmac.compare_digest(str(first_frame.get("token","")), self._token)

    def register(self, ws, tab_id, url, active):
        self._clients.append({"ws":ws,"tab_id":tab_id,"url":url,"active":active})
    def unregister(self, ws):
        self._clients = [c for c in self._clients if c["ws"] is not ws]

    def _active(self):
        for c in self._clients:
            if c["active"]: return c
        return self._clients[0] if self._clients else None

    async def locate(self, query, css=None, max_results=10, timeout=3.0) -> dict:
        deadline = timeout
        while self._active() is None and deadline > 0:
            await asyncio.sleep(0.3); deadline -= 0.3
        c = self._active()
        if c is None: raise TimeoutError("no active tab")
        rid = next(self._ids)
        await c["ws"].send_json({"id":rid,"op":"locate","query":query,"css":css,"max_results":max_results})
        return await asyncio.wait_for(self._fulfill(c["ws"], rid), timeout=max(deadline,1.0))

    async def _fulfill(self, ws, rid):
        # 简化版(2A 收口为按 id 配对 future): 直接读该 ws 下一条 reply
        return await ws.receive_json()

def make_ws_route(bridge: "DomBridge"):
    from starlette.websockets import WebSocket
    async def handler(ws: "WebSocket"):
        await ws.accept()
        first = await ws.receive_json()
        if not bridge.check_auth(first):
            await ws.close(code=4401); return
        bridge.register(ws, first.get("tab_id"), first.get("url"), first.get("active", True))
        try:
            while True:
                await ws.receive_json()
        except Exception:
            pass
        finally:
            bridge.unregister(ws)
    return ("/dom-bridge", handler)
