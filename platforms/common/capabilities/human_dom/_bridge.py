"""human_dom 本地桥: content script 直连的 WS 客户端注册表 + locate 派发 + WS 认证。
绑 127.0.0.1; WS 不经 BearerAuthMiddleware, 首帧 {type:'auth',token} 自校验。"""
from __future__ import annotations
import asyncio, hmac, itertools

class DomBridge:
    def __init__(self, token: str = ""):
        self._token = token or ""
        self._clients = []          # [{ws, tab_id, url, active}]
        self._ids = itertools.count(1)
        self._pending = {}          # id -> Future

    def check_auth(self, first_frame: dict) -> bool:
        if not self._token: return True
        return hmac.compare_digest(str(first_frame.get("token","")), self._token)

    def register(self, ws, profile_id, tab_id, url, active):
        self._clients.append({"ws": ws, "profile_id": profile_id or "default",
                              "tab_id": tab_id, "url": url, "active": active})
    def unregister(self, ws):
        self._clients = [c for c in self._clients if c["ws"] is not ws]

    def set_active(self, ws, active):
        """content script 报前后台切换 → 更新该 client 的 active(修多 tab 派发)。"""
        for c in self._clients:
            if c["ws"] is ws:
                c["active"] = bool(active)

    def _active(self, profile_id):
        group = [c for c in list(self._clients) if c["profile_id"] == profile_id]
        for c in group:
            if c["active"]:
                return c
        return group[0] if group else None

    def _deliver(self, reply: dict):
        """把 reply 按 id 投递给对应的 pending future。"""
        rid = reply.get("id")
        fut = self._pending.pop(rid, None)
        if fut and not fut.done():
            fut.set_result(reply)

    async def locate(self, query, css=None, max_results=10, profile_id="default", timeout=3.0) -> dict:
        deadline = timeout
        while self._active(profile_id) is None and deadline > 0:
            await asyncio.sleep(0.3); deadline -= 0.3
        c = self._active(profile_id)
        if c is None:
            raise TimeoutError(f"no tab for profile {profile_id}")
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await c["ws"].send_json({"id": rid, "op": "locate", "query": query, "css": css, "max_results": max_results})
        try:
            return await asyncio.wait_for(fut, timeout=max(deadline, 1.0))
        finally:
            self._pending.pop(rid, None)

def make_ws_route(bridge: "DomBridge"):
    from starlette.websockets import WebSocket
    async def handler(ws: "WebSocket"):
        await ws.accept()
        first = await ws.receive_json()
        if not bridge.check_auth(first):
            await ws.close(code=4401); return
        bridge.register(ws, first.get("profile_id", "default"), first.get("tab_id"),
                        first.get("url"), first.get("active", True))
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "active":
                    bridge.set_active(ws, msg.get("active"))
                else:
                    bridge._deliver(msg)
        except Exception:
            pass
        finally:
            bridge.unregister(ws)
    return ("/dom-bridge", handler)


def run_bridge_loopback(bridge, host: str = "127.0.0.1", port: int = 8779):
    """在守护线程里起一个【只绑 127.0.0.1】的最小 WS server 跑 /dom-bridge。
    扩展是本机 Chrome → loopback 即安全边界, 不暴露给 LAN。"""
    import asyncio, threading, uvicorn
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    path, handler = make_ws_route(bridge)
    app = Starlette(routes=[WebSocketRoute(path, handler)])
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    t.start()
    return t
