# 能力模块框架（capability-module framework）—— 方案 C

状态：设计中（待 architect 审 + 用户确认后实施）
日期：2026-05-24
关联：[[北极星愿景]] `memory/project-agent-fleet-capability-platform-vision.md`、`2026-05-24-win-mac-element-action.md`、`2026-05-24-fleet-cli.md`

---

## 0. 一句话

把每个 device server 的工具按**能力模块（capability）**组织：**core 常驻 + 可选模块（首个 = `browser`）**；所有启用模块的工具在**连接时静态注册**（靠客户端 deferred-tools 省 token，不靠会话内动态列表），配 `list_capabilities()` 发现面 + 每能力 skill，server 端按 config 决定挂载哪些模块。

---

## 1. 背景与决策依据（spike 已定）

**为什么是方案 C 而不是 A（动态列表）**：2026-05-24 最小 spike 实测（`/tmp/spike_server.py`，FastMCP 3.3.0，`claude mcp add` + `/mcp` 连上）——运行时 `add_tool()` 注册新工具并发 `tools/list_changed`，**Claude Code 同回合、下一回合都不重拉**，ToolSearch 精确名/关键词均找不到新工具，必须手动 `/mcp` 重连。→ **"会话内动态注册 → 自动拾取" 不成立，路径 A 排除。**

**为什么 C 够用（spike 顺带证实）**：本会话所有 device 工具（4 server × ~41 = 几百个）都是 Claude Code 的 **deferred tools**——连接即在 `tools/list`，但 schema 不预载、按需 `ToolSearch` 才 load。**"工具过多 / 烧 token" 客户端已自解**，不需要靠动态增删工具省 token。

**真机 FastMCP 版本**：win-device 3.2.4 / mac-device **3.3.1（pyproject `!=3.3.1` 排除版，macmini venv 漂移，落地前先对齐）** / ios-device 3.3.0，均 v3 → 可用 v3 的 `mount()` / tags / `enable()/disable()`。

**现状（代码核实）**：每平台 = 单个 FastMCP 文件（`@mcp.tool` 平铺 ~41 个、`with_touch` 装饰器），无 tags/无模块分组；skills 每平台一个（`using-mac`/`using-win`/...）；契约 SSOT = `common/_canonical_tools.py`（CORE+OPTIONAL）；manifest = `platform.toml`（`[platform]`/`[server]`/`[install]`）→ `PlatformManifest`。

---

## 2. 目标与非目标

**目标**
1. 定义 `CapabilityModule` 抽象：一个能力 = 一组工具 + 元数据 + 契约 + skill + 依赖声明，可被一个或多个 platform server 挂载。
2. 现有全部工具收编为 **`core` 模块**（纯重构、零行为变化）。
3. 加 `list_capabilities()` 发现面（agent 知道"有哪些能力、各含哪些工具、加载哪个 skill、是否可用"）。
4. server 端 config（`platform.toml` `[capabilities]` + 可选 per-host 覆盖）决定**挂载哪些模块**，(重)连生效——运维级可控。
5. 首个可选模块 `browser`（CDP/DOM）作为**共享模块**（OS 无关）打通整链路、做成可复制范式。
6. 为"**开放接入标准**"留好扩展点（第三方按同一 `CapabilityModule` 协议加能力）。

**非目标（本框架批次明确排除）**
- 会话内动态启用/停用（spike 已证不可行；改为 (重)连生效）。
- 把 core 现有工具拆成多模块的大重构（core 整体收编为一个模块即可，内部不再细分）。
- `browser` 的完整实现（本批只定框架 + browser 作为**第一个验证用例的接口契约**；完整实现进 Phase 2）。
- element-action 独立成模块（它是设备基础能力 → 留在 core）。

---

## 3. 框架核心设计

### 3.1 `CapabilityModule` 抽象（落在 `common/capabilities/`）

```python
# common/capabilities/_base.py  （示意，非最终）
@dataclass
class CapabilityModule:
    id: str                       # "core" | "browser" | ...
    display_name: str
    description: str              # 给 agent 看的能力简介
    skill: str | None             # 配套 skill 名，如 "using-fleet-browser"
    platforms: list[str] | None   # 适用 host_os；None=全平台（如 browser）
    surface: str                  # "multi_tool" | "gateway"  —— 工具粒度（见 3.4）
    def register(self, mcp: FastMCP) -> None: ...   # 把本模块工具注册到 mcp
    def availability(self) -> tuple[bool, str]: ...  # (是否可用, 原因)  依赖缺失→False
```

- 每个模块自带 `register()`，内部用 `@mcp.tool(tags={self.id})` 给工具打**能力 tag**（FastMCP v3 支持），便于 `list_capabilities` 反查归属、便于未来按 tag 过滤。
- `availability()` 探测依赖（如 browser 探 Chromium/CDP 端点）→ 决定 `list_capabilities` 里报 `enabled` 还是 `unavailable + 原因`。

### 3.2 挂载机制 —— 候选：`mount()` 子 server vs 条件注册（**请 architect 定**）

- **方案 X：conditional register**。server 启动读 config，对每个启用模块调 `module.register(mcp)`。最简单、零新概念。
- **方案 Y：FastMCP `mount()` 子 server**。每能力 = 一个子 `FastMCP`，按 prefix 挂到主 server。隔离干净、tag/前缀天然、停用 = 不 mount。spike 已确认**连接时静态组合**可用。
- 倾向 **Y（mount 子 server）**——更贴"模块化平台"、利于第三方接入；但 X 更轻。**架构权衡点①**。

### 3.3 发现面 `list_capabilities()`（core 工具，常驻）

返回结构（示意）：
```json
{
  "capabilities": [
    {"id":"core","status":"enabled","tools":["tap","type_text","find_elements",...],"skill":"using-mac"},
    {"id":"browser","status":"enabled","tools":["browser_navigate","browser_click",...],"skill":"using-fleet-browser"},
    {"id":"media","status":"unavailable","reason":"ffmpeg not installed","tools":[],"skill":"using-fleet-media"}
  ]
}
```
- 取代愿景里原设想的 `enable_capability`——工具本就静态在列，**只需"发现"不需"启用"**。
- 双重作用：① Claude Code 下，agent 据此知道该 `ToolSearch` 哪些名字 + 加载哪个 skill；② 非 deferred 客户端下，是能力总览入口。

### 3.4 工具粒度：multi_tool（默认）vs gateway（opt-in）—— **请 architect 定 browser**

- **multi_tool**（如 core、element-action、以及 Playwright MCP 的形态）：`browser_navigate` / `browser_click` ... 多个**强类型**工具。Claude Code 靠 deferred 不烧 token；非 CC 客户端会多很多工具名。
- **gateway 胖工具**：单 `browser(action, args)` 内部分派。**任何客户端一个名字**；类型弱，靠 schema 的 action enum + skill 补。
- 框架**两者都支持**，`CapabilityModule.surface` 逐能力声明。core 固定 multi_tool。
- **browser 倾向 multi_tool**（对齐成熟 Playwright MCP、强类型 LLM 友好、CC 下零 token 代价），但"开放标准要兼容弱客户端"又偏向 gateway → **架构权衡点②**，请 architect 给结论。

### 3.5 能力契约与一致性

- `common/_canonical_tools.py` 维持不变 = **core 设备通用契约**（CORE+OPTIONAL，跨平台一致性）。
- 每个可选能力有**自己的契约 dict**（如 `common/capabilities/browser/_contract.py` 的 `BROWSER`），配套 conformance 单测；与 core 契约同模式但独立。
- legacy guard（`test_no_legacy_naming.py`）机制对能力工具同样适用。

### 3.6 跨平台共享

- OS 无关能力（`browser` CDP/DOM）落 `common/capabilities/browser/`，**多平台 server 共同挂载**（避免 4× 重复）——这是"开放标准 + 一个 agent-fleet 全包"的关键。
- OS 相关能力可落各 `platforms/<os>/`。框架对两类一视同仁（模块声明 `platforms`）。

### 3.7 配置（`platform.toml` 新增 `[capabilities]`）

```toml
[capabilities]
enabled = ["core", "browser"]   # 该 host 挂载哪些；core 始终在
# 可选 per-host 覆盖：<repo_root>/.fleet/config.toml（与 fleet-cli 设计同源）
```
- server 启动读取 → 只挂载 enabled ∩ 平台适用 ∩ availability。
- 改动经 (重)连生效；fleet-cli 后续提供 `fleet capability list/enable/disable`（与 `2026-05-24-fleet-cli.md` 的 ServiceController 同体系，本批不实现）。

---

## 4. skill 层（每能力一份）

- 现状 skills 每平台一个（`using-mac`）。新增**能力级 skill**：如 `using-fleet-browser`，含动作词表 + 决策树（参考 element-action SKILL 的 not_found/ambiguous 决策树范式）。
- `list_capabilities` 的 `skill` 字段指向它；可在能力工具的 description 里反向点名 skill，提升 agent 主动加载率。

---

## 5. 落地分期（每阶段过 review gate）

- **Phase 1（纯框架，零行为变化）**：`CapabilityModule` 抽象 + 挂载机制（X/Y 二选一）+ 现有工具收编为 `core` 模块 + `list_capabilities()` + `[capabilities]` 配置读取。四平台冒烟（工具集与现在完全一致）。
- **Phase 2（首个能力 + 整链路验证）**：`browser`（CDP/DOM，共享模块）在**一个平台**（建议 mac 或 win）打通：navigate/snapshot/click/type/...（粒度按 3.4 定）+ `using-fleet-browser` skill + 契约 + 真机验证。参考 Playwright MCP 的 snapshot/ref 模型与工具划分。
- **Phase 3（server 端可控 + CLI）**：`[capabilities]` enable/disable 经 fleet-cli 暴露（接 fleet-cli 设计）；多平台铺开 browser。
- **Phase 4（开放标准，文档为主）**：第三方加 `CapabilityModule` 的接入文档 + 样例。

---

## 6. 风险与缓解

- **非 CC 客户端仍看到全部静态工具（token）**：multi_tool 在弱客户端会膨胀 → 缓解 = server 端按 config 停用不需要的能力 + 对动作多的能力用 gateway（3.4）。
- **能力依赖重**（browser 需 Chromium/CDP）：`availability()` 缺失时报 `unavailable + 原因`，不让工具静默失败；安装走 setup/fleet-cli。
- **FastMCP 版本漂移**（mac 3.3.1=排除版）：落地前对齐 pin（尤其若用 `mount()`/tags 等 v3 特性）。
- **mount() 前缀 vs 现有平铺工具名冲突**（若选 Y）：core 不加前缀、可选能力加 `browser_` 等前缀，约定清楚。
- **"开放标准"过度设计**：Phase 4 仅文档，框架先服务自家 core+browser，不提前抽象未验证的扩展点。
- **skill 加载不稳**：靠 `list_capabilities` 强指向 + 工具 description 反向点名缓解；真机观察 agent 是否主动加载。

---

## 7. 给 architect 的关键决策点（请逐条结论）

1. **挂载机制**：`mount()` 子 server（Y，倾向）vs 条件注册（X）—— 哪个更稳、更利于模块化与第三方接入？v3 `mount()` 在连接时组合是否有坑（前缀/tag/中间件/性能）？
2. **browser 工具粒度**：multi_tool（Playwright 形态，倾向）vs gateway 胖工具 vs 框架支持两者-逐能力声明（倾向）—— 兼顾"CC 省 token"与"开放标准兼容弱客户端"该怎么定？
3. **browser 共享落 `common/capabilities/` 多平台挂载** 是否合理？CDP 进程/端点生命周期归谁管（每会话？共享？headless vs 接管真实 Chrome）？
4. **能力契约**：每能力独立 contract dict + conformance（仿 core）是否到位，还是过重？
5. **element-action 留 core** 是否认可（vs 独立成 ui-automation 能力）？
6. **Phase 1 收编 core 为单模块**（不细分）是否是正确的最小起步？是否有更稳的迁移顺序？
7. 对标成熟项目（Playwright MCP 的 snapshot/ref + 工具集、GitHub MCP "dynamic toolsets" 的能力分组思路、FastMCP `mount`/proxy 文档）后，本框架有无遗漏的已知坑或更优范式？

---

## 8. architect 审查结论与定稿增量（2026-05-24）

**总体结论：框架方向正确、可动工**。方案 C 判断链（spike→A 排除→静态注册+deferred 省 token→`list_capabilities` 发现面）成立；`CapabilityModule` 抽象、core 收编、跨平台共享 browser 均与 Playwright MCP / GitHub MCP 成熟实践一致。两个阻断级问题为可立即解决的设计缺口，不动摇方向。

**必须采纳（阻断级，优先级 1）：**
1. **挂载机制选定 = X（条件注册），不用 mount（推翻 §3.2 原倾向 Y）**。理由：FastMCP v3 `mount()` 是内存级直接挂载、`list_tools()` 仍穿透到子 server，且在"连接时静态确定工具列表"这点上与条件注册**对客户端完全等价**;但条件注册免去子 server 实例/前缀规则/mount 生命周期，代码量约 1/3，`tags={id}` 同样可用，第三方接入只需实现 `register(mcp)`。`mount()` 唯一实质优势(运行时隔离/动态卸载)因"(重启)生效"约定而非刚需。→ `CapabilityModule.register(self, mcp: FastMCP) -> None` 直接把本模块工具注册到主 mcp。**§3.2 作废 Y，§3.1 接口按此定稿。**
2. **修正"生效"措辞 = server 进程重启后生效,不是"重连"**(对标 GitHub MCP dynamic toolsets:toolsets 进程启动时读 flag/env、会话内不可变)。`platform.toml`/`.fleet/config.toml` 是**进程启动时**读取;FastMCP streamable-http 下"重连"≠"重启进程"(同进程可被多客户端连)。触发配置变更的正确入口 = `fleet service restart`。**全文 "(重)连生效" 改为 "server 进程重启后生效"。**

**强烈建议（质量，优先级 2）：**
3. **FastMCP 版本对齐升为 Phase 1 前置硬阻断**(非"风险")。`mount` 不用了但 tags 仍是 v3 特性,且 mac 真机 3.3.1 = pyproject 排除版(有已知 bug)→ 不对齐 Phase 1 冒烟必挂。**Phase 1 首条任务 = 全真机 FastMCP 版本对齐 + pin**(win 3.2.4→3.3.x、mac 换掉 3.3.1)。
4. **`availability()` 启动时探测一次并缓存**,`list_capabilities()` 支持 `refresh=true` 强制重探(browser 探 Chromium/CDP 端口是 IO,不能每次调用都探)。
5. **`list_capabilities()` 响应每能力加 `usage_hint`**(1-2 句关键用法内联),不把引导**唯一**寄托于 agent 主动加载 skill(实测不稳);完整 skill 作深化补充。

**采纳（完成度，优先级 3）：**
6. **阻断问题 2 文字补丁**:§3.3 `tools` 字段明确 = "agent 可直接 ToolSearch 的完整工具名"(条件注册下由模块命名约定确定:core 不加前缀、browser 工具自带 `browser_` 前缀)。
7. **`register()` 接口写清**:选 X 后直接注册到主 mcp,Phase 1 实施说明禁止 X/Y 混用。
8. **`[capabilities]` 合并规则**:`.fleet/config.toml` 覆盖 `platform.toml`;两者皆无 → 默认只启用 `core`(对齐 fleet-cli §8.2 的 `.fleet/config.toml`)。
9. **Phase 1 末产出 browser `_contract.py` 初稿**(工具名+参数骨架),否则 Phase 1 "browser 作验证用例" 无法验收;conformance 单测留 Phase 2 开头。

**§7 决策点逐条结论：**
1. **挂载机制 → X 条件注册**(见阻断 1)。
2. **browser 工具粒度 → multi_tool**(对标 Playwright MCP 21 个独立工具、强类型 LLM 友好;CC deferred 下零 token);框架保留 `surface` 字段允许将来某能力声明 gateway,但 browser 不是。弱客户端兼容靠 server 端 config 禁用整能力,不靠退化 gateway。
3. **browser 落 `common/capabilities/browser/` → 认可**;CDP 生命周期 = **共享单例 + 断连重连**(不每调用建断、不每会话独立 CDP——多 agent 并用会冲突);headless 与 attach_debug_port 两种 mode 经 capability config 切换。
4. **能力契约不过重 → 做,但 Phase 2**(Phase 1 末出草稿、Phase 2 开头写 conformance)。契约是跨平台多 server 一致性的唯一机械化手段,不可跳。
5. **element-action 留 core → 认可**(AX/UIA 设备基础能力、与 `tap(x,y)` 兜底紧耦合、对齐 android/ios 平台 core element 工具;独立成模块会变"强制选项",语义不符)。
6. **Phase 1 收编 core 为单模块 → 正确**;迁移顺序细化 = ① 先 `common/capabilities/` 建抽象基类+注册骨架(不碰 server 文件)→ ② 加 `list_capabilities()` 到 common → ③ 先**单平台(mac,工具最全便于验收)** core 模块化+config 读取并冒烟 → ④ 再铺其余三平台。"四平台冒烟" = 最后验收步,非每步同步。
7. **对标后两个遗漏(须补)**:
   - **(A) Playwright ref 模型**:browser 应对齐 `browser_snapshot` 返回 a11y tree + 每元素 `ref`(如 `e5`),`browser_click(ref="e5")` 用 ref 定位;ref 与页面快照绑定、DOM 变化后失效需重拍(server 无状态、agent 自管 ref)。**不用 CSS selector/坐标**。写进 Phase 1 末 browser 契约草稿。
   - **(B) 生效措辞**:见阻断 2,"进程重启后生效" + `fleet service restart` 为入口。

来源:Playwright MCP(github.com/microsoft/playwright-mcp、playwright.dev/mcp/snapshots,21 工具+ref 机制)、GitHub MCP(github.com/github/github-mcp-server,dynamic toolsets 进程启动生效)、FastMCP 组合文档(fastmcp.wiki/en/servers/composition,mount vs import_server、list_tools 延迟)、FastMCP 3.0 博客、Claude Code issue #46426(会话内新增 MCP 需重启 session,印证 spike)、本仓库 `mac_device_mcp.py`/`_canonical_tools.py`/`_manifest.py`/element-action+fleet-cli 设计文档。

---

## 9. 能力实现策略增量:嫁接成熟 MCP + browser 双档(2026-05-24,审查后讨论定向)

> 本节是 §8 之后与用户进一步讨论的设计增量,**精化并部分取代前文 browser 相关设想**(§3.4 倾向、§8 决策点 2/3、§7-gapA 的"手写 CDP+Playwright ref")。框架级结论(§8 决策点 1/4/5/6 等)不变。

### 9.1 框架级:能力模块的两种实现(self-built / proxied)

不重复造轮子——成熟领域 MCP 直接**嫁接**。`CapabilityModule` 据此分两类实现:

- **self-built(自建型)**:`register()` 注册手写工具。走护城河(操控这台物理设备本身)。例:`core`、element-action、**`human_browser`**。
- **proxied(代理型)**:`register()` 内用 FastMCP `as_proxy()` 包一个**在该 host 本地跑着的成熟 MCP**(stdio 子进程 / localhost http),挂到主 server,工具透明转发。例:**`agent_browser` = 嫁接 Playwright MCP**。

两类**共用同一** `list_capabilities` 发现面 / server 端开关 / skill 层;`list_capabilities` 每能力标注 `origin: "self-built" | "proxied"`,供按**信任级别**开关。→ 框架因此成为"统一管理 + 透明能力提供"层,无论底层自家代码还是嫁接。

**自建 vs 嫁接判据**:"该能力是否关于操控这台物理设备本身?" 是 → 自建(护城河,无轮子可造);否、但需跑在设备上且有成熟 MCP → 嫁接;完全不绑设备(云 API/DB)→ 可嫁接但低优先。

### 9.2 总原则:fleet 保持真实,**永不 headless**

只提供**有界面、可端到端测试的真实浏览器**。agent_browser 也是 **headed CDP**,不跑 headless。这是产品立场(真机 E2E 保真),也意味着 host 必须有活动 GUI 会话。

### 9.3 browser = 两个独立能力模块(双档 + 路由)

| | **human_browser**(self-built) | **agent_browser**(proxied=Playwright MCP) |
|---|---|---|
| 用途 | **全权人类代理**:操作真实账号、配置信息等"作为人本人"的操作 | 端到端测试 / 痕迹无所谓的浏览·搜索·自动化、agent 浏览器学习 |
| 实现 | 启动**真人日常 Chrome(无 debug 端口)**,`take_screenshot` + 视觉识别 + **OS 级坐标点击/输入**(复用 core 护城河) | 嫁接 Playwright MCP(headed CDP),`browser_snapshot`+`ref` DOM 语义操作 |
| 自动化痕迹 | **零**(无 CDP/无 webdriver/无自动化接口可测;输入是 OS 真实事件;残留仅行为信号=同真人) | **有**(webdriver/CDP 可被检测,设计上接受) |
| 代价 | 放弃 DOM → token 高、精度低(像素/布局敏感)、慢、读页面靠 OCR/视觉 | 依赖重(node+浏览器)、上游版本漂移、有痕迹 |
| 定位/读取 | 截图+视觉坐标(基线);可选增强见 §9.4-5 | DOM snapshot + ref(快准省 token、干净抽文本) |

**路由规则**:任务**触碰真实账号/真实身份**(全权人类代理)→ **human_browser**;其余 → **agent_browser**。**默认偏安全**:一旦涉及真人身份,默认 human_browser,避免把 CDP/自动化痕迹沾到真人身份上。purpose/scenario 写进各自 skill,由 agent 据此选档。

### 9.4 落地前必须钉死(交 architect 审)

1. **profile/实例拓扑**:human_browser = 真人日常 Chrome(**绝不开 debug 端口**);agent_browser = **另起** headed+CDP 实例,profile 与真人身份**隔离**。这是两档"互不污染"的关键(CDP 痕迹勿沾真人账号)。
2. **身份/会话归属**:human = 真登录态;agent = 独立身份(待定)。
3. **独占 vs 并发**:human_browser **独占物理屏幕+输入** → 必须接入设备 `acquire/release` 单 holder;agent_browser 走 CDP 另窗,冲突小。两档能否同时在线、谁优先,需定。
4. **headed-only 运维前提**:host 必须有**活动 GUI 会话**(macmini 上踩过"无显示会话致控制失败"的坑)→ `availability()`/setup 检查。
5. **(可选)human_browser 定位增强**:Chrome 可向 OS 无障碍树(UIA/AX,需 `--force-renderer-accessibility`)暴露部分网页结构 → "无障碍树定位 + OS 输入",**仍零 CDP**、比纯像素稳。值不值得做请 architect 评;基线仍是截图+坐标。
6. **能力建模**:两个独立模块(倾向,工具面/语义/开关都不同)vs 一个 browser 能力下两 mode。请 architect 定。
7. **Playwright MCP 接入校验**:确认它支持 **headed + attach 真实/独立 Chrome(`--cdp-endpoint` 等)+ 不强制 headless**,以及 stdio/http 哪种代理拓扑最稳。

### 9.5 风险增量(并入 §6)

- **信任/供应链(最重)**:嫁接 = 在真机、甚至个人机(win-device-qjl)上跑三方 MCP 代码 → pin 版本、审来源、个人机更谨慎;`origin:"proxied"` 供 server 端按信任开关。
- **依赖重量**:Playwright 拖 node+浏览器二进制 → fleet-cli setup + `availability()` 缺失即报。
- **双档 profile 污染**:见 §9.4-1 隔离。
- **human_browser token/精度代价**:已知,靠"仅用于真身份代理"的用途约束控制频率。
- **合规边界**:拟人/零痕迹能力**仅限自有设备、自有/授权账号、授权测试与正当浏览学习**,非用于大规模绕过检测/滥用服务。

### 9.6 分期影响

- §5 Phase 2 的"browser"改为 **agent_browser(嫁接 Playwright MCP)** 先行(整链路验证代理型模块);**human_browser** 作为 Phase 2b(自建,复用 core OS 输入 + browser 专属 skill)。
- Phase 1 末契约草稿:agent_browser 对齐 Playwright 工具面;human_browser 工具多为 core 复用 + 少量 browser 专属(开浏览器/地址栏导航/截图读取)。

## 10. architect 复审结论(§9 专项,2026-05-24)

**总体:"嫁接+双档"方向可行、认可动工**。self-built/proxied 分类务实、双档隔离安全逻辑成立;Playwright MCP 默认即 headed、`--cdp-endpoint` 可 attach、`--isolated`/`--user-data-dir` 控 profile、FastMCP `as_proxy()` 路径均已核实可行。风险不在方向,在两个实现细节(并发冲突、代理性能)须先钉死。

**必须采纳(阻断级,优先级 1):**
- **A. 并发/独占粒度**:现有 `DeviceStateRegistry` 是**整机级单 holder**(`_SERIAL="host"`),粒度不匹配——human_browser 独占的是"物理屏幕+输入焦点",agent_browser 独占的是"那个 CDP 浏览器进程",非同一资源;若 human 去 acquire "host" 会错误驱逐正在跑的 agent_browser。**定论(方案甲)**:两档**可同时在线**;human_browser 工具调用前做**轻量前台焦点检查**(OS API 查 foreground window 是否被 agent Chrome 占据,否则报冲突),**不接 acquire/release**;agent_browser 完全不需要 holder。写进 human_browser 模块 `register()` 前置逻辑。
- **B. `as_proxy()` 性能(已知 bug `fastmcp#1583`)**:fresh-session-per-request 策略每次多一次 MCP init 握手(HTTP 场景实测 list +300-400ms、exec +200-500ms);对 browser 操作序列(导航→截图→点击→截图)往返影响不可忽视。**定论**:**Phase 2 第一步不是写代码,是原型量测**——`as_proxy()` 包 Playwright MCP stdio 子进程,连调 `browser_navigate`+`browser_snapshot` 量端到端延迟;**>2s/次则改"共享 Playwright MCP 子进程 + session reuse"**。结论须 Phase 2 第一周产出,否则后续可能整体返工。

**强烈建议(优先级 2):**
- **C. agent_browser 用 Playwright MCP 子进程自启 + `--user-data-dir` 隔离 profile,不用 `--cdp-endpoint` attach**。attach 模式(`connectOverCDP`)官方标注 fidelity 显著更低(页面事件/a11y 覆盖可能失效),且 agent_browser 本就要隔离 profile、用不到复用真人 profile。**§9.4-7 "attach 真实 Chrome" 降级为可选运维 opt-in、非基线。**
- **D. `as_proxy()` 工具前缀主动管理**:Playwright 工具名已自带 `browser_`,再加 capability 前缀会变 `agent_browser_browser_navigate`。`register()` 里传 `prefix=""` 或明确对齐前缀策略,Phase 1 末契约草稿写清工具名形态。

**完成度(优先级 3):**
- **E. §9.5 风险补两条**:① `as_proxy` fresh-session 对高频 browser 调用的延迟(量测前为未知风险);② Chrome 146+ 在做原生 MCP 接入(无需 debug 端口),将来 agent_browser 可有更简洁路径,Phase 3 评估。
- **F. §9.6 Phase 1 末产出加一条**:在 mac 或 win 任一真机手工跑通 "Playwright MCP stdio 子进程 → `as_proxy()` 包装 → `list_capabilities()` 显示 agent_browser 工具列表",把工具名形态 + headed 确认记进契约草稿。

**§9.4 七点逐条定论:**
1. **profile/实例拓扑**:human = 真人日常 Chrome(**无 debug 端口**,`launch_app`/`open -a` 启动,不接任何 CDP);agent = Playwright MCP 子进程自管 Chromium,`--user-data-dir ~/.fleet/agent-browser-profile`,headed、非 headless、非 attach。两进程两 profile 目录,天然隔离。
2. **身份/会话**:human = 真登录态(代理本人);agent = 独立身份,Phase 2 先"空 profile 干净启动、不注入账号",测试账号池留 Phase 3+。
3. **独占/并发**:见阻断 A——两档可并行,human_browser 自带轻量前台检查,**不强依赖 acquire/release**。
4. **headed-only 运维门禁**:**必须**写进 `availability()` + setup(非可选,两模块共同门禁)。macOS 用 `CGSessionCopyCurrentDictionary`/`who` 验活动 GUI 会话,Windows 用 `query session` 查 active 控制台;失败即报 `unavailable:"no active GUI session"`。
5. **human_browser OS 无障碍树定位增强 → 明确不做(Phase 2b 基线)**。三因:① 代码注释已确认网页内容不在 UIA/AX 树(已知限制),`--force-renderer-accessibility` 也只暴露 Chrome 自身 UI 框、不暴露网页 DOM;② 该 flag 稳定性边界模糊;③ 需精确 DOM 就**路由到 agent_browser**,不给 human_browser 打补丁。**§9.4-5 从"可选增强"改为"明确不做,理由在案"。**
6. **两个独立模块 → 认可**(工具面/开关/skill 全不同,合并成 mode 参数会让发现面含糊、选档逻辑写死)。
7. **Playwright MCP 接入校验 → 全部确认**:headed 为默认(headless 是 opt-in,与 §9.2 "永不 headless" 零配置对齐);`--cdp-endpoint` 支持但主路径不用;`--user-data-dir` 隔离 profile 可用;**代理拓扑 = stdio 子进程**(fleet server 启动时 spawn Playwright MCP,`as_proxy()` 包装挂主 mcp;比 localhost http 少一跳、生命周期随 fleet 进程管)。

**"零自动化痕迹"卖点 → 技术上基本成立,但须加边界(写进 skill,不只设计文档):**
- 成立:不开 debug 端口 → 无 CDP 可探、`navigator.webdriver` 维持 false;OS 输入经系统消息队列 → `isTrusted=true` 是**真实**的(非 CDP 注入欺骗);不注入 JS → 无 `$cdc_`/WebDriver 变量。
- 边界:**行为信号仍可被采样**(pyautogui 线性瞬移非人类轨迹) → human_browser **不是万能防检测**,对行为分析型反爬(如 Cloudflare Bot Fight 鼠标轨迹分析)仍有识别风险,只是远好于 CDP 路径。**合规声明须在 skill 同步出现。**

**分期**:agent_browser=Phase 2、human_browser=Phase 2b 合理;**Phase 2 开工前插"量测检查点"(阻断 B),一周出结论再定代理拓扑实现。**

来源:Playwright MCP 配置文档(playwright.dev/mcp/configuration/options:headed 默认/cdpEndpoint/profile)、Playwright MCP 仓库、FastMCP Proxy 文档(gofastmcp.com/servers/providers/proxy)、`fastmcp#1583`(as_proxy 性能)、FastMCP proxy session 隔离 PR #1083、Castle.io(CDP 检测 / stealth 演化)、MDN `Event.isTrusted`、Chromium 无障碍树架构文档、BrowserStack `connectOverCDP` 说明、本仓库 `win_device_mcp.py`/`mac_device_mcp.py`(find_elements 注释:web 内容不在 UIA/AX)/`_device_state.py`(整机单 holder)。
