"""human_dom 本地桥: content script 直连的 WS 客户端注册表 + locate 派发 + WS 认证。
绑 127.0.0.1; WS 不经 BearerAuthMiddleware, 首帧 {type:'auth',token} 自校验。"""
from __future__ import annotations
import asyncio, hmac, itertools, threading, time

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

    def register(self, ws, profile_id, tab_id, url, active, focused=None):
        with self._lock:
            self._clients.append({"ws": ws, "profile_id": profile_id or "default",
                                  "tab_id": tab_id, "url": url, "active": active,
                                  "focused": focused,   # None=旧扩展未上报(§6.4⑤); 前台检查带外查用, 不进 locate 派发
                                  "last_active_ts": time.monotonic()})
    def unregister(self, ws):
        with self._lock:
            self._clients = [c for c in self._clients if c["ws"] is not ws]

    def set_active(self, ws, active, focused=None):
        """content script 报前后台/焦点切换 → 更新该 client 的 active(修多 tab 派发) 与 focused(前台检查)。
        focused=None 表示本帧未带该字段 → 不覆盖(不把已有值抹成 None)。"""
        with self._lock:
            for c in self._clients:
                if c["ws"] is ws:
                    c["active"] = bool(active)
                    if focused is not None:
                        c["focused"] = focused
                    if active:
                        c["last_active_ts"] = time.monotonic()  # 最近活跃 → 省略 profile 解析优先它

    def _active(self, profile_id):
        with self._lock:
            group = [c for c in self._clients if c["profile_id"] == profile_id]
        for c in group:
            if c["active"]:
                return c
        return group[0] if group else None

    def active_operator_profile(self):
        """省略 profile 时的解析源: 返回当前【最近活跃的非 "default" operator profile】的 profile_id;
        无 operator tab 连着 → None(调用方回退 "default")。修 P6: 省略 profile 硬默认 "default"→no_tab。"""
        with self._lock:  # 锁内一次性 copy (profile_id, active, ts), 排序在锁外, 消脏读
            ops = [(c["profile_id"], bool(c.get("active")), c.get("last_active_ts", 0.0))
                   for c in self._clients if c["profile_id"] != "default"]
        if not ops:
            return None
        active = [t for t in ops if t[1]]
        pool = active or ops
        pool.sort(key=lambda t: t[2], reverse=True)   # 最近活跃优先
        return pool[0][0]

    def focus_state(self, profile_id):
        """前台检查(带外, Class C)源: 该 profile 活跃 client 的 focused(document.hasFocus())。
        无连接 / 旧扩展未上报 focused 键 → None(调用方回落截图, spec §6.4 ⑤/⑦)。
        复用 _active 选活跃 client, 【不改】其 locate 派发语义(focused 与 active 分离)。"""
        c = self._active(profile_id)
        return c.get("focused") if c else None

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
                        first.get("url"), first.get("active", True), first.get("focused"))
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "active":
                    bridge.set_active(ws, msg.get("active"), msg.get("focused"))
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
