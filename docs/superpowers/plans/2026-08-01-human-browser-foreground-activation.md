# human_browser 前台激活收口 Implementation Plan (StarBeam #188)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `human_browser_open` 默认不再抢前台（复用零重激活），并新增扩展带外前台检查 `human_dom_focused`，治 StarBeam #188"每次 open 抢前台吞输入"。

**Architecture:** 三条主线——① `human_browser_open` 加 `activate: bool=False`，复用路径默认不调最大化；② human_dom 扩展顺带报 `document.hasFocus()`，新增 `human_dom_focused` 带外布尔查（取代截图目测作前台检查首选）；③ Windows 冷启动改"非激活最大化"、mac 加 `-g`。配套迁移仓内两份 SKILL.md 的操作循环为"查→不对才拉"。设计依据：`docs/superpowers/specs/2026-08-01-human-browser-foreground-activation-design.md`（已过 architect 4 轮）。

**Tech Stack:** Python 3（FastMCP 工具、ctypes/user32 Win32）、浏览器 JS（content script）、pytest、node `vm`（content.js 测试）。

**关键约定（跨任务一致的签名，先锁死）：**
- 桥（`_bridge.py`）：`register(ws, profile_id, tab_id, url, active, focused=None)`、`set_active(ws, active, focused=None)`、`focus_state(profile_id) -> bool | None`。**`focused` 缺省 `None`（不是 `False`）**——旧扩展不发该字段时必须落 `None`（spec §6.4 局限⑤）。
- content.js：register/auth 首帧 = 原对象**追加** `focused`（不丢 `token`/`profile_id`/`tab_id`/`url`）；更新帧（visibilitychange + 新增 window focus/blur）走窄 `report()`。
- `_human_dom.py`：`human_dom_focused(profile="") -> {ok, focused, profile, reason}`。
- `_human_browser.py`：`human_browser_open(url="", profile="", activate=False)`；内部 `_maybe_foreground(fn, udd, activate) -> bool`；返回加 `activated: bool|None`、`maximized: bool`。
- `win_input.py`：`foreground_chrome_window_for_udd(udd, activate: bool = True) -> bool`（**`activate` 默认 `True` = 旧行为**，保证与旧 1 参调用兼容，让中间态不炸）。

**CI 盲区提醒：** `platforms/common`、平台 server 的 pytest **不进 CI**（reference-agentfleet-ci-coverage-gap）；Win32/`open` host-only 逻辑 Linux 无法 import → 靠 py_compile + test-win11 真机。本机可跑：`.mjs`（node）、纯 Python 单测（注入 fake）。

---

## Task 1: 桥 `focus_state` + `register`/`set_active` 穿 `focused`

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_bridge.py`（`register` :19-23、`set_active` :28-35、`make_ws_route` :101-121，新增 `focus_state`）
- Test: `platforms/common/tests/test_human_dom_focus_state.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `platforms/common/tests/test_human_dom_focus_state.py`:

```python
"""桥 focus_state: 前台检查带外查(document.hasFocus 值)。旧扩展无 focused 键必须落 None(不 False)。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities", "human_dom"))
from _bridge import DomBridge


class _WS:  # 唯一身份用于 register/unregister 匹配
    pass


def _reg(b, profile_id, active, focused="__absent__"):
    ws = _WS()
    if focused == "__absent__":
        # 模拟旧扩展: 首帧不带 focused 键 → 走 register 默认
        b.register(ws, profile_id, tab_id="t", url="u", active=active)
    else:
        b.register(ws, profile_id, tab_id="t", url="u", active=active, focused=focused)
    return ws


def test_focused_true():
    b = DomBridge()
    _reg(b, "op-x", active=True, focused=True)
    assert b.focus_state("op-x") is True


def test_focused_false_not_none():
    b = DomBridge()
    _reg(b, "op-x", active=True, focused=False)
    assert b.focus_state("op-x") is False   # 连着且确定不聚焦 → False, 不能是 None


def test_no_client_is_none():
    b = DomBridge()
    assert b.focus_state("op-missing") is None


def test_old_extension_no_focused_key_is_none():
    b = DomBridge()
    _reg(b, "op-x", active=True)             # 旧扩展: 首帧无 focused → 存 None
    assert b.focus_state("op-x") is None     # 关键: None 而非 False (spec §6.4 ⑤)


def test_set_active_updates_focused():
    b = DomBridge()
    ws = _reg(b, "op-x", active=True, focused=False)
    b.set_active(ws, active=True, focused=True)
    assert b.focus_state("op-x") is True


def test_focused_does_not_break_active_dispatch():
    # 分离守卫: focused 存取不改 _active 的派发(仍按 active 选)
    b = DomBridge()
    _reg(b, "op-x", active=False, focused=True)
    c = _reg(b, "op-x", active=True, focused=False)
    assert b._active("op-x")["ws"] is c      # 选 active=True 那个, 与 focused 无关
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python -m pytest tests/test_human_dom_focus_state.py -v`
Expected: FAIL（`register()` 不认 `focused` kwarg / 无 `focus_state`）

- [ ] **Step 3: 改 `_bridge.py`**

`register`（:19-23）加 `focused=None` 形参并存储：

```python
    def register(self, ws, profile_id, tab_id, url, active, focused=None):
        with self._lock:
            self._clients.append({"ws": ws, "profile_id": profile_id or "default",
                                  "tab_id": tab_id, "url": url, "active": active,
                                  "focused": focused,   # None=旧扩展未上报(§6.4⑤); 前台检查带外查用
                                  "last_active_ts": time.monotonic()})
```

`set_active`（:28-35）加 `focused=None` 形参、仅在传了时更新（不覆盖成 None）：

```python
    def set_active(self, ws, active, focused=None):
        """content script 报前后台/焦点切换 → 更新该 client 的 active 与 focused。"""
        with self._lock:
            for c in self._clients:
                if c["ws"] is ws:
                    c["active"] = bool(active)
                    if focused is not None:
                        c["focused"] = focused
                    if active:
                        c["last_active_ts"] = time.monotonic()
```

新增 `focus_state`（放在 `_active` 之后）：

```python
    def focus_state(self, profile_id):
        """前台检查(带外, Class C)源: 该 profile 活跃 client 的 focused(document.hasFocus())。
        无连接 / 旧扩展未上报 focused 键 → None(调用方回落截图, spec §6.4 ⑤/⑦)。
        不动 _active 的 locate 派发语义(分离)。"""
        c = self._active(profile_id)
        return c.get("focused") if c else None
```

`make_ws_route`（:108-116）首帧透传 `focused`、`active` 消息透传 `focused`：

```python
        bridge.register(ws, first.get("profile_id", "default"), first.get("tab_id"),
                        first.get("url"), first.get("active", True), first.get("focused"))
        ...
                if msg.get("type") == "active":
                    bridge.set_active(ws, msg.get("active"), msg.get("focused"))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python -m pytest tests/test_human_dom_focus_state.py -v`
Expected: PASS（6/6）

- [ ] **Step 5: 提交**

```bash
git add platforms/common/capabilities/human_dom/_bridge.py platforms/common/tests/test_human_dom_focus_state.py
git commit -m "feat(human_dom): bridge focus_state + thread focused (§6.4, StarBeam #188)"
```

---

## Task 2: content.js 焦点上报（`hasFocus` + focus/blur，首帧不丢字段）

**Files:**
- Modify: `platforms/common/capabilities/human_dom/extension/content.js`（`ws.onopen` :71-72、`visibilitychange` :83-84、新增 window focus/blur）
- Test: `platforms/common/tests/test_content_js_focus_report.mjs`（新建，仿 `test_content_js_visibletext.mjs` 的 node-vm 骨架）

- [ ] **Step 1: 写失败测试**

Create `platforms/common/tests/test_content_js_focus_report.mjs`:

```javascript
// 验 content.js 焦点上报: 首帧不丢 profile_id/tab_id/url(delta-BLOCKING-1)、report() 带 focused、
// focus/blur/visibilitychange 三事件都触发上报、切应用(hidden=false 但 hasFocus=false)时 focused 翻 false。
// 运行: node tests/test_content_js_focus_report.mjs
import { readFileSync } from "fs";
import vm from "vm";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
let src = readFileSync(join(here, "../capabilities/human_dom/extension/content.js"), "utf8");
src = src.replace(/__AF_PORT__/g, "8779").replace(/"__AF_PROFILE_ID__"/g, '"op-x"');

let sent = [];                 // 捕获所有 ws.send 的 JSON
const winHandlers = {};        // 捕获 window.addEventListener
const docHandlers = {};        // 捕获 document.addEventListener
let hasFocusVal = true, hiddenVal = false;

const ctx = {
  WebSocket: function () { this.readyState = 1; this.send = (s) => sent.push(JSON.parse(s)); },
  document: {
    get hidden() { return hiddenVal; },
    hasFocus: () => hasFocusVal,
    addEventListener: (ev, fn) => { docHandlers[ev] = fn; },
    querySelectorAll: () => [],
  },
  location: { href: "https://mp.weixin.qq.com/x" },
  setTimeout: () => {},
  window: { addEventListener: (ev, fn) => { winHandlers[ev] = fn; } },
  screenX: 0, screenY: 0, innerWidth: 0, innerHeight: 0, outerWidth: 0, outerHeight: 0,
  devicePixelRatio: 1, scrollX: 0, scrollY: 0,
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
// 触发 ws.onopen(connect() 里 new WebSocket 后需手动调, 因 stub 不自动触发)
ctx.__ws_open_trigger && ctx.__ws_open_trigger();

let failed = 0;
const check = (cond, msg) => { if (!cond) { console.error(`FAIL: ${msg}`); failed++; } };

// 首帧(auth): 必须保留 profile_id/tab_id/url + 带 focused
const auth = sent.find((m) => m.type === "auth");
check(auth && auth.profile_id === "op-x", "首帧保留 profile_id(不被折进窄 payload)");
check(auth && auth.tab_id != null && auth.url === "https://mp.weixin.qq.com/x", "首帧保留 tab_id/url");
check(auth && auth.focused === true, "首帧带 focused=true(初始 hasFocus)");

// window focus/blur/visibilitychange 三事件都注册了
check(typeof winHandlers.focus === "function", "注册了 window focus");
check(typeof winHandlers.blur === "function", "注册了 window blur");
check(typeof docHandlers.visibilitychange === "function", "注册了 visibilitychange");

// 切到别的应用: hidden 仍 false, hasFocus 翻 false → blur 事件上报 focused=false
sent = []; hasFocusVal = false;
winHandlers.blur();
const upd = sent[sent.length - 1];
check(upd && upd.type === "active" && upd.focused === false && upd.active === true,
  "切应用: 更新帧 focused=false 而 active(=!hidden) 仍 true(§6.4 取证分叉)");

if (failed) { console.error(`${failed} 条失败`); process.exit(1); }
console.log("content.js 焦点上报测试全过");
```

> 注：stub 的 `WebSocket` 不会自动触发 `onopen`。实现里 `connect()` 赋值 `ws.onopen` 后，需要测试能手动触发它——见 Step 3 让 `connect()` 把 open 逻辑暴露成可调（最简单：`ws.onopen` 赋值后测试直接 `ctx` 拿不到 ws；故让 stub 的 `WebSocket` 构造里保存实例、并在赋值 onopen 后由测试调用）。**Step 3 采用更稳的写法：把首帧发送抽成具名函数 `sendAuth()`，`ws.onopen=sendAuth`，测试通过捕获到的 `onopen` 触发**（改测试 stub 记录 `this` 到 `ctx.__last_ws`，`ctx.__ws_open_trigger = () => ctx.__last_ws.onopen()`）。

修正测试 stub（替换上面 `WebSocket` 与触发行）：

```javascript
  WebSocket: function () { ctx.__last_ws = this; this.readyState = 1; this.send = (s) => sent.push(JSON.parse(s)); },
```
```javascript
ctx.__last_ws.onopen();   // 手动触发首帧
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node platforms/common/tests/test_content_js_focus_report.mjs`
Expected: FAIL（首帧无 `focused` / 无 window focus/blur handler）

- [ ] **Step 3: 改 `content.js`**

`ws.onopen`（:71-72）追加 `focused`（**保留全部原字段**）：

```javascript
  ws.onopen = ()=> ws.send(JSON.stringify({type:"auth", token:TOKEN, profile_id:PROFILE_ID,
    tab_id:String(Date.now()), url:location.href, active:!document.hidden, focused:document.hasFocus()}));
```

抽 `report()` 辅助 + 三事件挂它（替换 :82-85 的 visibilitychange 块）：

```javascript
// 前后台/焦点切换时重报 active+focused(§6.4): visibilitychange 不在切【应用】时触发,
// 故 window focus/blur 也挂, 否则切应用后 focused 陈旧。窄帧不带 profile_id 等(ws 已在桥端标识 client)。
function report(){ if(ws && ws.readyState===1)
  ws.send(JSON.stringify({type:"active", active:!document.hidden, focused:document.hasFocus()})); }
document.addEventListener("visibilitychange", report);
window.addEventListener("focus", report);
window.addEventListener("blur", report);
```

（仍只读，未加任何 `.click()`/`.value=`/`dispatchEvent`，守 `content.js:1` 铁律。）

- [ ] **Step 4: 跑测试确认通过 + 既有 content.js 测试不回归**

Run: `node platforms/common/tests/test_content_js_focus_report.mjs`
Expected: PASS

Run: `node platforms/common/tests/test_content_js_visibletext.mjs && node platforms/common/tests/test_content_js_accessible_name.mjs`
Expected: 两个既有测试仍全过

- [ ] **Step 5: 提交**

```bash
git add platforms/common/capabilities/human_dom/extension/content.js platforms/common/tests/test_content_js_focus_report.mjs
git commit -m "feat(human_dom): content.js report focused via hasFocus + focus/blur (§6.4)"
```

---

## Task 3: `human_dom_focused` 工具 + `human_dom_status` 带 focused

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_human_dom.py`（`register` 内注册工具 :156+、返回列表 :final；`compute_status`/`build_status`）
- Test: `platforms/common/tests/test_human_dom_focused_tool.py`（新建，仿 `test_human_dom_profile_resolution.py` 的 FakeMcp/FakeBridge）

- [ ] **Step 1: 写失败测试**

Create `platforms/common/tests/test_human_dom_focused_tool.py`:

```python
"""human_dom_focused: 带外前台检查工具。三态 true/false/None → reason 分类; 省略 profile 走 resolve。"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities", "human_dom"))
from _human_dom import HumanDomCapability


class FakeBridge:
    def __init__(self, focus_map, active_ops=None):
        self._focus = focus_map                      # profile_id -> bool|None
        self._active_ops = active_ops or []          # active_operator_profile 用
        self._clients = []
    def focus_state(self, pid): return self._focus.get(pid)
    def active_operator_profile(self): return self._active_ops[0] if self._active_ops else None


class FakeMcp:
    def __init__(self): self.tools = {}
    def tool(self, fn): self.tools[fn.__name__] = fn; return fn


def _cap(focus_map, active_ops=None):
    cap = HumanDomCapability(FakeBridge(focus_map, active_ops), tap_fn=lambda *a: None, fill_fn=lambda *a: None)
    mcp = FakeMcp(); cap.register(mcp); return mcp


def _run(coro): return asyncio.get_event_loop().run_until_complete(coro)


def test_focused_true():
    mcp = _cap({"op-x": True})
    r = _run(mcp.tools["human_dom_focused"](profile="~/.fleet/op-x-publisher"))
    # resolve_profile_id 会把路径 hash 成 <slug>-<h>, 这里用显式 pid 直接命中需对齐; 用 active operator 路径更稳:
    # 见 test_focused_true_via_active_operator


def test_focused_true_via_active_operator():
    mcp = _cap({"op-x": True}, active_ops=["op-x"])
    r = _run(mcp.tools["human_dom_focused"](profile=""))       # 省略 → resolve 到活跃 operator op-x
    assert r["ok"] is True and r["focused"] is True and r["profile"] == "op-x" and r["reason"] == "focused"


def test_not_focused():
    mcp = _cap({"op-x": False}, active_ops=["op-x"])
    r = _run(mcp.tools["human_dom_focused"](profile=""))
    assert r["focused"] is False and r["reason"] == "not_focused"


def test_no_signal_none():
    mcp = _cap({"op-x": None}, active_ops=["op-x"])
    r = _run(mcp.tools["human_dom_focused"](profile=""))
    assert r["focused"] is None and r["reason"] == "no_signal"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python -m pytest tests/test_human_dom_focused_tool.py -v`
Expected: FAIL（无 `human_dom_focused` 工具）

- [ ] **Step 3: 改 `_human_dom.py`**

在 `register` 里、`human_dom_status` 之后注册新工具，并把 `human_dom_focused` 加进返回列表：

```python
        @mcp.tool
        async def human_dom_focused(profile: str = "") -> dict:
            """前台检查(带外, Class C, 取代截图目测作首选): 该 profile 活跃 tab 是否真持焦点(document.hasFocus())。
            focused=True → 可直接 OS 操作; False → human_browser_open(profile, activate=True) 拉回后复查;
            None → 拿不到信号(未连桥 / chrome:// / 非 Chrome / 旧扩展未上报) → 调用方回落 take_screenshot(spec §5.2/§6.4)。"""
            pid = resolve_profile_id(bridge, profile)
            f = bridge.focus_state(pid)
            reason = "focused" if f is True else ("not_focused" if f is False else "no_signal")
            return {"ok": True, "focused": f, "profile": pid, "reason": reason}
```

返回列表加 `"human_dom_focused"`：

```python
        return ["human_dom_locate", "human_dom_tap", "human_dom_fill", "human_dom_status", "human_dom_focused"]
```

`human_dom_status` 带 focused（观测）——`compute_status` 加 `focus_by_id` 形参，`build_status` 的 per-profile 明细透传。最小改：在 `human_dom_status` 里组 focus 映射并塞进 profiles 明细（不改 compute_status 签名的低风险写法）：

```python
        async def human_dom_status() -> dict:
            """... (docstring 不变) ..."""
            connected = {c["profile_id"] for c in list(bridge._clients)}
            st = build_status(compute_status("~/.fleet/human-dom-ext", connected_ids=connected))
            for p in st["profiles"]:                 # 观测: 每 profile 带上 focused(带外查, 不影响 installed/connected)
                if p.get("connected"):
                    p["focused"] = bridge.focus_state(p["profile_id"])
            return st
```

> 注：`build_status`/`compute_status` 的 profiles 明细含 `profile_id` 与 `connected` 键；若字段名不符，读 `_human_dom.py:64 compute_status` 对齐后再填。

- [ ] **Step 4: 跑测试确认通过 + 既有 human_dom 测试不回归**

Run: `cd platforms/common && python -m pytest tests/test_human_dom_focused_tool.py tests/test_human_dom_profile_resolution.py -v`
Expected: 新测试 PASS，profile 解析既有测试全过

- [ ] **Step 5: 提交**

```bash
git add platforms/common/capabilities/human_dom/_human_dom.py platforms/common/tests/test_human_dom_focused_tool.py
git commit -m "feat(human_dom): add human_dom_focused out-of-band foreground check (§4.4)"
```

---

## Task 4: `human_browser_open` 加 `activate` + 复用零重激活 + mac `-g` + 字段

**Files:**
- Modify: `platforms/common/capabilities/browser/_human_browser.py`（`_maybe_maximize` :129-138、工具签名 :338、default-daily :367-378、复用 :401-411、冷启动 :444-445）
- Test: `platforms/common/tests/test_human_browser_activate.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `platforms/common/tests/test_human_browser_activate.py`:

```python
"""human_browser_open activate 分派: 复用+activate=False 不调 foreground; 复用+True 调; 冷启动传 activate。
   字段 activated/maximized 反映真实动作(不用 bool(fn))。用 fake foreground_fn 记录调用序列。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities", "browser"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities"))
import _human_browser as hb


def _install_capability(monkeypatch, foreground_calls, warm):
    cap = hb.HumanBrowserCapability(bridge_port=None,
                                    maximize_fn=lambda udd, activate=True: (foreground_calls.append((udd, activate)) or True))
    # 稳定桩: 定位 profile、探冷热、不真起 Chrome
    monkeypatch.setattr(hb, "_chrome_binary", lambda: "/fake/chrome")
    monkeypatch.setattr(hb, "_resolve_profile", lambda p: ("/udd/x", None, "keyx"))
    monkeypatch.setattr(hb, "_detect_reuse", lambda key, udd, _probe=None: ({"port": None, "via": "in-process"} if warm else None))
    monkeypatch.setattr(hb, "_ensure_human_dom_ext", lambda profile, bp: None)
    monkeypatch.setattr(hb.subprocess, "Popen", lambda *a, **k: type("P", (), {"poll": lambda self: None})())
    monkeypatch.setattr(hb, "_warm_navigate", lambda port, url: "no-url")
    class _Mcp:
        def __init__(self): self.tools = {}
        def tool(self, fn): self.tools[fn.__name__] = fn; return fn
    m = _Mcp(); cap.register(m); return m.tools["human_browser_open"]


def test_warm_default_no_foreground(monkeypatch):
    calls = []
    open_ = _install_capability(monkeypatch, calls, warm=True)
    r = open_(url="", profile="~/.fleet/op-x")             # activate 默认 False
    assert calls == []                                      # 复用+默认 → 零调用(P0 治 #188)
    assert r["reused"] is True and r["maximized"] is False and r["activated"] is False


def test_warm_activate_true_calls_foreground(monkeypatch):
    calls = []
    open_ = _install_capability(monkeypatch, calls, warm=True)
    r = open_(url="", profile="~/.fleet/op-x", activate=True)
    assert calls == [("/udd/x", True)]                     # 复用+activate=True → 调 (udd, True)
    assert r["maximized"] is True and r["activated"] is True


def test_cold_passes_activate(monkeypatch):
    calls = []
    open_ = _install_capability(monkeypatch, calls, warm=False)
    open_(url="", profile="~/.fleet/op-x", activate=False)
    assert calls == [("/udd/x", False)]                    # 冷启动 → 调 (udd, False) 非激活最大化
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python -m pytest tests/test_human_browser_activate.py -v`
Expected: FAIL（`human_browser_open` 不认 `activate` / 复用无条件调 maximize）

- [ ] **Step 3: 改 `_human_browser.py`**

(a) `_maybe_maximize`（:129-138）改为返回 bool、接受 activate 的 best-effort 包装：

```python
def _maybe_foreground(fn, udd: str, activate: bool) -> bool:
    """起窗后调平台注入的窗口置前/最大化。activate=True: 激活最大化; False: 非激活最大化(win)。
    返回是否真的调用生效(供 activated/maximized 如实置)。无 fn(mac/linux)→False。best-effort, 永不抛。"""
    if not fn:
        return False
    try:
        return bool(fn(udd, activate))
    except Exception:
        return False
```

(b) 工具签名（:338）加 `activate`：

```python
        def human_browser_open(url: str = "", profile: str = "", activate: bool = False) -> dict:
```

（docstring 末补一句：`activate=False(默认)不抢前台; 即将在浏览器里动手前传 activate=True 把该 profile 的 Chrome 拉前台(见 using-human-browser 的查→不对才拉循环)。`）

(c) default-daily mac 路径（:367-370）按 activate 加 `-g`：

```python
                    if sys.platform == "darwin":
                        bg = [] if activate else ["-g"]     # -g: 不抢前台(spec §6.2)
                        args = ["open"] + bg + ["-a", "Google Chrome"] + ([url] if url else [])
                        subprocess.run(args, timeout=15, check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

default-daily 返回加 `"activated": None`（该路径无法确定性控前台，spec §6.3）：

```python
                    return {"ok": True, "opened": url or "(chrome)", "profile": "(default-daily)",
                            "reused": False, "activated": None,   # Chrome 单例转发不受控(§6.3)
                            "note": ...}   # note 原文追加: "(默认 Chrome 前台由 Chrome 自身控制; 需后台运行请用专用 profile。)"
```

(d) 复用路径（:401-411）——**activate=False 不调 foreground**：

```python
                if warm is not None:
                    nav = _warm_navigate(warm["port"], url)
                    acted = _maybe_foreground(self._maximize_fn, udd, activate) if activate else False
                    print(f"[human_browser] reuse profile={key} via={warm['via']} nav={nav} activate={activate}", file=sys.stderr)
                    return {
                        "ok": True, "opened": url or "(chrome)", "profile": key,
                        "reused": True, "reuse_via": warm["via"],
                        "note": "该 profile 的 Chrome 已在运行, 复用现有窗口(未重启浏览器、未重装扩展、未新开标签)。"
                                + _WARM_NAV_NOTE.get(nav, ""),
                        "maximized": acted, "activated": acted and activate,
                    }
```

(e) 冷启动路径（:444-445）——传 activate：

```python
                acted = _maybe_foreground(self._maximize_fn, udd, activate)
                resp["maximized"] = acted
                resp["activated"] = acted and activate
```

（`self._maximize_fn` 属性名与注入 kwarg `maximize_fn` **保持不变**——避免跨文件改名炸中间态；仅其调用签名从 `(udd)` 变 `(udd, activate)`，由 Task 5 的 win 函数 `activate` 默认 True 兜住兼容。）

- [ ] **Step 4: 跑测试确认通过 + 既有 human_browser 测试不回归**

Run: `cd platforms/common && python -m pytest tests/test_human_browser_activate.py tests/test_human_browser_profile.py -v`
Expected: 新测试 PASS，既有 profile 测试全过

- [ ] **Step 5: py_compile 兜 host 侧 + 提交**

Run: `python -m py_compile platforms/common/capabilities/browser/_human_browser.py`
Expected: 无输出（通过）

```bash
git add platforms/common/capabilities/browser/_human_browser.py platforms/common/tests/test_human_browser_activate.py
git commit -m "feat(human_browser): add activate flag, reuse zero-reactivation, mac -g (§4.1/§4.2/§6.2, #188)"
```

---

## Task 5: Windows `foreground_chrome_window_for_udd(udd, activate)` 非激活最大化

**Files:**
- Modify: `platforms/windows/server/win_input.py`（`maximize_chrome_window_for_udd` :104-182 → 加 `activate` 分支）
- Modify: `platforms/windows/server/win_device_mcp.py:1027`（注入指向新函数名）
- 无本机单测（host-only Win32）→ py_compile + test-win11 真机（Task 8 验收）

- [ ] **Step 1: 改 `win_input.py`**

函数改签名 `foreground_chrome_window_for_udd(udd, activate: bool = True)`（保留旧名做别名以防他处引用），最大化那段（:176-182）按 activate 分流：

```python
    ok = False
    for h in hwnds:
        try:
            if activate:
                user32.ShowWindow(h, SW_MAXIMIZE)                 # 激活最大化(旧行为)
            else:
                _maximize_no_activate(user32, h)                  # 非激活: 填工作区不夺焦点
            ok = True
        except Exception:
            pass
    return ok


# 旧名别名(他处若有引用不炸); 新名语义更准
maximize_chrome_window_for_udd = foreground_chrome_window_for_udd
```

新增 `_maximize_no_activate`（HWND_TOP + SWP_NOACTIVATE，**不加 SWP_NOZORDER**；取**目标窗所在**屏工作区，delta-2a/2b）：

```python
def _maximize_no_activate(user32, hwnd):
    """把窗口填满【它所在显示器】的工作区, 提到最前但不夺键盘焦点(spec §6.1)。
    HWND_TOP 提最前 + SWP_NOACTIVATE 不激活, 二者不冲突; 【不加 SWP_NOZORDER】(它会让 HWND_TOP 失效)。
    显示器用 MonitorFromWindow(DEFAULTTONEAREST) 取窗口实际所在屏(绝不用 MonitorFromPoint 主屏, 否则副屏窗口被搬到主屏)。"""
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    MONITOR_DEFAULTTONEAREST = 2
    HWND_TOP = 0
    SWP_NOACTIVATE = 0x0010
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return
    w = mi.rcWork.right - mi.rcWork.left
    h = mi.rcWork.bottom - mi.rcWork.top
    user32.SetWindowPos(hwnd, HWND_TOP, mi.rcWork.left, mi.rcWork.top, w, h, SWP_NOACTIVATE)
```

- [ ] **Step 2: 改注入点 `win_device_mcp.py:1027`**

```python
_cap_registry.add(HumanBrowserCapability(bridge_port=_bridge_port, maximize_fn=foreground_chrome_window_for_udd))
```

（kwarg 仍叫 `maximize_fn`——见 Task 4 (e) 的说明，不跨文件改名。确保 `foreground_chrome_window_for_udd` 已从 `win_input` 导入：检查文件顶部 import，把 `maximize_chrome_window_for_udd` 的导入换/加成新名。）

- [ ] **Step 3: py_compile 两个文件**

Run:
```bash
python -m py_compile platforms/windows/server/win_input.py platforms/windows/server/win_device_mcp.py
```
Expected: 无输出（通过）

> 逻辑正确性（非激活是否真不抢焦点、多屏工作区是否取对）**留 Task 8 test-win11 真机验**——Win32 在 Linux 无法执行。

- [ ] **Step 4: 提交**

```bash
git add platforms/windows/server/win_input.py platforms/windows/server/win_device_mcp.py
git commit -m "feat(win): foreground_fn non-activating maximize (HWND_TOP+SWP_NOACTIVATE, MonitorFromWindow) §6.1"
```

---

## Task 6: 仓内两份 SKILL.md 迁移为"查→不对才拉"（组粒度 + 版本先行三态回落）

**Files:**
- Modify: `platforms/common/skills/using-human-browser/SKILL.md`（Workflow 节 :30-35、"exclusive screen" :44）
- Modify: `platforms/common/skills/using-human-dom/SKILL.md`（工作流节）
- 无自动化测试 → 过文档 QA subagent（Task 7）

- [ ] **Step 1: 改 `using-human-browser/SKILL.md`**

`## Workflow` 节（:30-35）把"open → screenshot → tap"改为带前台检查的循环：

```markdown
## Workflow (screenshot + OS input, NOT DOM)

1. `human_browser_open(url, profile=...)` — launches/focuses the real Chrome. **默认不抢前台**（`activate=False`）；即将在浏览器里动手前才 `activate=True`。
2. **动手前查前台（查→不对才拉，按【组】非逐帧）**：一组无中断连续动作的**组首**、以及任何等待/加载/跳页/重试之后：
   - `human_dom_focused(profile=...)` → `focused=true` 直接操作；`false` 或 `None`/工具不存在/报错 → 见下。
   - `focused=false` → `human_browser_open(profile=..., activate=True)` 拉回 → 复查 → 操作。
   - `None` / 拿不到（未连/`chrome://`/非 Chrome）/ **该工具不存在或调用报错（旧 server）** → 回落 `take_screenshot` 目测前台，别卡住别重试。
3. `take_screenshot` → `tap(x,y)`/`type_text`/`press_key` — 操作。
4. Re-`take_screenshot` 确认结果、定位下一目标。
```

删除/改写 `:44` 的"exclusive screen"独占假设：

```markdown
- **Shared screen aware**: human_browser drives the physical mouse/keyboard on a machine the user may also be using. Do NOT routinely grab foreground; before each action-group verify foreground is your target browser (step 2). 走错窗口＝往别的应用敲字（数据错发），故动手前必查。
```

- [ ] **Step 2: 改 `using-human-dom/SKILL.md`**

在其"工作流"节，`human_dom_tap`/`human_dom_fill`（Class A、OS 级）之前补同一条前台检查循环（引用 `human_dom_focused`），并注明：省略 profile 时 `human_dom_focused` 与 locate/tap/fill 走同一 `resolve_profile_id`。措辞与 using-human-browser 一致（DRY：可写"前台检查循环见 using-human-browser step 2"）。

- [ ] **Step 3: 自检 grep（无自动化测试，人工确认关键串在位）**

Run:
```bash
grep -n "human_dom_focused\|查→不对才拉\|activate=True" platforms/common/skills/using-human-browser/SKILL.md platforms/common/skills/using-human-dom/SKILL.md
```
Expected: 两文件都出现 `human_dom_focused` 与前台检查循环措辞

- [ ] **Step 4: 提交**

```bash
git add platforms/common/skills/using-human-browser/SKILL.md platforms/common/skills/using-human-dom/SKILL.md
git commit -m "docs(skills): migrate workflow to verify-then-activate loop (group-granularity, §5.2/§七)"
```

---

## Task 7: 质量门禁——code-review + 文档 QA（charter review-gate）

**Files:** 无改动（除非发现问题）

- [ ] **Step 1: 派 code-reviewer 审 Task 1-5 的代码改动**

对着 spec 审 `_bridge.py`/`content.js`/`_human_dom.py`/`_human_browser.py`/`win_input.py`：重点 focus_state 的 `.get()` 无默认（⑤）、复用零重激活、首帧字段不丢、Win32 flag（无 SWP_NOZORDER、MonitorFromWindow）。修掉阻断项并复验。

- [ ] **Step 2: 派文档/本地化 QA 审两份 SKILL.md**

确认操作循环口径与 spec §五 一致、组粒度与三态回落写清、无夹英文违反用户章程（中文叙述）。修掉问题。

- [ ] **Step 3: 全量本机测试回归**

Run:
```bash
cd platforms/common && python -m pytest tests/ -q
node tests/test_content_js_focus_report.mjs && node tests/test_content_js_visibletext.mjs && node tests/test_content_js_accessible_name.mjs
```
Expected: 全绿

- [ ] **Step 4: 提交（若有修）**

```bash
git add -A && git commit -m "fix: address code-review + doc-QA on foreground activation (#188)"
```

---

## Task 8: test-win11 真机联合验收（走 spec §十 checklist）

**前置：** 在信箱通知 StarBeam「实现到可验状态」；StarBeam 开 test-win11；**先确认其说明书回填时序**（按约定：验收通过后才回填，故本轮用旧 doc 或临时新 doc 手动验）。

- [ ] **Step 1: 部署本分支到 test-win11**（更新 clone + 重启 `MCP-WinDevice`，参照 win-device 更新流程）
- [ ] **Step 2: 逐条走 spec §十 功能 checklist**（复现 #188 基线 / 常态零 activate / 扩展焦点分叉 true·false·None / 截图兜底 / 走错窗自救 / activate 复用行为 / 冷启动非激活最大化观感 / warm-reuse 数据错发防线 / 组粒度 / 旧 server+新说明书三态回落 / default-daily 缺口观测）
- [ ] **Step 3: mac 侧抽验**（macmini：`open -g` 后台打开、复用不抢——mac 复用本就 no-op）
- [ ] **Step 4: 验收结论回信箱**，据结果决定合并 main + tag（延续 v0.8.x-alpha）+ registry 发布（外发动作，落地前与用户确认）

---

## Self-Review（against spec）

- **§4.1/§4.2 activate 契约 + 字段** → Task 4（含 default-daily `activated=None`）✅
- **§4.3 foreground_fn(udd,activate)->bool + best-effort 包装** → Task 4(a) `_maybe_foreground` ✅
- **§4.4 human_dom_focused** → Task 3 ✅
- **§5.1 分栏（含 hover_preview/vision_locate_image）** → Task 6 SKILL 迁移体现（分栏是文档口径，代码无对应）✅
- **§5.2 操作循环 + 组粒度** → Task 6 ✅
- **§6.1 Win32 非激活最大化（HWND_TOP+SWP_NOACTIVATE、MonitorFromWindow、无 NOZORDER）** → Task 5 ✅
- **§6.2 mac -g** → Task 4(c) ✅
- **§6.3 default-daily activated=None** → Task 4(c) ✅
- **§6.4 扩展焦点实现 + 局限⑤(.get 无默认)/⑦(三态回落)** → Task 1(focus_state None 语义)/Task 2(content.js)/Task 6(SKILL 三态)✅
- **§七 仓内两份 SKILL 迁移 + 分离守卫** → Task 6 + Task 1 分离守卫测试 ✅
- **§九 测试策略** → 各 Task 的本机 TDD + Task 5 host-only py_compile ✅
- **§十 验收 checklist** → Task 8 ✅

**Placeholder scan**：无 TBD/TODO；host-only 逻辑（Task 5）明确标注真机验、非占位。
**Type consistency**：`focus_state`/`focused`/`activate`/`_maybe_foreground`/`foreground_chrome_window_for_udd` 跨任务命名一致；`maximize_fn` kwarg 有意不改名（Task 4(e)/Task 5 已注明）。
