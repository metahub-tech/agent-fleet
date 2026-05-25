# 浏览器 profile 指定 + 租约生命周期设计

> 状态：草案，待 architect 审 + 用户定方向
> 日期：2026-05-25
> 目标：给 agent_browser / human_browser 加"调用时动态指定 profile"，并设计 profile 级的**租约（lease）机制**——绑定 / 释放 / 空闲超时 / 关闭，让多 agent 或单 agent 多次调用能协调到"绑定了指定 profile 的浏览器"。

## 0. 用户已定方向（2026-05-25）

1. **并发**：profile 被占用时**拒绝 + 告知 `auto_release_in`**（advisory，非阻塞，调用方重试）。与现有 `acquire`/`DeviceStateRegistry` 一致。
2. **生命周期**：`release` **只解绑、保留浏览器进程**（供下次同 profile 秒复用）；**idle 超时才真关进程**回收资源；`close` 是显式关闭。
3. **范围**：agent_browser **必须支持多 profile 真并行**（同时操作多个不同 profile 的浏览器）。

---

## 1. 核心约束（为什么需要租约）

- **profile = OS 级互斥资源**：同一 Chrome `user-data-dir` 同一时刻只能被一个 Chrome 实例打开（singleton 锁）。
- **跨档共享同一把锁**：一个 profile 要么被 agent_browser（Playwright 控制）占、要么被 human_browser（裸 Chrome）占，**不能同时**。所以 human/agent **共用一个全局 lease 注册表**，键 = profile。
- **现成模板**：`platforms/common/_device_state.py` 的 `DeviceStateRegistry`（advisory single-holder + idle-timeout + acquire/release/touch/status）正是同构机制。本设计**新建 `BrowserLeaseRegistry`** 复用其模式，但额外管理**真实浏览器实例句柄**（不只是 advisory 标记）。

---

## 2. 资源模型：BrowserLease

```
profile_key  ──►  BrowserLease {
    profile_key:   str          # 规范化的 profile 标识（见 §3）
    engine:        "human" | "agent"
    holder:        str          # 绑定者（agent 名 / 调用方标识）
    instance:      <handle>     # human: Popen/进程组；agent: 该 profile 的 Playwright client
    acquired_at:   datetime
    last_used_at:  datetime     # 每次操作 touch 刷新
    state:         "active" | "detached"   # detached = 已 release 但进程保留
}
```

- 一个 `BrowserLeaseRegistry`（全局单例，线程安全，仿 DeviceStateRegistry）持有 `dict[profile_key → BrowserLease]`。
- **多 profile 真并行** = registry 里同时多个 active lease，每个对应一个真实浏览器实例。
- **跨档互斥**：bind 时若 profile_key 已被**另一 engine 或另一 holder**占（active）→ 拒绝。

---

## 3. profile 标识与别名

调用方传 `profile` 参数，规范化为 `profile_key`：

| 输入形式 | 含义 | 规范化 |
|---|---|---|
| 别名 `"default"` | human：系统默认 profile（真人日常） | `human:default` |
| 别名 `"isolated"` | agent：隔离 profile `~/.fleet/agent-browser-profile` | `agent:isolated` |
| `--user-data-dir` 绝对路径 | 显式 profile 目录 | 该路径（绝对化） |
| `dir@ProfileName` | user-data-dir + `--profile-directory`（Chrome 多 profile 子目录，如 `Default`/`Profile 1`） | `dir::ProfileName` |

- profile_key 以**最终独占的 user-data-dir（+ profile-directory）**为准——这是 OS 锁的真实粒度，保证跨档互斥正确。
- 内置别名给常用场景降负担；高级用法传路径。
- **human "default"（真人日常 profile）的特殊性**见 §6。

---

## 4. 租约生命周期与工具接口

新增 4 个管理工具（两档共用同一 registry）+ 操作工具加 `profile` 参数：

| 工具 | 行为 |
|---|---|
| `browser_bind(engine, profile, holder)` | profile 空闲 → 启动该 engine 浏览器绑定，返回 `{bound:true, profile_key, session}`。已被本 holder+engine 占 → 复用+刷新。被他人/他档占 → `{bound:false, current_holder, engine, auto_release_in}`。`detached` 状态(进程保留)→ 重新绑定到该进程(秒复用)。 |
| `browser_release(profile, holder)` | 仅 holder 可释放。置 `detached`，**保留进程**。返回 `{released:true, kept_alive:true}`。 |
| `browser_close(profile, holder)` | 关闭浏览器进程 + 删除 lease。 |
| `browser_status()` | 所有 lease 快照(profile_key/engine/holder/idle/auto_release_in/state)。 |
| 操作工具（agent 的 `browser_*` / human 走 core 的 screenshot+tap） | 带 `profile` 参数路由到对应实例；每次调用 `touch` 刷新 idle，并校验调用方为 holder。 |

- **idle 超时**（默认 10min，沿用 IDLE_TIMEOUT）：active 或 detached lease 超时 → 关进程 + 删 lease（回收）。惰性过期（在 bind/status/touch 时检查）+ 可选后台清扫线程。
- **detached 复用**：release 后进程保留为 detached；同 profile 再 bind → 直接复用该进程，免重启（满足"秒复用"决策）。

---

## 5. human_browser 多 profile 实现（简单）

> **搁置（用户 2026-05-25）**：human_browser 暂不做多 profile（YAGNI），待真实需求 / 其他开发者需要时再加。它继续用系统默认/日常 profile、不接入租约。`BrowserLeaseRegistry` 已预留 `human` engine + 跨档互斥逻辑，届时直接接入即可，无需改 registry。以下为将来实现参考。当前设计聚焦 agent_browser（§6）。

- `human_browser_open(url, profile, holder)`：
  - 经 registry `bind("human", profile, holder)`。
  - 启动：`chrome --user-data-dir=<dir> [--profile-directory=<name>] <url>`（mac 经 `open -na "Google Chrome" --args ...` 用 `-n` 强制新实例避免 singleton 转发）。
  - 记录 Popen/进程句柄到 lease。
- 操作仍走 core 的 `take_screenshot`+`tap`（OS 级，零痕迹不变）。多 profile = 多 Chrome 窗口，截图/坐标操作哪个窗口靠前台焦点——**多 human profile 并行时的前台焦点协调是一个细节风险**（OS 同一时刻一个前台），需 bind 时 `--new-window` + 操作前 focus。
- **真人日常 profile 的约束**：若用户已手动开着日常 Chrome，`bind("human","default")` 会遇到 singleton——`-n`/新实例可能与已运行实例冲突。需检测并提示（"日常 profile 已在运行,请用现有窗口或指定其它 profile"）。

## 6. agent_browser 多 profile 实现（难点 + 候选方案）⚠️

**根本张力**：当前 agent_browser 是 proxied——`mcp.mount(create_proxy(ProxyClient(StdioTransport(npx @playwright/mcp --user-data-dir FIXED))))`，**一个**子进程绑**一个**固定 profile，工具静态挂载。@playwright/mcp 的 profile 是**进程级启动参数**，一个 server 进程一个 profile。"多 profile 真并行"与此冲突。

候选方案：

- **A. 网关 + 后端实例池（推荐评估）**：agent_browser 不再 `mcp.mount`。改为自建固定一组 `browser_*` 工具（schema = @playwright/mcp 的 23 个 + 新增 `profile` 参数），内部维护 `dict[profile_key → fastmcp Client(StdioTransport(@playwright/mcp --user-data-dir <profile>))]`，bind 时 lazy 起子进程，调用时按 profile 路由 `client.call_tool(name, args)`。
  - ✅ 真多 profile 并行（多子进程同时活）；工具名固定（不依赖动态 mount / list_changed）。
  - ⚠️ 要维护 23 个 wrapper 的 schema —— 可在启动时探一个 @playwright/mcp 自省工具 schema 动态生成 wrapper，避免硬编码漂移。**此动态生成 + 路由是主要技术风险，建议先 spike 验证 FastMCP 可行性。**
- **B. 每 profile 动态 mount with prefix**：`mcp.mount(proxy, prefix=profile)` 运行时挂载。❌ 依赖 `tools/list_changed`，spike 已证 Claude Code 会话内不响应（见 capability-framework spec），排除。
- **C. 收口为网关胖工具** `browser(action, profile, args)`：单工具多 action。✅ 实现简单、天然带 profile。⚠️ 放弃 23 个原生工具的类型与体验,与现有 agent_browser 形态不一致。

**倾向**：A（保留原生工具体验 + 真并行），但 schema 动态生成 + 多 client 路由需 spike 验证；若 spike 不通则退 C。

**实现架构（架构 spike 2026-05-25，test-win11）**：
- ✅ spike A gate 已过（`add_tool` 动态 schema + 自省真实 23 工具 + 批量注册，见 §10-3）。
- ⚠️ **Windows 陷阱（实测踩到）**：把多 client 放进「子线程后台 event loop」会卡死——Windows 上 asyncio 子进程（`StdioTransport` 起 npx）在**子线程**的 ProactorEventLoop 里无法可靠创建（child watcher / signal 限制）。实测子线程 bg-loop 方案首个 client 连接即卡死、零输出、@playwright/mcp 子进程根本没 spawn 出来。**实现绝不能用子线程 event loop。**
- ✅ **正确架构 = server 自己的主 event loop 直接管所有 client**（不开子线程）：现有单 profile agent_browser（`create_proxy`+`mount`，keep_alive）已证 server 主 loop + @playwright/mcp 子进程在 Windows 可行；多 profile = 主 loop 里多个 `Client`（每 profile 一个），asyncio 天然并发。
- **sync↔async 桥接**：`BrowserLeaseRegistry` 是同步的、client 操作是 async。`start_fn` 同步只构造 session 对象（**不连**，connect lazy 到首次 call 的 async handler 内）；**`close_fn` 同步用 `asyncio.ensure_future(session.aclose())` fire-and-forget**（惰性过期发生在 async handler 栈内、有 running loop，非阻塞，正好满足 registry「close_fn 必须非阻塞」的约束）；handler `await session.call(name, args)`（同一主 loop）。

---

## 7. 跨档互斥与一致性

- human/agent 共用一个 `BrowserLeaseRegistry`，键以**真实 user-data-dir(+profile-directory)** 规范化 → 保证"同一 profile 不被 human 和 agent 同时占"。
- profile_key 冲突检测在 bind 时做（active lease 存在且 holder/engine 不匹配 → 拒绝 + auto_release_in）。
- registry 放 `platforms/common/`（两档 capability 共享导入），随 server 进程单例。

---

## 8. 与现有 acquire/release（设备级）的关系

- 现有 `acquire`/`release`/`get_status` 是**整设备** advisory holder（core 工具，`DeviceStateRegistry`）。
- 本设计是 **profile 级浏览器租约**，粒度更细、且管真实实例。**两者并存、不替代**：设备级管"谁在用这台机"，浏览器级管"谁在用哪个 profile 的浏览器"。
- 复用 `DeviceStateRegistry` 的代码模式（甚至可抽公共基类 `LeaseRegistry`），但实例分开。

---

## 9. 未决点 / 风险（请 architect 重点评估）

1. **A 方案 FastMCP 可行性**：能否在启动时自省 @playwright/mcp 的工具 schema 并动态生成带 `profile` 参数的 wrapper + 多 client 路由？建议先做最小 spike。
2. **human 多 profile 前台焦点**：多个 human Chrome 窗口并行时，core 截图/坐标操作如何确定目标窗口（OS 单前台）——bind 时 `--new-window` + 操作前 focus_window，是否够？
3. **真人日常 profile 的 singleton 冲突**：用户已开着日常 Chrome 时 bind("human","default") 的处理（复用现有 vs 拒绝提示）。
4. **idle 超时关进程**：detached human Chrome / agent Playwright 子进程的可靠关闭（进程组 kill / client.close + 子进程回收）。
5. **holder 标识来源**：MCP 调用方如何提供稳定 holder 名（同 acquire 的 holder_name 约定）。
6. **零痕迹一致性**：human_browser 加 `--user-data-dir` 是否仍零自动化痕迹（应是——user-data-dir 是正常 Chrome 参数，非自动化标志）；agent_browser 多子进程不改变 §CDP 分析结论。

---

## 10. 实现顺序（待方向确认后）

1. **独立实现** `BrowserLeaseRegistry`（仿 DeviceStateRegistry 模式，但管真实实例句柄）。**先不抽公共基类**——它管真实资源、DeviceStateRegistry 纯 advisory，差异大，过早抽象会让基类职责过载；接口稳定后再议（architect 建议）。
2. human_browser：加 `profile` 参数 + bind/release/close/status 接入 registry（简单，先落地验证租约语义）。
3. **spike（gate）✅ 通过（2026-05-25，test-win11，fastmcp 3.2.4）**：
   - `mcp.add_tool(tool | callable)` 存在；`Tool.from_function` 从函数签名生成 schema（无显式 input_schema 入口，但有 `exclude_args`）。
   - 关键手法：给一个 `async def handler(**kwargs)` **运行时设 `__signature__`**（profile + 原工具参数，类型由原 schema 的 type 映射），fastmcp 自省该签名 → 注册出带 profile 的、**结构化 schema 完整保留**的工具（验证 `browser_navigate→[profile,url]`、`browser_click→[profile,element,target,doubleClick,button,modifiers]` 等）。
   - `Client.list_tools()` 自省真实 @playwright/mcp **23 工具 schema** 成功；据此**批量生成并注册 23 个 wrapper** 成功。
   - 工具名启动时固定 → 绕开 list_changed 限制。**→ 走方案 A（不退 C）。**
   - 注意（实现要点）：spike 退出时 @playwright/mcp stdio 子进程未干净退出（脚本超时）——印证 `close_fn` 必须非阻塞地回收子进程（registry 已警告）。
4. agent_browser：按 spike 结论实现 A（或退 C）。
5. 跨档互斥 + idle 清扫 + 真机验证（test-win11 / macmini）。
6. 更新 using-fleet-browser / using-human-browser skill。

---

## 11. architect 审结论（2026-05-25，已采纳）

**整体：方向正确、无架构阻断，方案 A 可行性高；以 §10-3 spike 为 gate,通过即可全量实现。** 5 条建议（均不阻断，已并入上文）：

1. **方案 A 的 spike 焦点 = `mcp.add_tool()` 动态批量注册**（不是 schema 自省——后者经 `Client.list_tools()` 已确认可行；多 Client/多 stdio 子进程路由也是 ProxiedCapability 已验证路径）。绕开 list_changed 成立（工具名启动时固定、profile 走参数）。退路 C（胖工具）零 spike 风险但丢结构化 schema/类型。
2. **idle 超时竞态（TOCTOU）**：清扫与进行中操作间有窗口。对策——**默认只用惰性过期**；后台清扫设为可选且保守（关进程前二次确认 `last_used_at` 未刷新），并加 `active_calls` 计数守卫，调用进行中不关。
3. **profile_key 规范化必须 `Path.resolve()`**（展开符号链接），否则同目录不同路径形式绕过跨档互斥。
4. **human 多 profile focus 要分平台**：mac 用 `open -na "Google Chrome" --args --user-data-dir=… --new-window` + AppleScript `activate`；win 用 `--new-window` + `ctypes.windll.user32` 置前。`tap` 是屏幕绝对坐标，操作前必须确保目标窗口在最前。
5. **holder 必填**（MCP 调用无自带身份），与现有 `acquire` 的 holder_name 约定对齐,不做自动推断。
