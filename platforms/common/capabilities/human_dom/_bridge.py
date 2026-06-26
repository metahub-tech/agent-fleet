"""human_dom 本地桥: content script 直连的 WS 客户端注册表 + locate 派发 + WS 认证。
绑 127.0.0.1; WS 不经 BearerAuthMiddleware, 首帧 {type:'auth',token} 自校验。"""
from __future__ import annotations
import asyncio, hmac, itertools, threading

class DomBridge:
    def __init__(self, token: str = ""):
        self._token = token or ""
        self._clients = []          # [{ws, tab_id, url, active}]
        self._ids = itertools.count(1)
        self._pending = {}          # id -> (Future, loop)
        self._bridge_loop = None    # 桥线程的 event loop(线程版下由 run_bridge_loopback 存回)
        self._lock = threading.Lock()  # 保护 _clients/_pending 跨线程访问

    def check_auth(self, first_frame: dict) -> bool:
        if not self._token: return True
        return hmac.compare_digest(str(first_frame.get("token","")), self._token)

    def register(self, ws, profile_id, tab_id, url, active):
        with self._lock:
            self._clients.append({"ws": ws, "profile_id": profile_id or "default",
                                  "tab_id": tab_id, "url": url, "active": active})
    def unregister(self, ws):
        with self._lock:
            self._clients = [c for c in self._clients if c["ws"] is not ws]

    def set_active(self, ws, active):
        """content script 报前后台切换 → 更新该 client 的 active(修多 tab 派发)。"""
        with self._lock:
            for c in self._clients:
                if c["ws"] is ws:
                    c["active"] = bool(active)

    def _active(self, profile_id):
        with self._lock:
            group = [c for c in self._clients if c["profile_id"] == profile_id]
        for c in group:
            if c["active"]:
                return c
        return group[0] if group else None

    @staticmethod
    def _safe_set(fut, reply):
        # 在 future 自己的 loop 里执行: 调度前 fut 可能已被 wait_for 超时 cancel,
        # 故回调内再判一次 done(), 避免对 cancelled future set_result 抛 InvalidStateError。
        if not fut.done():
            fut.set_result(reply)

    def _deliver(self, reply: dict):
        """把 reply 按 id 投递给对应的 pending future。
        从桥线程调 → 用 future 自己的 loop.call_soon_threadsafe 安全 set_result(跨线程)。"""
        rid = reply.get("id")
        with self._lock:
            entry = self._pending.pop(rid, None)
        if entry:
            fut, floop = entry
            if not fut.done():   # 快路径; 真正的保障在 _safe_set 回调内再判一次
                floop.call_soon_threadsafe(self._safe_set, fut, reply)

    async def locate(self, query, css=None, max_results=10, profile_id="default", timeout=3.0) -> dict:
        deadline = timeout
        while self._active(profile_id) is None and deadline > 0:
            await asyncio.sleep(0.3); deadline -= 0.3
        c = self._active(profile_id)
        if c is None:
            raise TimeoutError(f"no tab for profile {profile_id}")
        rid = next(self._ids)
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        with self._lock:
            self._pending[rid] = (fut, loop)
        try:
            # ws 属桥线程 loop → send_json 必须在桥线程 loop 跑;
            # run_coroutine_threadsafe 返回 concurrent.futures.Future, wrap_future 让主 loop 可 await。
            send_coro = c["ws"].send_json({"id": rid, "op": "locate", "query": query, "css": css, "max_results": max_results})
            if self._bridge_loop is not None:
                await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(send_coro, self._bridge_loop))
            else:
                await send_coro   # 退化(测试里没起线程时, 单 loop)
            return await asyncio.wait_for(fut, timeout=max(deadline, 1.0))
        finally:
            with self._lock:
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
    扩展是本机 Chrome → loopback 即安全边界, 不暴露给 LAN。
    桥线程把自己的 loop 存回 bridge._bridge_loop, 让主 loop 的 locate 能跨线程
    run_coroutine_threadsafe 到桥 loop 发 ws、_deliver 能 call_soon_threadsafe 回 future loop。"""
    import asyncio, threading, uvicorn
    app = make_bridge_app(bridge)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            bridge._bridge_loop = loop   # 存回桥 loop(真 DomBridge 必有该属性)
        except AttributeError:
            pass                         # 容忍非 DomBridge 的桩对象(测试)
        loop.run_until_complete(server.serve())
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def make_bridge_app(bridge):
    """构 starlette app(含 /dom-bridge 路由)，供挂到调用方的 loop。"""
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    path, handler = make_ws_route(bridge)
    return Starlette(routes=[WebSocketRoute(path, handler)])


async def serve_bridge_in_loop(bridge, host: str = "127.0.0.1", port: int = 8779):
    """在调用者的 event loop 里跑桥(单 loop, 消跨 loop 隐患); 仍只绑 127.0.0.1。
    调用方: loop.create_task(serve_bridge_in_loop(bridge, '127.0.0.1', port))。"""
    import uvicorn
    app = make_bridge_app(bridge)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    await server.serve()
