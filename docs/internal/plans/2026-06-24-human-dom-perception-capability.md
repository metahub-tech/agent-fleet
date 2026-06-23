# human_dom DOM 感知能力 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 human_browser 加伴生能力 `human_dom`——保持 human 特征（真 profile + OS 级真输入 + 零自动化痕迹）下，用 Chrome 扩展 content script 只读 DOM 拿元素坐标、操作仍走 core OS 级 `tap/type`，DOM 拿不到落 `vision_locate`(OCR)。

**Architecture:** 纯逻辑（坐标映射 `_geom.py`、locate 编排 `_locate.py`、桥协议）全在 `platforms/common/capabilities/human_dom/`，用 fake 桥 + 合成几何在 Linux CI 全测；WS 桥 `_bridge.py` 挂在 server 现有 Starlette app 上（`_server_runtime.serve()` 加 `extra_routes`），content script 直连 `127.0.0.1` 规避 MV3 SW 死亡；`HumanDomCapability` 是 `CapabilityModule`，**靠 server 注入 `tap_fn`/`type_fn` + 持有 bridge**（capability 不 import server，破循环，沿用 vision 模式）。

**Tech Stack:** Python 3.10+，FastMCP（http_app / streamable-http）、Starlette WebSocket、`websockets`/Starlette WS、pytest（含 fastmcp+httpx 集成测试，skipif）；Chrome MV3 扩展（manifest v3 + content script，纯 JS，无第三方依赖）。

**Spec:** `docs/internal/design/2026-06-24-human-dom-perception-capability.md`（已 architect 审，4 阻断 + Retina 公式已并入）。

**约定：** 每个 commit 用 `git commit -s`（DCO，仓内 CONTRIBUTING 必需）。CI 不跑 `platforms/common/tests`（见 `memory/reference-agentfleet-ci-coverage-gap`）→ **每个纯逻辑/集成测试都要本地 `pytest` 实跑**。真机验证用 macmini（mac-device），唤醒注意见 `memory/reference-macmini-display-idle-sleep`。

---

## 文件结构（先锁分解）

| 文件 | 职责 | 测试 |
|---|---|---|
| `platforms/common/capabilities/human_dom/__init__.py` | 导出 `HumanDomCapability` | — |
| `platforms/common/capabilities/human_dom/_geom.py` | 纯：视口 rect + 视口几何 → 屏幕坐标（mac 公式） | `test_human_dom_geom.py` |
| `platforms/common/capabilities/human_dom/_bridge.py` | WS 桥：client 注册表 + locate 派发 + WS 认证 + Starlette WS route 工厂 | `test_human_dom_bridge.py` |
| `platforms/common/capabilities/human_dom/_locate.py` | 纯编排：query → bridge.locate → 候选映射屏幕坐标 → 结构化结果/兜底信号 | `test_human_dom_locate.py` |
| `platforms/common/capabilities/human_dom/_human_dom.py` | `CapabilityModule`：注册 `human_dom_locate/tap/fill`，注入 `tap_fn`/`type_fn`/`bridge` | （工具薄包，逻辑在上面三测） |
| `platforms/common/capabilities/human_dom/extension/manifest.json` | MV3 manifest（content script + 127.0.0.1 host_permissions） | 真机/Playwright |
| `platforms/common/capabilities/human_dom/extension/content.js` | content script：只读 DOM 找候选 + getBoundingClientRect + 直连 WS | 真机/Playwright |
| `platforms/common/_server_runtime.py`（改） | `serve()` 加可选 `extra_routes`，经 `mcp.http_app()` 注入后跑 | （Spike A 定 API） |
| `platforms/macos/server/mac_device_mcp.py`（改） | 构造 bridge + 注入 capability + serve(extra_routes=[ws_route]) | 真机 |
| `platforms/macos/platform.toml`（改） | `[capabilities].enabled` 加 `human_dom` | 真机 |
| `platforms/common/skills/using-human-dom/SKILL.md` | skill：先 human_browser_open 再 human_dom_*，何时落 OCR | — |
| `platforms/macos/scripts/install-human-dom-extension.sh` | 一次性把扩展装进真实 profile（说明文档） | 真机 |

---

## Phase 0 — Spikes（先去风险，结果写进后续任务）

### Task 0A: Spike — FastMCP 暴露 Starlette app 以挂 WS 路由的入口

**Files:** 无（调查 + 记录到本任务勾选项备注）

- [ ] **Step 1: 本机 introspect fastmcp 的 app 构建入口**

Run:
```bash
python3 - <<'PY'
import inspect, fastmcp
from fastmcp import FastMCP
print("ver", fastmcp.__version__)
print("http_app:", inspect.signature(FastMCP.http_app))
m = FastMCP("probe")
app = m.http_app(transport="http")
print("app type:", type(app))
print("has add_websocket_route:", hasattr(app, "add_websocket_route"))
print("has router:", hasattr(app, "router"), "router routes attr:", hasattr(getattr(app,'router',None), "routes"))
PY
```
Expected: 打印出 `app` 是 `Starlette`（或子类）、`add_websocket_route` 或 `router.routes` 可用。

- [ ] **Step 2: 确认运行方式**

判定二选一并记录：(a) `app = mcp.http_app(...)` → `app.add_websocket_route("/dom-bridge", h)`（或 `app.router.routes.append(WebSocketRoute(...))`）→ `uvicorn.run(app, host, port)`；(b) 若 http_app 不可挂，改用外层 `Starlette(routes=[Mount("", app=app), WebSocketRoute("/dom-bridge", h)])`。
Expected: 记下能 append WS route 且不破坏 `/mcp`、`/health` 的具体调用。Task 1A 用该结论。

- [ ] **Step 3: 记录 fastmcp 下界**

确认 `http_app` 形参 + WS 挂载在 `fastmcp>=2.3.2`（mac/win pyproject 现有下界）成立；不成立则在 Task 1A 提高下界并记原因。

### Task 0B: Spike — content script 能否直连 `ws://127.0.0.1:<port>`（macmini）

**Files:** 临时 `/tmp/spike-ext/`（spike 后删）

- [ ] **Step 1: 在 macmini 起一个最小 WS echo**

在 mac-device 上 `python3 -c` 起 `websockets` echo server 于 `127.0.0.1:8799`（或复用 server 端口起临时路由）。

- [ ] **Step 2: 临时扩展连它**

`/tmp/spike-ext/manifest.json`（MV3，`host_permissions:["http://127.0.0.1/*","ws://127.0.0.1/*"]`，content_scripts 注 `<all_urls>`）+ `content.js`：`new WebSocket("ws://127.0.0.1:8799")` → onopen 发 `{hello:location.href}`。Load unpacked 进**真实 profile**，开任意页。
Expected: echo server 收到 `{hello:...}`。**确认 content script 能直连 localhost WS、tab 存活即在线。** 失败则回退方案（content script→`fetch` long-poll，或经 background SW + chrome.runtime）并记录。

- [ ] **Step 3: dev-mode stealth 探针（顺带做 §3 待验 spike）**

同一开了 Developer Mode + 装了 spike 扩展的真实 Chrome，`human_browser_open("https://bot.sannysoft.com")` → 截图核 `navigator.webdriver=false`、无 WebDriver 红行。
Expected: 与 CDP 分析基线一致（dev-mode + 扩展对网站 JS 不可见）。结论记入 spec §3/PR #60。删除 `/tmp/spike-ext`。

### Task 0C: Spike — macmini Retina 坐标公式标定

**Files:** 无（标定结果写进 Task 1B 的 `top_chrome_px`）

- [ ] **Step 1: 取已知元素的视口 rect + 窗口几何**

`human_browser_open("https://example.com")` → 用 spike 扩展（或临时 content.js）打印 `JSON.stringify({rect: document.querySelector('h1').getBoundingClientRect(), screenX, screenY, innerWidth, innerHeight, outerWidth, outerHeight, devicePixelRatio})`。

- [ ] **Step 2: 按 spec §5.3 公式算屏幕中心并验证落点**

`screen_x = screenX + rect.left + rect.width/2`；`screen_y = screenY + (outerHeight-innerHeight) + rect.top + rect.height/2`。`take_screenshot` 量该 h1 的实际屏幕中心，比对。
Expected: 误差 < ~5px。**若系统性偏移**：记录真实 `top_chrome_px`（screenY→视口顶的实测垂直偏移）与 `screenX` 是否需修正，作为 `_geom.top_chrome_px()` 的标定常量。确认 mac 上**不需乘 dpr**。

---

## Phase 1 — M1：扩展 + 桥 + `human_dom_locate`

### Task 1A: `serve()` 支持 `extra_routes`（共享 helper，向后兼容）

**Files:**
- Modify: `platforms/common/_server_runtime.py`
- Test: `platforms/common/tests/test_server_runtime.py`（加用例）

- [ ] **Step 1: 写失败测试（extra_routes 透传不破坏旧行为）**

在 `test_server_runtime.py` 末尾加（纯逻辑：验证 `serve` 接受 `extra_routes` 形参且默认 None 时行为不变——用 monkeypatch 拦截运行）：
```python
def test_serve_accepts_extra_routes_without_running(monkeypatch):
    import _server_runtime as sr
    captured = {}
    class _FakeMcp:
        def http_app(self, **kw): captured["http_app_kw"] = kw; return _FakeApp()
        def run(self, **kw): captured["run_kw"] = kw
    class _FakeRouter:
        def __init__(self): self.routes = []
        def add_websocket_route(self, path, handler): self.routes.append((path, handler))
    class _FakeApp:
        def __init__(self): self.router = _FakeRouter()
    monkeypatch.setattr(sr, "_run_app",
                        lambda app, host, port: captured.update({"routes": app.router.routes, "ran": (host, port)}))
    async def _h(ws): ...
    sr.serve(_FakeMcp(), prog="t", default_port=9999, argv=["--port","9001"],
             extra_routes=[("/dom-bridge", _h)])
    assert ("/dom-bridge", _h) in captured["routes"]
    assert captured["ran"] == ("0.0.0.0", 9001)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_server_runtime.py::test_serve_accepts_extra_routes_without_running -q`
Expected: FAIL（`serve()` 无 `extra_routes` 形参 / 无 `_run_app`）。

- [ ] **Step 3: 改 `serve()`（按 Task 0A 结论实现）**

`_server_runtime.py`：`serve()` 增 `extra_routes: list | None = None`。**无 extra_routes 时走原 `mcp.run(**run_kwargs)` 路径（旧平台零改动）**；有 extra_routes 时：
```python
def _run_app(app, host, port):
    import uvicorn
    uvicorn.run(app, host=host, port=port)

def serve(mcp, prog, default_port, argv=None, extra_routes=None):
    # ...（保留行缓冲 + parse_server_args + register_health_route）...
    gate = auth_middleware(args.token)
    if not extra_routes:
        run_kwargs = {"transport": "http", "host": args.host, "port": args.port}
        if gate: run_kwargs["middleware"] = gate
        mcp.run(**run_kwargs); return
    app = mcp.http_app(transport="http", middleware=gate or None)
    for path, handler in extra_routes:
        app.router.add_websocket_route(path, handler)   # 0A 确认: app 本身无此法, 用 app.router(StarletteWithLifespan)
    _run_app(app, args.host, args.port)
```
（`register_health_route(mcp)` 仍在 `mcp.http_app` 之前调用，保证 /health 进 app。）

- [ ] **Step 4: 运行测试通过 + 全量回归**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_server_runtime.py tests/test_server_app_integration.py -q`
Expected: PASS（含旧 16 例 + 新 1 例）。

- [ ] **Step 5: Commit**

```bash
git add platforms/common/_server_runtime.py platforms/common/tests/test_server_runtime.py
git commit -s -m "feat(server-runtime): serve() 支持 extra_routes（挂 WS 桥用，无则走原 mcp.run）"
```

### Task 1B: `_geom.py` 坐标映射（纯逻辑，TDD）

**Files:**
- Create: `platforms/common/capabilities/human_dom/__init__.py`、`platforms/common/capabilities/human_dom/_geom.py`
- Test: `platforms/common/tests/test_human_dom_geom.py`

- [ ] **Step 1: 写失败测试**

`test_human_dom_geom.py`：
```python
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capabilities"))
from human_dom._geom import viewport_to_screen, top_chrome_px

GEOM = {"screenX": 100, "screenY": 80, "innerW": 1200, "innerH": 800,
        "outerW": 1200, "outerH": 888, "dpr": 2, "scrollX": 0, "scrollY": 500}

def test_top_chrome_px_is_outer_minus_inner():
    assert top_chrome_px(GEOM) == 88  # outerH - innerH

def test_center_maps_screenX_plus_rect_no_dpr():
    rect = {"left": 40, "top": 60, "width": 100, "height": 20}
    out = viewport_to_screen(rect, GEOM)
    # screenX + left + w/2 = 100+40+50 = 190 ; screenY + (outerH-innerH) + top + h/2 = 80+88+60+10 = 238
    assert out["center"] == [190.0, 238.0]
    assert out["box"] == [140.0, 228.0, 100, 20]  # screen left/top/w/h
    # 关键：dpr=2 但不参与（mac point 空间 1:1）

def test_rect_already_scroll_relative_no_scroll_subtraction():
    rect = {"left": 0, "top": 0, "width": 10, "height": 10}
    out = viewport_to_screen(rect, GEOM)
    assert out["center"] == [105.0, 173.0]  # 不减 scrollY
```

- [ ] **Step 2: 运行确认失败**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_geom.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `_geom.py`**

```python
"""视口坐标(CSS px) → 屏幕坐标(point 空间, 与 take_screenshot/tap 同空间)。
mac: window.screenX/Y 与 getBoundingClientRect 同在 CSS px, OS 点空间 1:1, 不乘 dpr。
top_chrome_px 由 Task 0C 真机标定; 默认 outerH-innerH。"""
from __future__ import annotations

def top_chrome_px(geom: dict) -> float:
    # Task 0C 若标出固定偏移, 在此改为标定常量。
    return float(geom["outerH"]) - float(geom["innerH"])

def viewport_to_screen(rect: dict, geom: dict) -> dict:
    ox = float(geom["screenX"])
    oy = float(geom["screenY"]) + top_chrome_px(geom)
    sl = ox + float(rect["left"]); st = oy + float(rect["top"])
    w = float(rect["width"]); h = float(rect["height"])
    return {"center": [sl + w / 2, st + h / 2], "box": [sl, st, rect["width"], rect["height"]]}
```
并建空 `human_dom/__init__.py`（暂空，Task 1E 填导出）。

- [ ] **Step 4: 运行通过**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_geom.py -q`
Expected: PASS（3 例）。

- [ ] **Step 5: Commit**

```bash
git add platforms/common/capabilities/human_dom/__init__.py platforms/common/capabilities/human_dom/_geom.py platforms/common/tests/test_human_dom_geom.py
git commit -s -m "feat(human_dom): 坐标映射 _geom（mac point 空间, 不乘 dpr）+ TDD"
```

### Task 1C: `_locate.py` 编排（纯逻辑 + fake bridge，TDD）

**Files:**
- Create: `platforms/common/capabilities/human_dom/_locate.py`
- Test: `platforms/common/tests/test_human_dom_locate.py`

- [ ] **Step 1: 写失败测试（用 fake bridge，不碰真 WS）**

```python
import asyncio, sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capabilities"))
from human_dom._locate import resolve_locate

class FakeBridge:
    def __init__(self, reply): self._reply = reply
    async def locate(self, query, css=None, max_results=10, timeout=3.0): return self._reply

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
    assert out["ok"] is False and out["reason"] == "bridge_no_active_tab"
    assert out["suggest"] == "vision_locate"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_locate.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `_locate.py`**

```python
"""locate 编排: query → bridge.locate → 候选映射屏幕坐标 → 结构化结果/兜底。永不抛到 server。"""
from __future__ import annotations
from ._geom import viewport_to_screen

async def resolve_locate(bridge, query, css=None, max_results=10, timeout=3.0) -> dict:
    try:
        reply = await bridge.locate(query, css=css, max_results=max_results, timeout=timeout)
    except TimeoutError:
        return {"ok": False, "reason": "bridge_no_active_tab",
                "suggest": "vision_locate",
                "hint": "页面未就绪或无 active tab 的扩展连入; 先 take_screenshot 确认页面 load, 或用 vision_locate"}
    except Exception as e:
        return {"ok": False, "reason": f"bridge_error:{type(e).__name__}", "suggest": "vision_locate"}
    if not reply.get("ok"):
        return {"ok": False, "reason": "not_found", "dom_sample": reply.get("dom_candidates", []),
                "suggest": "vision_locate"}
    geom = reply["viewport"]
    out = []
    for c in reply.get("candidates", [])[:max_results]:
        m = viewport_to_screen(c["rectViewport"], geom)
        out.append({"text": c.get("text"), "role": c.get("role"),
                    "center": m["center"], "box": m["box"],
                    "visible": c.get("visible", True), "clickable": c.get("clickable", True)})
    return {"ok": True, "candidates": out}
```

- [ ] **Step 4: 运行通过**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_locate.py -q`
Expected: PASS（3 例）。

- [ ] **Step 5: Commit**

```bash
git add platforms/common/capabilities/human_dom/_locate.py platforms/common/tests/test_human_dom_locate.py
git commit -s -m "feat(human_dom): locate 编排 _locate（候选映射 + 未命中兜底信号）+ TDD"
```

### Task 1D: `_bridge.py` WS 桥（client 注册 + 派发 + 认证，TDD）

**Files:**
- Create: `platforms/common/capabilities/human_dom/_bridge.py`
- Test: `platforms/common/tests/test_human_dom_bridge.py`

- [ ] **Step 1: 写失败测试（fake websocket，不起真服务）**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_bridge.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `_bridge.py`（DomBridge + Starlette WS route 工厂）**

```python
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

    def register(self, ws, tab_id, url, active): self._clients.append({"ws":ws,"tab_id":tab_id,"url":url,"active":active})
    def unregister(self, ws): self._clients = [c for c in self._clients if c["ws"] is not ws]

    def _active(self):
        for c in self._clients:
            if c["active"]: return c
        return self._clients[0] if self._clients else None

    async def locate(self, query, css=None, max_results=10, timeout=3.0) -> dict:
        deadline = timeout
        # 短等 active client 拨入（CS 注入时序, spec §7）
        while self._active() is None and deadline > 0:
            await asyncio.sleep(0.3); deadline -= 0.3
        c = self._active()
        if c is None: raise TimeoutError("no active tab")
        rid = next(self._ids); fut = asyncio.get_event_loop().create_future(); self._pending[rid] = fut
        await c["ws"].send_json({"id":rid,"op":"locate","query":query,"css":css,"max_results":max_results})
        try:
            return await asyncio.wait_for(self._fulfill(c["ws"], rid, fut), timeout=max(deadline,1.0))
        finally:
            self._pending.pop(rid, None)

    async def _fulfill(self, ws, rid, fut):
        # 简化: 直接读该 ws 的下一条 reply（生产里由 route 的读循环 set_result）
        reply = await ws.receive_json()
        return reply

def make_ws_route(bridge: DomBridge):
    from starlette.websockets import WebSocket
    async def handler(ws: "WebSocket"):
        await ws.accept()
        first = await ws.receive_json()
        if not bridge.check_auth(first):
            await ws.close(code=4401); return
        bridge.register(ws, first.get("tab_id"), first.get("url"), first.get("active", True))
        try:
            while True:
                await ws.receive_json()  # 心跳/状态; locate reply 走 send/receive 配对
        except Exception:
            pass
        finally:
            bridge.unregister(ws)
    return ("/dom-bridge", handler)
```
> 说明：测试用 `FakeWS.receive_json` 喂 reply 驱动 `_fulfill`；生产 route 的读循环与 pending future 配对在 Task 2 真机联调时按 0A/0B 结论收口（reply 用 `id` 匹配 `_pending[id].set_result`）。本任务先把**认证 + 派发 + 无 active 超时**三条纯逻辑测绿。

- [ ] **Step 4: 运行通过**

Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_bridge.py -q`
Expected: PASS（3 例）。

- [ ] **Step 5: Commit**

```bash
git add platforms/common/capabilities/human_dom/_bridge.py platforms/common/tests/test_human_dom_bridge.py
git commit -s -m "feat(human_dom): WS 桥 _bridge（client 注册/派发/首帧认证/无 active 超时）+ TDD"
```

### Task 1E: Chrome 扩展（manifest + content script，只读）

**Files:**
- Create: `platforms/common/capabilities/human_dom/extension/manifest.json`、`.../extension/content.js`

- [ ] **Step 1: manifest.json（MV3，按 Task 0B 确认的 host_permissions）**

```json
{
  "manifest_version": 3,
  "name": "agent-fleet human_dom locator",
  "version": "0.1.0",
  "description": "只读 DOM 定位桥（仅本机 127.0.0.1，配合 agent-fleet human_browser）。",
  "host_permissions": ["http://127.0.0.1/*", "ws://127.0.0.1/*"],
  "content_scripts": [{"matches": ["<all_urls>"], "js": ["content.js"], "run_at": "document_idle"}]
}
```
（**无 `web_accessible_resources`、无 background SW**——content script 直连，spec §5.1。）

- [ ] **Step 2: content.js（只读：连 WS + 收 locate + querySelector/文本匹配 + getBoundingClientRect）**

```js
// 只读铁律: 绝不 .click()/.value=/派发事件/改 DOM。端口由占位常量, install 脚本注入。
const PORT = (window.__AF_HUMAN_DOM_PORT__ || 8767), TOKEN = (window.__AF_HUMAN_DOM_TOKEN__ || "");
function geom(){return {screenX, screenY, innerW:innerWidth, innerH:innerHeight,
  outerW:outerWidth, outerH:outerHeight, dpr:devicePixelRatio, scrollX, scrollY};}
function visibleText(el){const t=(el.innerText||el.value||el.getAttribute("aria-label")||
  el.getAttribute("placeholder")||el.getAttribute("title")||"").trim(); return t;}
function matchAll(query, css, max){
  const pool = css ? [...document.querySelectorAll(css)]
    : [...document.querySelectorAll('a,button,input,textarea,[role],[onclick],[contenteditable]')];
  const q = query.toLowerCase(), out=[];
  for(const el of pool){
    const txt = visibleText(el); if(!txt && !css) continue;
    if(css || txt.toLowerCase().includes(q)){
      const r = el.getBoundingClientRect();
      if(r.width===0||r.height===0) continue;
      out.push({text:txt, role:el.getAttribute("role")||el.tagName.toLowerCase(),
        rectViewport:{left:r.left,top:r.top,width:r.width,height:r.height},
        visible:true, clickable:!el.disabled, _exact: txt.toLowerCase()===q});
    }
  }
  out.sort((a,b)=>(b._exact-a._exact)); return out.slice(0,max);
}
function visibleSample(n){return [...document.querySelectorAll('a,button,[role],input,textarea')]
  .map(visibleText).filter(Boolean).slice(0,n);}
function connect(){
  const ws = new WebSocket(`ws://127.0.0.1:${PORT}/dom-bridge`);
  ws.onopen = ()=> ws.send(JSON.stringify({type:"auth", token:TOKEN, tab_id:String(Date.now()),
    url:location.href, active:!document.hidden}));
  ws.onmessage = (ev)=>{
    const m = JSON.parse(ev.data); if(m.op!=="locate") return;
    const cands = matchAll(m.query, m.css, m.max_results||10);
    ws.send(JSON.stringify(cands.length
      ? {id:m.id, ok:true, candidates:cands, viewport:geom()}
      : {id:m.id, ok:false, dom_candidates:visibleSample(8), viewport:geom()}));
  };
  ws.onclose = ()=> setTimeout(connect, 1000);
}
connect();
```

- [ ] **Step 3: 人工 lint（无第三方依赖，跳过 JS 测试框架）**

Run: `node --check platforms/common/capabilities/human_dom/extension/content.js`
Expected: 无语法错误。

- [ ] **Step 4: Commit**

```bash
git add platforms/common/capabilities/human_dom/extension/
git commit -s -m "feat(human_dom): Chrome MV3 扩展（content script 只读 DOM + 直连 127.0.0.1 WS）"
```

### Task 1F: `HumanDomCapability` + `human_dom_locate` 工具

**Files:**
- Create: `platforms/common/capabilities/human_dom/_human_dom.py`
- Modify: `platforms/common/capabilities/human_dom/__init__.py`（导出）

- [ ] **Step 1: 实现 `_human_dom.py`（镜像 vision/human_browser 模式，注入 tap/type + 持 bridge）**

```python
"""human_dom 能力: 注册 human_dom_locate/tap/fill。靠 server 注入 tap_fn/type_fn + bridge。"""
from __future__ import annotations
import asyncio
from .._base import CapabilityModule, ORIGIN_SELF_BUILT
from ._locate import resolve_locate

class HumanDomCapability(CapabilityModule):
    id = "human_dom"
    display_name = "浏览器 human_dom(只读 DOM 定位, 配合 human_browser)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-human-dom"
    platforms = None

    def __init__(self, bridge, tap_fn, type_fn):
        self._bridge = bridge; self._tap = tap_fn; self._type = type_fn
        self.description = "只读 DOM 拿元素屏幕坐标(扩展 content script), 操作仍走 OS 级 tap/type; 未命中落 vision_locate。"

    def availability(self):
        # 只探注册期能定的依赖(WS 库)。"扩展是否在线"是运行时 locate 的事, 不在此判。
        try:
            import starlette.websockets  # noqa: F401
            return True, ""
        except Exception as e:
            return False, f"starlette WS 不可用: {e}"

    def register(self, mcp) -> list[str]:
        bridge, tap, type_ = self._bridge, self._tap, self._type
        @mcp.tool
        async def human_dom_locate(query: str, css: str = "", max_results: int = 10) -> dict:
            """只读 DOM 定位: 按文字/aria-label/placeholder(或 css)找元素, 返回屏幕坐标候选。
            先 human_browser_open 并等页面 load。未命中/桥未连会建议改用 vision_locate。"""
            return await resolve_locate(bridge, query, css=css or None, max_results=max_results)
        @mcp.tool
        async def human_dom_tap(query: str, nth: int = 0, css: str = "") -> dict:
            """定位 + OS 级点击(locate+tap 合一缩小漂移窗)。"""
            r = await resolve_locate(bridge, query, css=css or None)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason","not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][min(nth, len(r["candidates"])-1)]["center"]
            tap(int(round(x)), int(round(y)))
            return {"ok": True, "tapped": [int(round(x)), int(round(y))]}
        @mcp.tool
        async def human_dom_fill(query: str, text: str, css: str = "") -> dict:
            """定位 + 点击聚焦 + OS 级输入。"""
            r = await resolve_locate(bridge, query, css=css or None)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason","not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][0]["center"]; tap(int(round(x)), int(round(y))); type_(text)
            return {"ok": True, "filled_at": [int(round(x)), int(round(y))]}
        return ["human_dom_locate", "human_dom_tap", "human_dom_fill"]
```

- [ ] **Step 2: `__init__.py` 导出**

```python
from ._human_dom import HumanDomCapability
__all__ = ["HumanDomCapability"]
```

- [ ] **Step 3: 冒烟（import 不炸）**

Run: `cd platforms/common && PYTHONPATH=.:capabilities python3 -c "from human_dom import HumanDomCapability; print('ok', HumanDomCapability.id)"`
Expected: `ok human_dom`。

- [ ] **Step 4: Commit**

```bash
git add platforms/common/capabilities/human_dom/_human_dom.py platforms/common/capabilities/human_dom/__init__.py
git commit -s -m "feat(human_dom): HumanDomCapability + human_dom_locate/tap/fill（注入 tap/type + bridge）"
```

### Task 1G: mac server 接线 + platform.toml 启用

**Files:**
- Modify: `platforms/macos/server/mac_device_mcp.py`、`platforms/macos/platform.toml`

- [ ] **Step 1: mac server 构造 bridge + 注入 capability + serve(extra_routes)**

`mac_device_mcp.py`：import `from capabilities.human_dom import HumanDomCapability`、`from capabilities.human_dom._bridge import DomBridge, make_ws_route`；在能力注册区加：
```python
_dom_bridge = DomBridge(token="")   # 与 serve 的 --token 一致; 复用 _os_tap + type_text
_cap_registry.add(HumanDomCapability(_dom_bridge, tap_fn=_os_tap, type_fn=lambda s: type_text(s)))
```
`main()` 的 `serve(...)` 改为 `_server_runtime.serve(mcp, prog="agent-fleet-mac", default_port=8767, extra_routes=[make_ws_route(_dom_bridge)])`。
（`type_text` 用 mac 现有 core 工具的底层实现；若其为 @mcp.tool，抽出 `_os_type(s)` helper 注入，沿用 vision 抽 `_os_tap` 的做法。）

- [ ] **Step 2: platform.toml 启用**

`platforms/macos/platform.toml` 的 `[capabilities].enabled` 列表加 `"human_dom"`。

- [ ] **Step 3: 语法校验**

Run: `python3 -m py_compile platforms/macos/server/mac_device_mcp.py`
Expected: ✓。

- [ ] **Step 4: Commit**

```bash
git add platforms/macos/server/mac_device_mcp.py platforms/macos/platform.toml
git commit -s -m "feat(macos): 接入 human_dom（构造 bridge + 注入 tap/type + serve 挂 /dom-bridge）"
```

### Task 1H: 真机 — 装扩展 + locate 落点验证（macmini）

**Files:**
- Create: `platforms/macos/scripts/install-human-dom-extension.sh`（装扩展到真实 profile 的说明脚本）

- [ ] **Step 1: 写 install 脚本/文档**

`install-human-dom-extension.sh`：打印指引——把 `extension/` 路径填进 `content.js` 的 `__AF_HUMAN_DOM_PORT__/_TOKEN__`（或随 server 端口/token 生成），并在真实 Chrome `chrome://extensions` 开 Developer Mode → Load unpacked → 选扩展目录。

- [ ] **Step 2: 部署到 macmini + 重启 mac server + 重连**

把分支扩展 + server 改动同步到 macmini 的 clone；按 #59 流程重启 mac-device server（serve 现挂了 /dom-bridge）；`/mcp reconnect`；`list_capabilities` 见 `human_dom` enabled。

- [ ] **Step 3: 落点验证**

`human_browser_open("https://example.com")` → 等 load → `human_dom_locate("More information")` → 取 center → `tap` → `take_screenshot` 确认点中链接（或直接 `human_dom_tap("More information")` 跳转）。
Expected: 落点准（误差 < ~5px）。**若偏移** → 回 Task 0C/1B 调 `top_chrome_px` 标定常量，复跑 `test_human_dom_geom.py`。

- [ ] **Step 4: Commit（标定结果如有）**

```bash
git add platforms/macos/scripts/install-human-dom-extension.sh platforms/common/capabilities/human_dom/_geom.py
git commit -s -m "feat(human_dom): mac 装扩展脚本 + 真机坐标标定（M1 locate 落点验证通过）"
```

---

## Phase 2 — M2：tap/fill 兜底链 + 小红书发布 e2e 验收

### Task 2A: 桥 reply 配对收口（真机联调，按 0A/0B）

**Files:** Modify `platforms/common/capabilities/human_dom/_bridge.py`

- [ ] **Step 1:** 把 `make_ws_route` 的读循环改为按 `reply["id"]` 匹配 `self._pending[id].set_result(reply)`，`_fulfill` 改为 `await fut`（替掉 Task 1D 的简化 `receive_json`）。
- [ ] **Step 2:** 加单测 `test_reply_routed_by_id`（fake ws 推带 id 的 reply，验证并发两个 locate 各自拿到对的 reply）。
Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_bridge.py -q` → PASS。
- [ ] **Step 3:** 真机复跑 Task 1H Step 3 确认仍准。
- [ ] **Step 4: Commit** `git commit -s -m "fix(human_dom): 桥 reply 按 id 配对（支持并发 locate）"`

### Task 2B: 降级链 — DOM 未命中落 vision_locate（skill 层 + 工具提示）

**Files:** Modify `_human_dom.py`（错误返回已带 `suggest:"vision_locate"`，本任务确保 tap/fill 未命中也带；skill 写清编排）

- [ ] **Step 1:** 确认 `human_dom_tap/fill` 未命中返回含 `suggest:"vision_locate"`（Task 1F 已含——补测）。
- [ ] **Step 2:** 加 `test_human_dom_locate.py::test_tap_miss_suggests_vision`（fake bridge 返回 miss，调工具层封装函数验证 suggest）。
- [ ] **Step 3: Commit** `git commit -s -m "feat(human_dom): tap/fill 未命中统一回 vision_locate 兜底信号 + 测试"`

### Task 2C: 真机 — 小红书发布 e2e 验收（macmini，秦Pi 真号）

**Files:** 无（验收 + 记录）

- [ ] **Step 1:** 确认秦Pi 登录态（见 `memory/pulse-login-drop-2026-06-21`：用 data-collect/publish 的 agent-browser-profile；human_browser 用真实日常 profile，按实际发布 profile 来）。**发布真号属外发/不可逆 → 先跟创始人确认用测试稿或草稿态验证，不误发。**
- [ ] **Step 2:** `human_browser_open(创作页)` → `human_dom_locate/fill("标题", ...)`、正文、`#话题`、`human_dom_tap` 选封面/发布 → 全程 DOM 定位、OS 级操作。
- [ ] **Step 3:** 记录：定位命中率、端到端耗时（对比现状 18–40min）、是否仍需 OCR 兜底的步骤。
Expected: e2e 跑通且显著快；坐标错基本消除。
- [ ] **Step 4: Commit**（如有微调）`git commit -s -m "feat(human_dom): 小红书发布 e2e 验收通过（M2）"`

---

## Phase 3 — M3：skill + setup 文档 + 收口

### Task 3A: `using-human-dom` skill

**Files:** Create `platforms/common/skills/using-human-dom/SKILL.md`

- [ ] **Step 1:** 写 skill：human_dom vs human_browser/vision 的路由（真号 + 要 DOM 精度 → human_dom；DOM 拿不到 → vision_locate）；工作流（先 `human_browser_open` 等 load，再 `human_dom_locate/tap/fill`）；坐标空间说明；只读不操作的边界；CS 注入时序提示（等页面 load）。
- [ ] **Step 2: Commit** `git commit -s -m "docs(skill): using-human-dom"`

### Task 3B: CHANGELOG + blueprint 同步 + 全量回归

**Files:** Modify `CHANGELOG.md`；（`docs/internal/*` 不进 MAP，但新增 skill/能力可能影响 INTERFACE/MAP——跑 --check）

- [ ] **Step 1:** `CHANGELOG.md` `[Unreleased]` 加 human_dom 条目。
- [ ] **Step 2:** Run: `./scripts/gen-blueprint-map.sh --check && ./scripts/gen-blueprint-interface.sh --check && ./scripts/check-blueprint-refs.sh`；红则 `gen-blueprint-*.sh` 重生成。
- [ ] **Step 3:** Run 全量：`cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_geom.py tests/test_human_dom_locate.py tests/test_human_dom_bridge.py tests/test_server_runtime.py tests/test_server_app_integration.py -q` → 全 PASS。
- [ ] **Step 4: Commit** `git commit -s -m "docs(human_dom): CHANGELOG + blueprint 同步"`

### Task 3C: PR 收口（按既有流程）

- [ ] **Step 1:** 把 design PR #60 的 spec/plan 与实现合一（或新开实现 PR base main），推分支等 CI 四项绿。
- [ ] **Step 2:** 派 code-reviewer 审实现（安全敏感: WS 认证 + 只读铁律 + 坐标映射）；修阻断。
- [ ] **Step 3:** 创始人复核（真号发布属外发，落地前确认）后 squash 合并 + 清 worktree。

---

## 自查（写完对着 spec 核）

- **Spec 覆盖**：§5.1 扩展(1E) ✓ / §5.2 桥+WS 挂载+认证(1A,1D,2A) ✓ / §5.3 坐标映射(1B,0C) ✓ / §5.4 三工具(1F) ✓ / §5.5 能力模块+availability(1F) ✓ / §5.6 兜底链(1C,2B) ✓ / §6 装扩展(1H,3A) ✓ / §7 CS 注入时序(1D locate 短等) ✓ / §8 测试(各 Task TDD + 1H/2C 真机) ✓ / §9 里程碑=Phase1/2/3 ✓ / §10 风险=Phase0 spikes ✓ / §11 YAGNI（无 long-poll、扩展只读、不碰 win/ios/android）✓。
- **无 placeholder**：纯逻辑任务均含完整 test+impl 代码与命令；spike/真机任务为可执行流程 + 期望产出，非 TODO。
- **类型/命名一致**：`viewport_to_screen`/`top_chrome_px`(1B)、`resolve_locate`(1C,1F)、`DomBridge`/`make_ws_route`(1D,1G,2A)、`HumanDomCapability`(1F,1G)、reply 字段 `candidates/rectViewport/dom_candidates/viewport`(1C,1D,1E 一致)。
- **待真机收口的两处**（已显式标注、非 placeholder）：桥 reply 按 id 配对（1D 简化 → 2A 收口）；坐标 `top_chrome_px` 标定（0C → 1B/1H）。
