# human_dom profile 解析硬化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 治 human_dom 省略 profile 时的解析抖动（P6 真机确证根因）——省略 profile 不再硬默认 "default"，而是可靠解析到桥当前活跃的 operator profile；并补 E2 fill 失败重试一次。

**Architecture:** 主项自包含在桥 + 工具解析层：`DomBridge.active_operator_profile()`（连接客户端注册表=当前真活跃证据）+ `resolve_profile_id(bridge, profile)`（显式不变、省略问桥）+ 响应加 `resolved_profile` 可观测。次项：`human_dom_fill` 主体抽模块级 `_do_fill` + 失败重试一次（re-tap 复用首次 center）。E1/E3 已在 59fe476 实现（不重写，单测守）。

**Tech Stack:** Python（纯逻辑，`_bridge.py`/`_human_dom.py`/`_ident.py` 不依赖 numpy/cv2）；pytest + asyncio。**全部本机可跑 TDD**（既有 human_dom 测试就是纯 Python）。

**Spec:** `docs/superpowers/specs/2026-07-07-human-dom-profile-resolution-design.md`（architect 已审，1 BLOCKING 已修 + 6 非阻断已吸收）。

**语义收紧（已与用户确认）**：operator tab 与日常 default Chrome 同时连桥时，省略 profile 从「default」改指「operator」（有意、治 P6，非回归；「零回归」仅限无 operator 连桥；日常 default 用显式 profile 逃生）。

---

## 文件结构

**修改**
- `platforms/common/capabilities/human_dom/_bridge.py`：`import time`；`register`/`set_active` 记 `last_active_ts`；加 `active_operator_profile()`。
- `platforms/common/capabilities/human_dom/_ident.py`：加 `resolve_profile_id(bridge, profile_str)`。
- `platforms/common/capabilities/human_dom/_human_dom.py`：`import resolve_profile_id`；locate/tap 用它 + 成功加 `resolved_profile`；`human_dom_fill` 主体抽 `_do_fill` + E2 重试。

**新建**
- `platforms/common/tests/test_human_dom_profile_resolution.py`：桥解析 + resolve_profile_id + 工具接线 + _do_fill 重试（纯 Python 本机可跑）。

**不动**：`content.js`（E1/E3 已实现、不重写）、`_geom.py`、`_setup.py`、`_locate.py`（resolve_locate 不改；no_tab 分支已带 `profile` 字段）、vision、`_os_fill`、manifest（不加 all_frames，E4 后置）。

---

## Task 0: 建实现分支

- [ ] **Step 1: 从最新 main 建分支**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git checkout main && git pull
git checkout -b feat/human-dom-profile-resolution
```

---

## Phase A — 实现（本机 Python TDD）

### Task 1: 桥 `active_operator_profile()` + `last_active_ts`

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_bridge.py`
- Test: `platforms/common/tests/test_human_dom_profile_resolution.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# platforms/common/tests/test_human_dom_profile_resolution.py
"""human_dom profile 解析硬化: 桥活跃 operator 解析 + resolve_profile_id + 工具接线 + _do_fill 重试。
纯 Python 本机可跑(不依赖 numpy)。运行: cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -v"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._bridge import DomBridge


class FakeWS:
    async def send_json(self, m): pass


def _reg(b, ws, pid, active=True, ts=0.0):
    """register 一个客户端并设显式 last_active_ts(确定性排序)。"""
    b.register(ws, profile_id=pid, tab_id="t", url="u", active=active)
    for c in b._clients:
        if c["ws"] is ws:
            c["last_active_ts"] = ts


def test_active_operator_unique():
    b = DomBridge()
    _reg(b, FakeWS(), "default", ts=5.0)
    _reg(b, FakeWS(), "op-aaa", ts=1.0)
    assert b.active_operator_profile() == "op-aaa"        # 唯一 operator, 忽略 default


def test_active_operator_most_recent():
    b = DomBridge()
    _reg(b, FakeWS(), "op-aaa", ts=1.0)
    _reg(b, FakeWS(), "op-bbb", ts=9.0)                   # 更近活跃
    assert b.active_operator_profile() == "op-bbb"


def test_active_operator_prefers_active_over_ts():
    b = DomBridge()
    _reg(b, FakeWS(), "op-old", active=True, ts=1.0)
    _reg(b, FakeWS(), "op-inactive", active=False, ts=9.0)  # ts 更近但非 active
    assert b.active_operator_profile() == "op-old"       # active 优先于 ts


def test_active_operator_none_when_only_default():
    b = DomBridge()
    _reg(b, FakeWS(), "default", ts=1.0)
    assert b.active_operator_profile() is None            # 仅 default → None → 调用方回退 default


def test_active_operator_none_when_empty():
    assert DomBridge().active_operator_profile() is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: FAIL — `AttributeError: 'DomBridge' object has no attribute 'active_operator_profile'`

- [ ] **Step 3: 写实现**（`_bridge.py`）

① 顶部 import 加 `time`：把 `import asyncio, hmac, itertools, threading` 改为
```python
import asyncio, hmac, itertools, threading, time
```

② `register`（现 `:19-22`）加 `last_active_ts`：
```python
    def register(self, ws, profile_id, tab_id, url, active):
        with self._lock:
            self._clients.append({"ws": ws, "profile_id": profile_id or "default",
                                  "tab_id": tab_id, "url": url, "active": active,
                                  "last_active_ts": time.monotonic()})
```

③ `set_active`（现 `:27-32`）活跃时刷新 `last_active_ts`：
```python
    def set_active(self, ws, active):
        """content script 报前后台切换 → 更新该 client 的 active(修多 tab 派发)。"""
        with self._lock:
            for c in self._clients:
                if c["ws"] is ws:
                    c["active"] = bool(active)
                    if active:
                        c["last_active_ts"] = time.monotonic()  # 最近活跃 → 省略 profile 解析优先它
```

④ 在 `_active`（现 `:34-40`）之后加 `active_operator_profile`：
```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/_bridge.py platforms/common/tests/test_human_dom_profile_resolution.py
git commit -m "feat(profile-r): 桥 active_operator_profile()+last_active_ts(省略 profile 解析源, 修 P6)"
```

---

### Task 2: `resolve_profile_id(bridge, profile_str)`

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_ident.py`
- Test: 追加到 `test_human_dom_profile_resolution.py`

- [ ] **Step 1: 追加失败测试**

```python
# --- resolve_profile_id ---
from capabilities.human_dom._ident import resolve_profile_id, human_dom_profile_id


class _FakeBridge:
    def __init__(self, op): self._op = op; self._clients = []
    def active_operator_profile(self): return self._op


class _RaisingBridge:
    _clients = []
    def active_operator_profile(self):
        raise AssertionError("显式 profile 不该问桥")


def test_resolve_explicit_does_not_consult_bridge():
    # 显式 profile → 走 human_dom_profile_id, 不问桥(RaisingBridge 若被问会抛)
    assert resolve_profile_id(_RaisingBridge(), "~/.fleet/foo") == human_dom_profile_id("~/.fleet/foo")


def test_resolve_omitted_uses_operator():
    assert resolve_profile_id(_FakeBridge("op-aaa"), "") == "op-aaa"
    assert resolve_profile_id(_FakeBridge("op-aaa"), None) == "op-aaa"
    assert resolve_profile_id(_FakeBridge("op-aaa"), "   ") == "op-aaa"   # 纯空白视为省略


def test_resolve_omitted_falls_back_default():
    assert resolve_profile_id(_FakeBridge(None), "") == "default"          # 无 operator → default
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_profile_id'`

- [ ] **Step 3: 写实现**（`_ident.py` 末尾追加）

```python
def resolve_profile_id(bridge, profile_str: "str | None") -> str:
    """显式 profile → human_dom_profile_id(行为完全不变); 省略/纯空白 → 桥的活跃 operator profile,
    无则 "default"(保默认日常 Chrome 用例)。修 P6: 省略 profile 不再硬默认 default(错落无 tab 的
    default), 而继承当前活跃 operator(桥连接客户端=真活跃证据)。"""
    s = (profile_str or "").strip()
    if s:
        return human_dom_profile_id(s)
    op = bridge.active_operator_profile()
    return op if op else "default"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: PASS（8 passed 总计）

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/_ident.py platforms/common/tests/test_human_dom_profile_resolution.py
git commit -m "feat(profile-r): resolve_profile_id(显式不变, 省略问桥活跃 operator, 无则 default)"
```

---

### Task 3: 接线 `human_dom_locate`/`human_dom_tap` + `resolved_profile`

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_human_dom.py`（import + locate `:139-144` + tap `:146-155`）
- Test: 追加到 `test_human_dom_profile_resolution.py`

- [ ] **Step 1: 追加失败测试**（用 FakeMcp 截获闭包工具）

```python
# --- 工具接线: locate/tap 用 resolve_profile_id + 成功带 resolved_profile ---
from capabilities.human_dom import _human_dom
from capabilities.human_dom._human_dom import HumanDomCapability


class FakeMcp:
    def __init__(self): self.tools = {}
    def tool(self, fn): self.tools[fn.__name__] = fn; return fn   # 捕获原 async fn


def _tools(bridge, tap=None, fill=None):
    cap = HumanDomCapability(bridge, tap_fn=tap or (lambda x, y: None), fill_fn=fill or (lambda s: None))
    m = FakeMcp(); cap.register(m); return m.tools


def test_locate_omitted_resolves_operator_and_marks(monkeypatch):
    async def fake_resolve(bridge, q, css=None, max_results=10, profile_id="default", timeout=3.0):
        fake_resolve.pid = profile_id
        return {"ok": True, "candidates": [{"text": "x", "center": [10, 20], "box": [0, 0, 1, 1]}]}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    tools = _tools(_FakeBridge("op-aaa"))
    r = asyncio.run(tools["human_dom_locate"]("q"))              # 省略 profile
    assert r["ok"] and r["resolved_profile"] == "op-aaa"        # 解析到 operator + 可观测
    assert fake_resolve.pid == "op-aaa"                          # 真的用 operator 去 locate


def test_tap_omitted_resolves_operator_and_marks(monkeypatch):
    async def fake_resolve(bridge, q, css=None, profile_id="default", timeout=3.0):
        return {"ok": True, "candidates": [{"center": [30, 40]}]}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    taps = []
    tools = _tools(_FakeBridge("op-bbb"), tap=lambda x, y: taps.append((x, y)))
    r = asyncio.run(tools["human_dom_tap"]("q"))
    assert r["ok"] and r["tapped"] == [30, 40] and r["resolved_profile"] == "op-bbb"
    assert taps == [(30, 40)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: FAIL — `KeyError: 'resolved_profile'`（现工具用 `human_dom_profile_id(profile)`→"default"、不带 resolved_profile）

- [ ] **Step 3: 写实现**（`_human_dom.py`）

① import（现 `:6` `from ._ident import human_dom_profile_id`）改为：
```python
from ._ident import resolve_profile_id
```

② `human_dom_locate`（现 `:139-144`）：
```python
        @mcp.tool
        async def human_dom_locate(query: str, css: str = "", max_results: int = 10, profile: str = "") -> dict:
            """只读 DOM 定位: 按文字/aria-label/placeholder(或 css)找元素, 返回屏幕坐标候选。
            省略 profile 时解析到当前活跃 operator profile(非硬 default); 成功带 resolved_profile。
            先 human_browser_open 并等页面 load。未命中/桥未连会建议改用 vision_locate。"""
            pid = resolve_profile_id(bridge, profile)
            r = await resolve_locate(bridge, query, css=css or None, max_results=max_results, profile_id=pid)
            if r.get("ok"):
                r["resolved_profile"] = pid
            return r
```

③ `human_dom_tap`（现 `:146-155`）：
```python
        @mcp.tool
        async def human_dom_tap(query: str, nth: int = 0, css: str = "", profile: str = "") -> dict:
            """定位 + OS 级点击(locate+tap 合一缩小漂移窗)。省略 profile 解析到活跃 operator。"""
            pid = resolve_profile_id(bridge, profile)
            r = await resolve_locate(bridge, query, css=css or None, profile_id=pid)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"),
                        "resolved_profile": pid, "suggest": "vision_locate"}
            x, y = r["candidates"][min(nth, len(r["candidates"]) - 1)]["center"]
            tap(int(round(x)), int(round(y)))
            return {"ok": True, "tapped": [int(round(x)), int(round(y))], "resolved_profile": pid}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: PASS（10 passed 总计）

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/_human_dom.py platforms/common/tests/test_human_dom_profile_resolution.py
git commit -m "feat(profile-r): locate/tap 用 resolve_profile_id + 成功带 resolved_profile 可观测"
```

---

### Task 4: `_do_fill` 抽出 + E2 失败重试一次

**Files:**
- Modify: `platforms/common/capabilities/human_dom/_human_dom.py`（加模块级 `_do_fill` + 重写 `human_dom_fill` 闭包 `:157-172`）
- Test: 追加到 `test_human_dom_profile_resolution.py`

- [ ] **Step 1: 追加失败测试**（直接测模块级 `_do_fill`）

```python
# --- _do_fill: E2 失败重试一次(re-tap 复用首次 center) ---

def test_do_fill_retries_once_then_succeeds(monkeypatch):
    async def fake_resolve(bridge, q, css=None, profile_id="default", timeout=3.0):
        return {"ok": True, "candidates": [{"center": [30, 40]}]}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    seq = iter([False, True])                       # 首次 verify 失败, 重试成功
    async def fake_verify(bridge, text, css, profile_id): return next(seq)
    monkeypatch.setattr(_human_dom, "_verify_fill", fake_verify)
    taps = []
    r = asyncio.run(_human_dom._do_fill(object(), lambda x, y: taps.append((x, y)),
                                        lambda s: None, "q", "txt", None, "op-aaa"))
    assert r["ok"] and r["verified"] and r["retried"] is True
    assert r["resolved_profile"] == "op-aaa"
    assert taps == [(30, 40), (30, 40)]             # re-tap 复用首次 center, 两次相同


def test_do_fill_both_fail_returns_verify_failed(monkeypatch):
    async def fake_resolve(bridge, q, css=None, profile_id="default", timeout=3.0):
        return {"ok": True, "candidates": [{"center": [30, 40]}]}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    async def fake_verify(bridge, text, css, profile_id): return False
    monkeypatch.setattr(_human_dom, "_verify_fill", fake_verify)
    taps = []
    r = asyncio.run(_human_dom._do_fill(object(), lambda x, y: taps.append((x, y)),
                                        lambda s: None, "q", "txt", None, "op-aaa"))
    assert r["ok"] is False and r["reason"] == "fill_verify_failed"
    assert r["resolved_profile"] == "op-aaa"
    assert len(taps) == 2                            # 首次 + 重试一次, 不死循环


def test_do_fill_not_found(monkeypatch):
    async def fake_resolve(bridge, q, css=None, profile_id="default", timeout=3.0):
        return {"ok": False, "reason": "no_tab_for_profile", "profile": "op-aaa"}
    monkeypatch.setattr(_human_dom, "resolve_locate", fake_resolve)
    r = asyncio.run(_human_dom._do_fill(object(), lambda x, y: None, lambda s: None,
                                        "q", "txt", None, "op-aaa"))
    assert r["ok"] is False and r["reason"] == "no_tab_for_profile" and r["resolved_profile"] == "op-aaa"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute '_do_fill'`

- [ ] **Step 3: 写实现**（`_human_dom.py`）

① 在 `_verify_fill`（现 `:14`）之后加模块级 `_do_fill`：
```python
async def _do_fill(bridge, tap, fill, query, text, css, pid) -> dict:
    """定位 → tap 聚焦 → OS fill → 回读校验; 失败重试一次(re-tap 复用首次 center、不 re-locate)再降级。
    模块级(非闭包)便于单测。resolved_profile 一路带回可观测。retry 只一次防死循环;
    _os_fill 全选+粘贴覆盖式, re-fill 不追加、无副作用(取证文档实证落字机制本身 work)。"""
    r = await resolve_locate(bridge, query, css=css, profile_id=pid)
    if not r.get("ok") or not r["candidates"]:
        return {"ok": False, "reason": r.get("reason", "not_found"),
                "resolved_profile": pid, "suggest": "vision_locate"}
    x, y = r["candidates"][0]["center"]
    ix, iy = int(round(x)), int(round(y))
    for attempt in range(2):                 # 首次 + 至多重试一次
        tap(ix, iy)                          # 重试复用首次 center(不 re-locate, 避 R3 重排漂移)
        fill(text)
        if await _verify_fill(bridge, text, css=css, profile_id=pid):
            return {"ok": True, "filled_at": [ix, iy], "verified": True,
                    "resolved_profile": pid, "retried": attempt > 0}
    return {"ok": False, "reason": "fill_verify_failed", "suggest": "vision_locate",
            "filled_at": [ix, iy], "resolved_profile": pid}
```

② 重写 `human_dom_fill` 闭包（现 `:157-172`）为薄封装调 `_do_fill`：
```python
        @mcp.tool
        async def human_dom_fill(query: str, text: str, css: str = "", profile: str = "") -> dict:
            """定位 + 点击聚焦 + OS 级填充(全选 + 剪贴板粘贴, 覆盖式, 支持中文) + 回读校验(失败重试一次)。
            省略 profile 解析到活跃 operator。R2(#100): fill 后按填入片段回读, 真落字才 ok:True/verified:True;
            两次都没落字→ ok:False/reason:fill_verify_failed/suggest vision, 不再假成功。带 resolved_profile。"""
            pid = resolve_profile_id(bridge, profile)
            return await _do_fill(bridge, tap, fill, query, text, css or None, pid)
```

- [ ] **Step 4: 跑测试确认通过 + 零回归**

Run: `cd platforms/common && python3 -m pytest tests/test_human_dom_profile_resolution.py tests/test_human_dom_fill.py -q`
Expected: PASS（新文件 13 passed + 既有 test_human_dom_fill 全绿）

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/_human_dom.py platforms/common/tests/test_human_dom_profile_resolution.py
git commit -m "feat(profile-r): human_dom_fill 抽 _do_fill + E2 失败重试一次(re-tap 复用首次 center)"
```

---

### Task 5: 零回归全量 + E1/E3 在案确认

**Files:** 无（只跑既有测试）

- [ ] **Step 1: 跑 human_dom 全量 + content.js E1/E3 守卫**

Run:
```
cd platforms/common
python3 -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_vision.py --ignore=tests/test_vision_locate.py --ignore=tests/test_vision_ocr.py
node tests/test_content_js_visibletext.mjs
```
Expected: common 全量 PASS（含新 13 + 既有 human_dom bridge/locate/fill/geom/status/routing 零回归）；content.js visibleText 5/5（E1 在案，data-placeholder/aria-placeholder 读取未动）。

- [ ] **Step 2: 确认 E1/E3 在案**（只核不改）

Run: `grep -n "data-placeholder\|aria-placeholder\|isEditable\|_editable" platforms/common/capabilities/human_dom/extension/content.js`
Expected: 命中 E1（data-placeholder/aria-placeholder in visibleText）+ E3（isEditable + _editable sort）——确认已实现，本批不重写。

---

## Phase B — 真机验收（用户在场，test-win11 复现 P6）

### Task 6: 真机验收

- [ ] **Step 1: 复现 P6 场景**：`human_browser_open(profile=op-...)` 起 operator profile（登录态公众号编辑器）→ **省略 profile** 调 `human_dom_locate("请在这里输入标题")` → **可靠命中标题编辑体**（不再 no_tab_for_profile）；返回 `resolved_profile` = operator profile。
- [ ] **Step 2: 标题落字**：`human_dom_fill(query="请在这里输入标题", text=...)` **省略 profile** → 落字成功、`verified:True`、带 `resolved_profile`；构造首次 fill 失败（若可）→ 重试后成功 / 或正确 `fill_verify_failed` 降级。
- [ ] **Step 3: 默认日常 Chrome 不回归**：无 operator profile 时（仅默认 Chrome）省略 profile 仍解析 "default"、行为不变。
- [ ] **Step 4: 多 profile 不串线**（若可造双 operator）：显式 profile 精确路由不变（PR#66 不回归）。
- [ ] **Step 5: 记录验收结论**（含 `resolved_profile` 返回值样本）回用户。

---

## 质量门禁与收口（charter）

- [ ] **code-reviewer 审**：Phase A 落完，派 code-reviewer 审 diff（重点：显式 profile 路径零回归、锁内 copy 消脏读、resolved_profile 只成功路径不双字段、E2 只重试一次 re-tap 复用坐标、不碰 content.js/E1/E3/_os_fill）。发现问题先修复复验。
- [ ] **真机验收通过**（Task 6，用户在场）。
- [ ] **合并 + tag**：审过 + 真机过 → squash-merge PR → 打 `v0.8.x-alpha` annotated tag → GitHub Release(prerelease=true)。**合并/发版前与用户确认**（charter 不可逆/外发条款）。

---

## Self-Review（写完计划的自查）

- **Spec 覆盖**：主项 active_operator_profile(§4.1)→Task 1；resolve_profile_id(§4.2)→Task 2；locate/tap 接线+resolved_profile(§4.2)→Task 3；_do_fill+E2 重试(§4.3)→Task 4；E1/E3 在案确认+零回归(§4.3/§1.4)→Task 5；真机验收(§5.2)→Task 6；语义收紧/fresh-open 残留(§1.6/§7)→已在文档与 code-review 项标注。✓
- **占位扫描**：无 TBD。Phase B 真机依赖用户在场已在 GATE 说明。
- **命名/签名一致**：`active_operator_profile()`、`resolve_profile_id(bridge, profile_str)`、`_do_fill(bridge, tap, fill, query, text, css, pid)`、`resolved_profile` 字段、`last_active_ts`——全计划一致；locate/tap/fill 均用 `resolve_profile_id`；_do_fill 的 css 由调用方传 `css or None`。
