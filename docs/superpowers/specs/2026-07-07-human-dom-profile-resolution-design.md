# 设计：human_dom profile 解析硬化（主）+ E1/E2/E3 收尾（次）——治省略 profile 时的解析抖动

> 状态：设计稿（待 architect 审 + 用户 spec 评审后转 writing-plans）· 2026-07-07
> 需求方：AgentHub（`docs/superpowers/specs/2026-07-04-human-dom-prosemirror-locate-readback-requirements.md` + #100 E2E P6 真机取证）
> 落地方：agent-fleet（device 工具 owner）
> 原则：从需求来、回需求中去；改法加法/兜底为主、零回归。取证驱动——本 spec 的主根因是 P6 真机 transcript 取证得来（非需求文档字面）。
> 范围：主项 = human_dom profile 解析硬化（P6 真机确证根因）；次项 = E1/E2/E3 收尾（多数已实现，见 §1.3）；E4 iframe 后置不碰。

---

## 一、需求与取证（P6 真机 transcript 定的根因，两次反转）

### 1.1 观测失败（#100 E2E 10 轮，v0.8.12-alpha）

10/10 发文落草稿箱，但 **P6 轮（caf13db0）发布员 108 turns 填不进公众号标题 → request_help**，重试轮才成。间歇性（1 轮硬失败 + 若干轮靠 OS paste 兜）。

### 1.2 决定性取证（AgentHub 侧查 P6 transcript caf13db0）——根因是 profile 解析，非 E1/非 fill 落字

- `human_browser_open` **带对了 profile**：`args.profile=~/.fleet/op-f218d27a-...-publisher`，返回 `ok:true reused:true reuse_via:debug-port`。浏览器/tab 好、登录态在。
- 但随后 `human_dom_fill(query="请在这里输入标题", text=...)` 与 `human_dom_locate(query="请在这里输入标题")` **都没带 profile 参数** → 返回 `{ok:false, reason:"no_tab_for_profile", profile:"default"}`。**落到了 "default" profile（那里没有 MP tab）。**
- **决定性对照**：成功轮 **P10（d8b70025）** 的 `human_dom_fill(query="请在这里输入标题")` 与 `human_dom_tap(query="首页")` **同样没带 profile**（hasProfile=False），却成功。
- → **根因 = 省略 profile 时的解析不可靠**：P6 落 "default"（no_tab_for_profile 死在解析步、根本没到 DOM 查询/落字）。P10 同样 no-profile 却成，说明**当时桥里有个匹配 "default" 的 tab**（P10 是操作员开在默认 Chrome、还是别的，transcript 未细究）——注意 `_ident.py` 硬返回 "default"、代码**不可能**「继承 operator profile」，所以 P10 的成必是「恰好有 default tab」，不是代码继承。间歇标题失败 = 省略 profile 解析在「桥里有/无匹配 default 的 tab」之间抖。**不是 data-placeholder locate 盲区(E1)，也不是 fill 不落字(根因 b)。修法对 P10 的确切机制鲁棒**（§4.1：有 operator tab 就用它、否则 default，两种情形都对）。

### 1.3 代码机制（取证到确切代码）

- **`_ident.py human_dom_profile_id("")` → 硬返回 `"default"`**（`:7-9`，省略 profile 不继承任何东西）。
- **`_bridge.py _active(profile_id)` 严格按 `profile_id` 过滤客户端、无兜底**（`:34-40`）——`locate(profile_id="default")` 只找 `profile_id=="default"` 的 tab，没有 → `raise TimeoutError` → `resolve_locate` 返回 `no_tab_for_profile`（`_locate.py:8-10`）。
- **operator tab 注册的 profile_id = 烤入的 `op-f218...`**（content.js `PROFILE_ID` 占位替换，`make_ws_route` 用它 register，`_bridge.py:92`）——与解析出的 "default" 永不匹配。
- 故：**省略 profile 的 human_dom 调用 → 解析 "default" → 桥里只有 operator tab、没 "default" tab → no_tab_for_profile**。这就是 P6。

### 1.4 E1/E2/E3 取证：多数已实现（避免第二次投机重写）

需求文档 §3 的 E1/E2/E3 = commit **`59fe476`（PR#73，发版 v0.8.10-alpha）** 已做的 R1/R2/R3，**同日、一字不差**，已在 main（v0.8.12-alpha）：

| 需求 | main 现状 | 状态 |
|---|---|---|
| E1 visibleText 读 data-placeholder/aria-placeholder | `content.js:11-12` 已是该链 | ✅ 已实现 |
| E2 fill 回读杀假成功 | `_human_dom.py:14 _verify_fill` + `:171 fill_verify_failed` | ✅ 已实现（**缺「可选一次重试」**） |
| E3 候选偏真可编辑排序 | `content.js isEditable` + `sort((b._editable-a._editable)...)` | ✅ 已实现 |

**唯一真残留 = E2 的「可选一次重试」**（需求文档 §3 R2 那句「可选一次重试再降级」现在没做）。故次项 = **确认在案 + 补 E2 重试**，非重写。

### 1.5 需求一句话

> **省略 profile 时，human_dom_locate/tap/fill 不再硬默认 "default"，而是可靠解析到「当前活跃的 operator profile」（human_browser_open 打开、已连桥的那个 tab），治 P6 的解析抖动；并让解析结果可观测。次带补 E2 的失败重试。**

### 1.6 成功判据

- 省略 profile 的 human_dom 调用，在有 operator tab 连桥时**可靠命中该 operator tab**（不再间歇落 "default" no_tab）；无 operator tab 时回退 "default"（保默认日常 Chrome 用例）。
- 响应带 `resolved_profile`，解析到哪个 profile 可见（catch 静默误解析）。
- 显式传 profile 行为不变；多 profile 路由不串线（PR#66 不回归）。
- E2 fill 失败重试一次再降级。

> **⚠️ 一个有意的语义收紧（架构审 B1，写显式）**：本改**改变了「省略 profile」这一模糊输入的语义**——当 **operator tab 与日常 default Chrome 同时连桥**时，省略 profile 从今天的「default」改指「operator」（取最近活跃）。这是**有意收紧、非回归**：它正是为治 P6（操作员开了 operator profile 却省略 profile→错落 default）。所谓「零回归」**仅限「无 operator tab 连桥」**（纯默认日常 Chrome 用例，回退 default 不变）。要精确针对日常 default Chrome、同时又有 operator 在场，请**显式传 profile**（显式路由一行不动）；`resolved_profile` 让落到哪可见、可纠。

---

## 二、目标 / 非目标

### 目标
- G1（追 §1.2/§1.3）：**省略 profile 的解析改为「问桥要当前活跃 operator profile」**，桥无 operator tab 才回退 "default"。自包含在桥 + 工具解析层。
- G2：解析结果**可观测**（响应加 `resolved_profile`）。
- G3（追 §1.4）：**确认 E1/E2/E3 在案**（已实现）+ **补 E2 的失败重试一次**（tap→fill→verify→失败→re-tap+re-fill→verify→仍失败→降级 vision）。
- G4：桥/工具/E2 重试**纯 Python 可本机 TDD**（不依赖 numpy）。

### 非目标（YAGNI）
- NG1：**不重写 E1/E2/E3**（§1.4 已实现，重写=投机冗余）。
- NG2：**不引跨模块「last-bound profile」新状态**——桥的连接客户端注册表已是「human_browser_open 打开的 tab」的活证据，用它即可（G1）。
- NG3：**不碰 E4 iframe**（需求文档明确后置；公众号编辑器无 iframe，不阻塞 #100）。
- NG4：**不改显式 profile 的解析/路由**、不改坐标映射、不动 vision。
- NG5：**不改 fill 落字机制本身**（`_os_fill` 的 Ctrl+A+粘贴不动；取证文档 §1 实证「locate 到真编辑体则现有 OS fill 能填」——P6 的问题在 locate 前的 profile 解析，非落字）。

---

## 三、方案对比（省略 profile 怎么解析）

| 方案 | 做法 | 判定 |
|---|---|---|
| **A. 桥侧解析活跃 operator profile**（本 spec 选） | 省略 profile → 问桥「当前最近活跃的非 default operator profile」；无则回退 default | ✅ **选它**。自包含（桥已有客户端注册表）、直接治 P6、忠实「继承最近绑定的 profile」意图、无跨模块新状态、可观测。 |
| B. 保 "default" + no_tab 时兜底重试 | 解析仍 "default"，`no_tab_for_profile` 时若唯一活跃 operator tab 则重试一次 | 🔸 用户提的「最低兜底」。比 A 保守（不改默认语义），但要多一次失败往返、且只在唯一 operator 时生效。作为 A 的补充安全网可留（§4.1）。 |
| C. 跨模块记 last-bound（human_browser_open 写全局，human_dom 读） | human_browser_open 记「最近绑定 profile」到共享状态，human_dom 省略时读它 | ❌ 否决。引跨 capability 模块新状态（browser↔human_dom）、生命周期/并发复杂；桥的活客户端已是更可靠的「当前真活跃」证据（打开但已关的 profile 不该被继承）。 |

选 A 一句话：桥**已经知道**哪些 operator tab 正连着（human_browser_open 打开后 content script 连桥注册），省略 profile 就该解析到它，而不是硬 "default"。

---

## 四、设计（方案 A）

### 4.1 组件一：桥侧「活跃 operator profile」解析（G1）

`_bridge.py DomBridge` 加方法：

```python
def active_operator_profile(self) -> "str | None":
    """省略 profile 时的解析源: 返回当前【最近活跃的非 "default" operator profile】的 profile_id;
    无 operator tab 连着 → None(调用方回退 "default")。修 P6: 省略 profile 硬默认 "default"→no_tab。"""
    with self._lock:  # 锁内一次性 copy 出 (profile_id, active, ts), 排序在锁外, 消脏读(架构审 #5)
        ops = [(c["profile_id"], bool(c.get("active")), c.get("last_active_ts", 0.0))
               for c in self._clients if c["profile_id"] != "default"]
    if not ops:
        return None
    active = [t for t in ops if t[1]]
    pool = active or ops
    pool.sort(key=lambda t: t[2], reverse=True)  # 最近活跃优先
    return pool[0][0]
```

- 需给客户端记 `last_active_ts`：`register()` 时 `time.monotonic()`；`set_active(active=True)` 时刷新（均在既有 `self._lock` 内）。多 tab/多 operator 时取最近活跃的那个 profile。
- **多 operator 安全**：只有多个**不同** operator profile 同时活跃才有歧义；此时取最近活跃（偏向 operator 刚操作的那个），并靠 §4.2 的 `resolved_profile` 可观测——不静默串线到错 profile（PR#66 的显式 profile 路由完全不变；这只影响「省略 profile」这一模糊输入）。

### 4.2 组件二：工具层解析改道 + 可观测（G1/G2）

新增解析函数（`_ident.py` 或 `_locate.py`）：

```python
def resolve_profile_id(bridge, profile_str: "str | None") -> str:
    """显式 profile → 原样规范化(human_dom_profile_id, 不变);
    省略 → 桥的活跃 operator profile, 无则 "default"(保默认日常 Chrome 用例)。"""
    s = (profile_str or "").strip()
    if s:
        return human_dom_profile_id(s)         # 显式: 行为完全不变
    op = bridge.active_operator_profile()
    return op if op else "default"
```

- `_human_dom.py` 的 `human_dom_locate/tap/fill` 把 `human_dom_profile_id(profile)` 改为 `resolve_profile_id(bridge, profile)`。
- **响应可观测**：**成功路径加 `resolved_profile`**（解析到的 profile_id），让 agent/日志看得见落到了哪个 profile（catch 静默误解析——正是 P6 当初没暴露清楚的点）。`no_tab_for_profile` 分支**复用既有 `profile` 字段**（`_locate.py:9` 已带，新解析下它就是 resolved pid），**不再双字段**（架构审 #4）。
- **不做方案 B 兜底重试**（架构审 #3）：方案 A 已在解析步就选对 operator profile，`no_tab` 时再兜底是冗余、徒增改动面——砍掉，保持面最小。

### 4.3 组件三：E1/E2/E3 收尾（G3，次项）

- **E1/E3 已实现**（§1.4）→ 本 spec **只确认在案**（加/核单测守着不回归），**不重写**。
- **E2 补失败重试一次**（+ 抽 `_do_fill` 模块级 helper，架构审 #1）：现无测试触达 `human_dom_fill` 闭包工具，把其主体抽成模块级 `_do_fill(bridge, tap, fill, query, text, css, pid)`，让重试可直接单测（绕开「mock mcp 截获闭包」脚手架）。逻辑：`locate→tap(center)→fill→_verify_fill→失败→(**用首次 candidate 的同一 center re-tap** + re-fill)→verify→仍失败→{ok:False, fill_verify_failed, suggest:vision}`。**re-tap 复用首次坐标、不 re-locate**（架构审 #6）——重试假设是「首次焦点没落定」；若 re-locate，部分落字后占位消失会让 R3 排序变、定位漂移。retry 只一次防死循环；`_os_fill` 全选+粘贴覆盖式，re-fill 不追加、无副作用。

### 4.4 不动的部分（NG）
- 显式 profile 的解析/路由、多 profile 不串线（PR#66）、坐标映射、`_os_fill` 落字机制、vision、E4 iframe（manifest 不加 all_frames）——全不动。

---

## 五、测试策略（大部分纯 Python 本机可跑）

> `_bridge.py`/`_human_dom.py`/`_ident.py` 纯 Python（不依赖 numpy/cv2）→ 本机 pytest 可跑（既有 `test_human_dom_bridge*.py`/`test_human_dom_locate.py`/`test_human_dom_fill.py` 就是这么测的）。

### 5.1 本机可跑单测
- **`active_operator_profile`**：造 `DomBridge` + register 合成客户端（default + 一个/多个 operator，带 active/last_active_ts）→ 断言：① 唯一 operator active → 返回它；② 多 operator → 返回最近活跃；③ 仅 default 连着 → None；④ 无客户端 → None。
- **`resolve_profile_id`**：① 显式 profile → `human_dom_profile_id` 结果（不变）；② 省略 + 有 operator → operator profile；③ 省略 + 无 operator → "default"。
- **`resolved_profile` 可观测**：`resolve_locate`/工具返回含 `resolved_profile`（FakeBridge 桩）。
- **E2 重试**：直接测抽出的模块级 `_do_fill`（架构审 #1，绕开闭包）——monkeypatch `resolve_locate`/`_verify_fill`：首次 verify 失败、重试后成功 → `ok:True`；两次都失败 → `fill_verify_failed`；验证「只重试一次」（不死循环）+ re-tap 用首次 center（tap 桩记录被调坐标，两次相同）。
- **零回归**：既有 `test_human_dom_locate.py`/`test_human_dom_fill.py`/`test_human_dom_bridge*.py`/`test_human_dom_geom.py` 全绿；E1/E3 的 `test_content_js_visibletext.mjs`（若碰 content.js 则守，本 spec 不碰 content.js）不受影响。

### 5.2 真机验收（用户在场，test-win11 公众号编辑器）
- 起 operator profile（`human_browser_open(profile=op-...)`）→ **省略 profile** 调 `human_dom_locate("请在这里输入标题")` **可靠命中标题编辑体**（不再间歇 no_tab_for_profile）；`resolved_profile` = operator profile。
- `human_dom_fill(query="请在这里输入标题", text=...)` **省略 profile** 落字成功；构造首次 fill 失败 → 重试后成功 / 或正确降级。
- 多 profile 不串线回归（若可造双 operator）。

### 5.3 质量门禁（charter）
架构审（本 spec）→ code-reviewer 审 → 真机验收 → 过了才合并 + tag。

---

## 六、验收判据

1. 省略 profile + 有 operator tab 连桥 → 可靠解析到该 operator profile、命中（本机单测 + 真机）；无 operator tab → 回退 "default"。**「零回归」仅限「无 operator tab 连桥」；operator + 日常 default 并存时 omitted 按设计改指 operator（§1.6 有意语义收紧）。**
2. 成功路径带 `resolved_profile`（可观测）；`no_tab_for_profile` 分支复用既有 `profile` 字段（不双字段）。
3. **显式 profile 行为零回归**；多 profile 路由不串线（PR#66）。
4. E1/E3 确认在案（不重写、单测守）；**E2 补失败重试一次**再降级。
5. E4 iframe 不碰；`_os_fill`/坐标/vision 不动。

---

## 七、决策记录（每条追回需求/取证）

| 决策 | 选择 | 追回 |
|---|---|---|
| 省略 profile 解析 | 桥侧活跃 operator profile, 无则 default | §1.2 P6 真机根因；方案 A（自包含、忠实继承意图） |
| 不引跨模块 last-bound 状态 | 否（NG2/方案 C 否决） | 桥活客户端已是更可靠证据；避 browser↔human_dom 跨模块状态 |
| 可观测 | 响应加 `resolved_profile` | §1.2 P6 当初静默落 default 没暴露清楚 |
| E1/E2/E3 | 不重写(已实现), 仅确认 + 补 E2 重试 | §1.4 取证：59fe476 已做；唯一残留=E2 重试 |
| fill 落字机制 | 不动 | NG5；取证文档 §1 实证落字本身 work，P6 死在 profile 解析非落字 |
| E4 iframe | 后置不碰 | NG3；需求文档明确后置、公众号无 iframe |
| 多 operator 歧义 | 取最近活跃 + resolved_profile 可观测, 不静默串线 | §4.1；显式 profile 仍是精确路由 |
| omitted 语义收紧 | operator 在场时 omitted 改指 operator(非 default) | §1.6 架构审 B1；有意收紧治 P6，非回归；日常 default 用显式 profile |
| fresh-open 时序窗口(残留) | 不额外治；主目标(reused 已连)不受影响 | 架构审 #2：human_browser_open 非 reuse、content.js 未连桥时 omitted 调用→None→default→no_tab；缓解=调用前 human_dom_status 确认 connected(编排侧)或后续按需在 resolve 内短暂重试 |

---

## 八、落地位置与文件清单（给 writing-plans）

**修改**
- `platforms/common/capabilities/human_dom/_bridge.py`：`DomBridge` 加 `active_operator_profile()`；`register`/`set_active` 记 `last_active_ts`（`time.monotonic`）。
- `platforms/common/capabilities/human_dom/_ident.py`（或 `_locate.py`）：加 `resolve_profile_id(bridge, profile_str)`（显式不变、省略问桥）。
- `platforms/common/capabilities/human_dom/_human_dom.py`：`human_dom_locate/tap/fill` 用 `resolve_profile_id(bridge, profile)`；**成功路径**加 `resolved_profile`；`human_dom_fill` 主体抽模块级 `_do_fill(...)` + 加失败重试一次（E2，re-tap 复用首次 center）。
- `platforms/common/capabilities/human_dom/_locate.py`：成功结果带 `resolved_profile`；`no_tab_for_profile` 分支**复用既有 `profile` 字段**（不加双字段）。

**新建/扩测**
- `platforms/common/tests/test_human_dom_profile_resolution.py`（新）：`active_operator_profile` + `resolve_profile_id` 纯 Python 单测（本机可跑）。
- `test_human_dom_fill.py` 加 E2 重试断言；既有 bridge/locate 测试守零回归。

**不动**：`content.js`（E1/E3 已实现、不重写）、`_geom.py`、`_setup.py`、vision、坐标映射、manifest（不加 all_frames）、`_os_fill`。

---

## 附：给 writing-plans 的实现注意
- **零回归**：显式 profile 路径一行不动（`resolve_profile_id` 对非空 profile 直接调既有 `human_dom_profile_id`）；只改「省略 profile」这一模糊输入的解析。
- **桥并发（架构审 #5）**：`active_operator_profile` **锁内一次性 copy 出 `(profile_id, active, last_active_ts)` 再锁外排序**（`register`/`set_active` 也在锁内写这些字段），消脏读；`last_active_ts` 用 `time.monotonic`。
- **`resolved_profile`（架构审 #4）**：**只成功路径**加；`no_tab_for_profile` 复用既有 `profile` 字段，不双字段。
- **E2 重试只一次（架构审 #6）**：防死循环；**re-tap 复用首次 candidate 的 center**（不 re-locate，避部分落字后 R3 重排漂移）再 re-fill。
- **抽 `_do_fill`（架构审 #1）**：把 fill 主体抽模块级 helper，重试可直接单测（绕开闭包 mock 脚手架）。
- **omitted 语义收紧（架构审 B1）**：operator 在场时 omitted 改指 operator（非 default）——有意、非回归；「零回归」仅限无 operator 连桥；日常 default 用显式 profile。
- **fresh-open 时序窗口（架构审 #2，残留）**：human_browser_open 非 reuse、content.js 未连桥时紧接 omitted 调用会回退 default→no_tab；主目标（P6 是 reused 已连）不受影响，编排侧调用前 `human_dom_status` 确认 connected 可缓解，不在本 spec 额外治。
- **不重写 E1/E3**：只加单测守着（真机已间接验，本批不碰 content.js）。
- **默认日常 Chrome 用例**：无 operator tab 连桥时 `resolve_profile_id` 回退 "default"，与改动前一致——不回归。
