# human_dom 按 profile 维度路由 + 桥端口可配 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）or superpowers:executing-plans 逐任务实现。步骤用 `- [ ]`。
> 关联 spec：`docs/internal/design/2026-06-26-human-dom-profile-routing.md`（先读它）。

**Goal:** 把 human_dom 的桥从「按 active tab 全局猜」改成「按 profile 维度确定性路由」，并支持一台机多 server（桥端口启动时确定/向后扫/持久化）。

**Architecture:** content script 安装时烤入 `profile_id`+`port`（每 profile 一份扩展副本）→ 桥按 `profile_id` 分组路由 → `human_dom_*` 加 `profile` 参数。桥端口 server 启动时定死并持久化（`~/.fleet/dom-bridge-<mcp_port>.port`），扩展安装读该持久值；桥 listener 跑进 MCP 同一 event loop（仍只绑 127.0.0.1）。

**Tech Stack:** Python（FastMCP/starlette/uvicorn）、Chrome MV3 content script（JS）、pytest（纯逻辑 Linux 可测）。

---

## 文件结构（先锁定边界）

| 文件 | 责任 | 新建/改 |
|---|---|---|
| `platforms/common/capabilities/human_dom/_ident.py` | `human_dom_profile_id(profile_str)` 规范化 | 新建 |
| `platforms/common/capabilities/human_dom/_portfile.py` | `resolve_bridge_port` + 持久文件读写 | 新建 |
| `platforms/common/capabilities/human_dom/_setup.py` | `prepare_extension(out_dir,bridge_port,profile_id)` | 新建 |
| `platforms/common/capabilities/human_dom/extension/content.js` | 烤入占位 `__AF_PORT__/__AF_PROFILE_ID__`；auth 带 profile_id | 改 |
| `platforms/common/capabilities/human_dom/_bridge.py` | DomBridge 按 profile_id 路由；run_bridge_loopback 进主 loop | 改 |
| `platforms/common/capabilities/human_dom/_locate.py` | resolve_locate 透传 profile_id | 改 |
| `platforms/common/capabilities/human_dom/_human_dom.py` | 工具加 `profile`；新增 `human_dom_status` | 改 |
| `platforms/common/_server_runtime.py` | 暴露 `parse_server_args`；`serve(args=...)` | 改 |
| `platforms/windows/server/win_device_mcp.py`、`platforms/macos/server/mac_device_mcp.py` | 接 resolve_bridge_port + `--dom-bridge-port` + 桥进 loop + 注册 human_dom_status | 改 |
| `platforms/macos/scripts/install-human-dom-extension.sh`、`platforms/windows/scripts/install-human-dom-extension.ps1` | prepare_extension 引导 | 改/新建 |
| `platforms/common/skills/using-human-dom/SKILL.md`、`using-human-browser/SKILL.md` | profile 用法 + 安装流程 | 改 |
| `platforms/common/tests/test_human_dom_*.py` | 单测 | 新建 |
| `CHANGELOG.md` | 变更 | 改 |

测试约定：在 `platforms/common/` 下 `PYTHONPATH=. python3 -m pytest`（与现有 test 一致）。

---

## Task 1: `human_dom_profile_id` 规范化（纯函数）

**Files:**
- Create: `platforms/common/capabilities/human_dom/_ident.py`
- Test: `platforms/common/tests/test_human_dom_ident.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_human_dom_ident.py
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._ident import human_dom_profile_id

def test_empty_is_default():
    assert human_dom_profile_id("") == "default"
    assert human_dom_profile_id("   ") == "default"
    assert human_dom_profile_id(None) == "default"

def test_filesystem_safe_and_idempotent():
    a = human_dom_profile_id("~/.fleet/wechat-pub")
    assert a == human_dom_profile_id("~/.fleet/wechat-pub")      # 幂等
    assert re.fullmatch(r"[a-z0-9-]+", a)                        # 纯 [a-z0-9-]，可当目录名
    assert a.startswith("wechat-pub-")                           # 可读前缀

def test_distinct_profiles_distinct_id():
    assert human_dom_profile_id("~/.fleet/a") != human_dom_profile_id("~/.fleet/b")
```

- [ ] **Step 2: 跑，确认 FAIL**
Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_ident.py -q`
Expected: FAIL（`No module named 'capabilities.human_dom._ident'`）

- [ ] **Step 3: 实现**
```python
# capabilities/human_dom/_ident.py
"""human_dom profile 标识规范化: install 与 locate 必须用同一套。"""
from __future__ import annotations
import os, re, hashlib
from _browser_lease import _resolve_profile  # common/ 在 sys.path

def human_dom_profile_id(profile_str: "str | None") -> str:
    s = (profile_str or "").strip()
    if not s:
        return "default"
    udd, pdir, _key = _resolve_profile(s)               # 吸收 路径/dir@Name 差异
    canon = f"{os.path.realpath(os.path.expanduser(udd))}::{pdir or ''}"
    h = hashlib.sha1(canon.encode()).hexdigest()[:8]
    base = os.path.basename(udd.rstrip("/\\")) or "p"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:24] or "p"
    return f"{slug}-{h}"
```

- [ ] **Step 4: 跑，确认 PASS**
Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_ident.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/human_dom/_ident.py platforms/common/tests/test_human_dom_ident.py
git commit -s -m "feat(human_dom): profile_id 规范化(可读slug+sha1,文件系统安全)"
```

---

## Task 2: `resolve_bridge_port` + 持久文件（纯逻辑，注入 is_free 可测）

**Files:**
- Create: `platforms/common/capabilities/human_dom/_portfile.py`
- Test: `platforms/common/tests/test_human_dom_portfile.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_human_dom_portfile.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._portfile import resolve_bridge_port

def test_explicit_override_wins_and_persists(tmp_path):
    pf = tmp_path / "p"
    assert resolve_bridge_port(8766, override=9000, portfile=str(pf), is_free=lambda p: True) == 9000
    assert pf.read_text().strip() == "9000"

def test_derive_port_plus_13(tmp_path):
    assert resolve_bridge_port(8766, portfile=str(tmp_path/"p"), is_free=lambda p: True) == 8779

def test_scan_forward_when_taken(tmp_path):
    taken = {8779, 8780}
    assert resolve_bridge_port(8766, portfile=str(tmp_path/"p"), is_free=lambda p: p not in taken) == 8781

def test_persisted_stable_when_bindable(tmp_path):
    pf = tmp_path / "p"; pf.write_text("8790")
    assert resolve_bridge_port(8766, portfile=str(pf), is_free=lambda p: True) == 8790

def test_persisted_taken_falls_back_to_derive(tmp_path):
    pf = tmp_path / "p"; pf.write_text("8790")
    assert resolve_bridge_port(8766, portfile=str(pf), is_free=lambda p: p != 8790) == 8779
```

- [ ] **Step 2: 跑，确认 FAIL**
Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/test_human_dom_portfile.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**
```python
# capabilities/human_dom/_portfile.py
"""桥端口在 server 启动时一次确定并持久化; 扩展安装读该持久值(保 server↔扩展端口一致)。"""
from __future__ import annotations
import os, socket

def _portfile_path(mcp_port: int) -> str:
    return os.path.expanduser(f"~/.fleet/dom-bridge-{mcp_port}.port")

def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port)); return True
        except OSError:
            return False

def _read(pf: str) -> "int | None":
    try:
        return int(open(pf).read().strip())
    except Exception:
        return None

def _write(pf: str, port: int) -> None:
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    open(pf, "w").write(str(port))

def resolve_bridge_port(mcp_port: int, override=None, portfile: "str | None" = None, is_free=None) -> int:
    is_free = is_free or _is_free
    pf = portfile or _portfile_path(mcp_port)
    if override:
        chosen = int(override)
    else:
        persisted = _read(pf)
        if persisted and is_free(persisted):
            return persisted                       # 跨重启稳定, 已持久
        chosen = mcp_port + 13
        while not is_free(chosen):
            chosen += 1
    _write(pf, chosen)
    return chosen
```

- [ ] **Step 4: 跑，确认 PASS** — `pytest tests/test_human_dom_portfile.py -q` → 5 passed
- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/human_dom/_portfile.py platforms/common/tests/test_human_dom_portfile.py
git commit -s -m "feat(human_dom): 桥端口启动时确定(覆盖>持久>+13>向后扫)+持久化"
```

---

## Task 3: `prepare_extension`（生成 per-profile 扩展副本 + meta.json）

**Files:**
- Create: `platforms/common/capabilities/human_dom/_setup.py`
- Modify: `platforms/common/capabilities/human_dom/extension/content.js`（先加占位，见 Task 7 完成 auth 字段；本任务只需占位存在）
- Test: `platforms/common/tests/test_human_dom_setup.py`

- [ ] **Step 1: 先给模板 content.js 加占位常量**（Task 7 会补 auth 发送）。把 content.js 第 2 行
`const PORT = (window.__AF_HUMAN_DOM_PORT__ || 8779), TOKEN = (window.__AF_HUMAN_DOM_TOKEN__ || "");`
改为：
```javascript
const PORT = (__AF_PORT__ || 8779), TOKEN = (window.__AF_HUMAN_DOM_TOKEN__ || "");
const PROFILE_ID = ("__AF_PROFILE_ID__" || "default");
```
（未烤时 `__AF_PORT__` 是未定义标识符会抛——故模板本身不直接 Load；只经 prepare_extension 烤后用。烤替换把 `__AF_PORT__`→数字、`"__AF_PROFILE_ID__"`→实际串。）

- [ ] **Step 2: 写失败测试**
```python
# tests/test_human_dom_setup.py
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._setup import prepare_extension

def test_prepare_bakes_port_profile_and_meta(tmp_path):
    out = tmp_path / "ext"
    prepare_extension(str(out), bridge_port=8780, profile_id="wechat-ab12cd34")
    cjs = (out / "content.js").read_text()
    assert "const PORT = (8780" in cjs
    assert 'PROFILE_ID = ("wechat-ab12cd34"' in cjs
    assert "__AF_PORT__" not in cjs and "__AF_PROFILE_ID__" not in cjs
    assert (out / "manifest.json").exists()
    json.loads((out / "manifest.json").read_text())              # manifest 仍合法
    meta = json.loads((out / "meta.json").read_text())
    assert meta == {"profile_id": "wechat-ab12cd34", "bridge_port": 8780}
```

- [ ] **Step 3: 跑，确认 FAIL** — 模块不存在

- [ ] **Step 4: 实现**
```python
# capabilities/human_dom/_setup.py
"""生成某 profile 专属的 human_dom 扩展目录(烤入 port+profile_id)+ meta.json。"""
from __future__ import annotations
import json, shutil
from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parent / "extension"

def prepare_extension(out_dir: str, bridge_port: int, profile_id: str, template_dir: "str | None" = None) -> str:
    tpl = Path(template_dir) if template_dir else _TEMPLATE
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(tpl, out)
    cjs = out / "content.js"
    s = cjs.read_text()
    s = s.replace("__AF_PORT__", str(int(bridge_port)))
    s = s.replace("__AF_PROFILE_ID__", profile_id)
    cjs.write_text(s)
    (out / "meta.json").write_text(json.dumps({"profile_id": profile_id, "bridge_port": int(bridge_port)}))
    return str(out)
```

- [ ] **Step 5: 跑 PASS** — `pytest tests/test_human_dom_setup.py -q` → 1 passed
- [ ] **Step 6: Commit**
```bash
git add platforms/common/capabilities/human_dom/_setup.py platforms/common/capabilities/human_dom/extension/content.js platforms/common/tests/test_human_dom_setup.py
git commit -s -m "feat(human_dom): prepare_extension 生成 per-profile 扩展副本+meta.json"
```

---

## Task 4: DomBridge 按 profile_id 路由

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_bridge.py`
- Test: `platforms/common/tests/test_human_dom_bridge_routing.py`

- [ ] **Step 1: 写失败测试**（用 fake ws，验证按 profile 路由）
```python
# tests/test_human_dom_bridge_routing.py
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
    assert b._active("C") is None                       # 无该 profile

def test_locate_routes_to_requested_profile():
    b = DomBridge()
    wa, wb = FakeWS(), FakeWS()
    b.register(wa, profile_id="A", tab_id="1", url="a", active=True)
    b.register(wb, profile_id="B", tab_id="2", url="b", active=True)
    async def run():
        task = asyncio.create_task(b.locate("q", css=None, profile_id="B", timeout=1.0))
        await asyncio.sleep(0.05)
        # B 收到 locate, A 没有
        assert len(wb.sent) == 1 and wb.sent[0]["op"] == "locate"
        assert wa.sent == []
        rid = wb.sent[0]["id"]
        b._deliver({"id": rid, "ok": True, "candidates": [], "viewport": {}})
        return await task
    res = asyncio.run(run())
    assert res["ok"] is True

def test_locate_no_profile_raises():
    b = DomBridge()
    import pytest
    with pytest.raises(Exception):
        asyncio.run(b.locate("q", css=None, profile_id="ZZZ", timeout=0.4))
```

- [ ] **Step 2: 跑，确认 FAIL**（现 `register/_active/locate` 不带 profile_id）

- [ ] **Step 3: 改 `_bridge.py`**（只动 DomBridge 的 register/_active/locate + make_ws_route 读 profile_id；run_bridge_loopback 的 loop 在 Task 5）
```python
    def register(self, ws, profile_id, tab_id, url, active):
        self._clients.append({"ws": ws, "profile_id": profile_id or "default",
                              "tab_id": tab_id, "url": url, "active": active})

    def _active(self, profile_id):
        group = [c for c in list(self._clients) if c["profile_id"] == profile_id]   # 快照迭代
        for c in group:
            if c["active"]:
                return c
        return group[0] if group else None

    async def locate(self, query, css=None, max_results=10, profile_id="default", timeout=3.0):
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
```
并改 `make_ws_route` 的 register 调用读 `first.get("profile_id")`：
```python
        bridge.register(ws, first.get("profile_id", "default"), first.get("tab_id"),
                        first.get("url"), first.get("active", True))
```

- [ ] **Step 4: 跑 PASS** — `pytest tests/test_human_dom_bridge_routing.py -q` → 3 passed
- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/human_dom/_bridge.py platforms/common/tests/test_human_dom_bridge_routing.py
git commit -s -m "feat(human_dom): 桥按 profile_id 路由(_active/locate/register/ws-route)"
```

---

## Task 5: 桥 listener 跑进 MCP 同一 event loop（§4.8a 并发加固）

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_bridge.py`（run_bridge_loopback 支持「返回可在指定 loop 起的 coroutine/任务」）
- Modify: server 接线在 Task 9 串。本任务交付「可挂到主 loop」的形态 + 退路保留独立线程。

- [ ] **Step 1:** `_bridge.py` 新增 `make_loopback_app(port)` 返回 `(uvicorn.Server, )` 配置；保留 `run_bridge_loopback`（旧线程版，退路）。新增 `async def serve_bridge_in_loop(bridge, host, port)`：构 starlette app（同 make_ws_route）+ `uvicorn.Server(Config(..., host=127.0.0.1)).serve()`，由调用方 `loop.create_task()`。
```python
def make_bridge_app(bridge):
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    path, handler = make_ws_route(bridge)
    return Starlette(routes=[WebSocketRoute(path, handler)])

async def serve_bridge_in_loop(bridge, host="127.0.0.1", port=8779):
    import uvicorn
    app = make_bridge_app(bridge)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    await server.serve()   # 在调用者的 loop 里跑; 仍只绑 127.0.0.1
```
- [ ] **Step 2:** 单测有限（loop 集成留真机）。加一个轻测：`make_bridge_app(DomBridge())` 返回的 app 路由含 `/dom-bridge`。
```python
def test_bridge_app_has_route():
    from capabilities.human_dom._bridge import make_bridge_app, DomBridge
    app = make_bridge_app(DomBridge())
    assert any(getattr(r, "path", None) == "/dom-bridge" for r in app.routes)
```
- [ ] **Step 3:** 跑 PASS。**注**：实际「挂到 MCP loop」在 Task 9 server 接线用 FastMCP 启动钩子 `loop.create_task(serve_bridge_in_loop(...))`；若钩子接线代价大，退路用旧 `run_bridge_loopback` + `run_coroutine_threadsafe`/`call_soon_threadsafe`/`Lock`（见 spec §4.8a）。本任务先交付单 loop 形态。
- [ ] **Step 4: Commit**
```bash
git add platforms/common/capabilities/human_dom/_bridge.py platforms/common/tests/test_human_dom_bridge_routing.py
git commit -s -m "feat(human_dom): 桥 listener 可跑进 MCP 同一 loop(消跨 loop;仍 127.0.0.1)"
```

---

## Task 6: `_locate.py` 透传 profile_id + `_human_dom.py` 工具加 profile + `human_dom_status`

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_locate.py`、`_human_dom.py`
- Test: `platforms/common/tests/test_human_dom_status.py`

- [ ] **Step 1:** `_locate.py`：`resolve_locate(bridge, query, css=None, max_results=10, profile_id="default", timeout=3.0)`，把 `profile_id` 传给 `bridge.locate(...)`；`no active tab`/超时 → `{"ok":False,"reason":"no_tab_for_profile","profile":profile_id,"suggest":"该 profile 可能没起浏览器/没导航到目标页，或没装 human_dom 扩展(每 profile 单独装,见 using-human-dom);或 vision_locate"}`。

- [ ] **Step 2:** `_human_dom.py`：三工具签名加 `profile: str = ""`，内部 `pid = human_dom_profile_id(profile)` 传下去。新增工具 `human_dom_status()`：扫 `~/.fleet/human-dom-ext/*/meta.json` 取 `bridge_port == self_bridge_port` 的（installed），与桥当前 `_clients` 的 profile_id 求交（connected）。`HumanDomCapability.__init__` 增 `bridge_port` 入参以便 status 过滤。

- [ ] **Step 3: 写 status 失败测试**（注入 ext 目录 + fake bridge）
```python
# tests/test_human_dom_status.py
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._human_dom import compute_status   # 抽出纯函数便于测

def test_status_filters_by_port_and_marks_connected(tmp_path):
    root = tmp_path / "human-dom-ext"
    for pid, port in [("a-1", 8779), ("b-2", 8779), ("c-3", 8780)]:
        d = root / pid; d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"profile_id": pid, "bridge_port": port}))
    connected = {"a-1"}
    out = compute_status(ext_root=str(root), self_bridge_port=8779, connected_ids=connected)
    ids = {p["profile_id"]: p for p in out}
    assert set(ids) == {"a-1", "b-2"}                 # 只列本 server(8779)的; c-3(8780)不计
    assert ids["a-1"]["connected"] is True and ids["b-2"]["connected"] is False
    assert all(p["installed"] for p in out)
```
把 `compute_status(ext_root, self_bridge_port, connected_ids)` 实现为纯函数放 `_human_dom.py`；`human_dom_status` 工具调它（`ext_root=~/.fleet/human-dom-ext`、`connected_ids` 来自 bridge._clients）。

- [ ] **Step 4:** 跑 PASS（status 纯函数测）。`_locate`/工具签名改动由现有 e2e + Task 11 真机覆盖。
- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/human_dom/_locate.py platforms/common/capabilities/human_dom/_human_dom.py platforms/common/tests/test_human_dom_status.py
git commit -s -m "feat(human_dom): 工具加 profile 参数 + human_dom_status(installed/connected)"
```

---

## Task 7: content.js auth 带 profile_id（扩展侧完成）

**Files:** Modify `platforms/common/capabilities/human_dom/extension/content.js`

- [ ] **Step 1:** auth 帧加 `profile_id: PROFILE_ID`：
```javascript
  ws.onopen = ()=> ws.send(JSON.stringify({type:"auth", token:TOKEN, profile_id:PROFILE_ID,
    tab_id:String(Date.now()), url:location.href, active:!document.hidden}));
```
（PORT/PROFILE_ID 占位已在 Task 3 Step 1 加。）
- [ ] **Step 2:** 烤后语法自检：`prepare_extension` 生成一份到 tmp，用 `node --check`（若有 node）或正则确认无 `__AF_` 残留、`new Function` 解析不报错（CI 无 node 则跳，真机验）。
- [ ] **Step 3: Commit**
```bash
git add platforms/common/capabilities/human_dom/extension/content.js
git commit -s -m "feat(human_dom): content.js auth 带 profile_id"
```

---

## Task 8: `_server_runtime` 暴露 parse + serve(args)

**Files:** Modify `platforms/common/_server_runtime.py`

- [ ] **Step 1:** 把内部的 `parse_server_args()` 提为模块级公开函数（若已是则确认可 import）；给 argparse 加可选 `--dom-bridge-port`（`type=int, default=None`）。
- [ ] **Step 2:** `serve(mcp, *, args=None, extra_routes=None, ...)`：`if args is None: args = parse_server_args()`，其余不变（向后兼容）。
- [ ] **Step 3:** 现有 server 启动 e2e（blueprint/import 测）确认不破。Run: `cd platforms/common && PYTHONPATH=. python3 -m pytest tests/ -q -k "runtime or blueprint or server" --ignore=tests/test_vision.py`
- [ ] **Step 4: Commit**
```bash
git add platforms/common/_server_runtime.py
git commit -s -m "refactor(server): 暴露 parse_server_args + serve(args=) + --dom-bridge-port"
```

---

## Task 9: win/mac server 接线（端口解析 + 桥进 loop + 注册 status）

**Files:** Modify `platforms/windows/server/win_device_mcp.py`、`platforms/macos/server/mac_device_mcp.py`

- [ ] **Step 1:** 两端 `main()`：
```python
    from capabilities.human_dom._portfile import resolve_bridge_port
    args = parse_server_args()
    bridge_port = resolve_bridge_port(args.port, override=args.dom_bridge_port)
    # 桥挂到 MCP 同一 loop(用 FastMCP 启动钩子 create_task(serve_bridge_in_loop(_dom_bridge,'127.0.0.1',bridge_port)))
    # 退路: run_bridge_loopback(_dom_bridge, '127.0.0.1', bridge_port)
    ...
    _cap_registry.add(HumanDomCapability(_dom_bridge, tap_fn=_os_tap, fill_fn=_os_fill, bridge_port=bridge_port))
    serve(mcp, args=args, extra_routes=...)
```
- [ ] **Step 2:** 确认日志打印实际 bridge 端口；`HumanDomCapability` 注册 `human_dom_status`（其内部读 `~/.fleet/human-dom-ext` + `_dom_bridge._clients` + `bridge_port`）。
- [ ] **Step 3:** Linux 无法跑 win/mac server；**py_compile 两文件** + 留真机（Task 11）。Run: `python3 -m py_compile platforms/windows/server/win_device_mcp.py platforms/macos/server/mac_device_mcp.py`
- [ ] **Step 4: Commit**
```bash
git add platforms/windows/server/win_device_mcp.py platforms/macos/server/mac_device_mcp.py
git commit -s -m "feat(server): 接 resolve_bridge_port + 桥进 loop + 注册 human_dom_status(win/mac)"
```

---

## Task 10: 安装引导（mac .sh 改 + win .ps1 新增，走 prepare_extension）

**Files:** Modify `platforms/macos/scripts/install-human-dom-extension.sh`；Create `platforms/windows/scripts/install-human-dom-extension.ps1`

- [ ] **Step 1:** 两脚本逻辑：① 读该机 server 的 bridge 端口（`~/.fleet/dom-bridge-<mcp_port>.port`，mac 默认 mcp_port=该平台 port、win 同理；或参数传入）；② 调 `python -c "from capabilities.human_dom._setup import prepare_extension; prepare_extension('~/.fleet/human-dom-ext/<profile_id>', <port>, '<profile_id>')"`（profile_id 由 `human_dom_profile_id` 算，默认 `default`）；③ 打印/打开 out_dir 引导用户 chrome://extensions Load-unpacked；④ `mkdir -p ~/.fleet && touch ~/.fleet/human-dom-ready`（保留全局 marker 兼容）。
- [ ] **Step 2:** 脚本可读性自检（bash -n / PowerShell 语法）。
- [ ] **Step 3: Commit**
```bash
git add platforms/macos/scripts/install-human-dom-extension.sh platforms/windows/scripts/install-human-dom-extension.ps1
git commit -s -m "feat(human_dom): 安装引导走 prepare_extension(mac .sh改/win .ps1新增)"
```

---

## Task 11: skill + CHANGELOG + 真机端到端

**Files:** Modify `using-human-dom/SKILL.md`、`using-human-browser/SKILL.md`、`CHANGELOG.md`

- [ ] **Step 1:** `using-human-dom`：① `human_dom_*` 加 `profile=` 用法，**强调三处同一 profile 串**（open/装扩展/locate）；② 自助 Load-unpacked 流程改为「先 `prepare_extension` 生成带 PROFILE_ID/PORT 的 `~/.fleet/human-dom-ext/<id>` 再 Load-unpacked」；③ 多 profile **必须显式传 profile**、否则落 default；④ `human_dom_status` 查装/连状态；⑤ 别移动 `~/.fleet/human-dom-ext/`（移动后扩展 ID 变、需重装）。
- [ ] **Step 2:** `using-human-browser`：专用 profile 段补「human_dom 要传同一 profile」。
- [ ] **Step 3:** CHANGELOG「变更」加：human_dom 改 profile 维度路由 + 桥端口启动时确定/持久化 + per-profile 安装状态 + human_dom_status。
- [ ] **Step 4:** 全套非 vision 单测绿：`cd platforms/common && PYTHONPATH=. python3 -m pytest tests/ -q --ignore=tests/test_vision.py --ignore=tests/test_vision_locate.py --ignore=tests/test_vision_ocr.py`
- [ ] **Step 5: Commit**
```bash
git add platforms/common/skills/ CHANGELOG.md
git commit -s -m "docs(human_dom): skill+CHANGELOG 同步 profile 路由/端口/status"
```
- [ ] **Step 6: 真机端到端**（执行阶段单独做，不在本仓单测）：win-device + mac-device 各起两个 profile、各装带不同 PROFILE_ID/同 server PORT 的扩展，`human_dom_locate(profile=A)`/`(profile=B)` 分别命中各自页面、互不串线；默认 profile `profile=""` 命中默认 Chrome；`human_dom_status` 正确列装/连。**真账号写入验证用公众号正文(profile 固定)**。

---

## 跨仓 / 部署依赖（执行阶段处理，非本仓代码）

- **ops 仓发布员/pulse prompt**：human_dom 调用补 `profile=<固定值>`——**合并前硬前提**（真账号防误路由，spec §4.8 M4）。
- **AgentHub**：agent-fleet 更新后通知其更新 + 重装 desktop（清理所有 profile）重测。
- **openclaw 独立 server**：:8767 → 桥派生 8780，其各 profile 扩展烤 8780。
