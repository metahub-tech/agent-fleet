# human_dom 能力模块设计：human_browser 的 DOM 感知（保持 human 特征下的精确定位）

> 状态：设计稿（待 architect 审 + 用户复核后转 writing-plans）· 2026-06-24
> 目标读者：核心维护者 + 未来贡献者
> 关联：
> - human_browser `platforms/common/capabilities/browser/_human_browser.py` + skill `using-human-browser`
> - vision 定位 `docs/internal/design/2026-06-04-vision-localization-capability.md`（同一套"定位/操作分离"心智，本设计复用其 OCR 作兜底）
> - **CDP 反检测分析 `docs/internal/design/2026-05-25-cdp-antibot-detection-analysis.md`**（stealth 论证以它为基线，§3）
> - 能力模块框架 `docs/internal/design/2026-05-24-capability-module-framework.md`
> - 受管拉起 helper `platforms/common/_server_runtime.py`（本地桥复用其 HTTP app）
> 原则：从需求来、回需求中去——每个决策都能追回一条真实需求（见 §1、§2）。

---

## 一、需求与场景（先从用户视角说清「为什么」）

### 1.1 真实处境
运营 agent **pulse**（跑在 macmini / mac-device）发布小红书，必须以 **秦Pi 真人账号** 操作 → 只能走 **human_browser**：启动宿主真实日常 Chrome（真 profile / cookie / 登录态、OS 级真鼠键、零自动化痕迹）。

但 human_browser **设计上零 DOM**：`human_browser_open(url)` 只负责启动 Chrome，之后所有操作走 core 的 `take_screenshot + tap(x,y) + type_text`——**每一次点击的坐标都靠"看截图"得来**（agent 用 VLM 眼估，或走 OCR）。

### 1.2 痛点（实测）
- **2026-06-23 一次交互式小红书发布，human_browser 卡 40+ 分钟未成功**，现象=视图坐标反复点错。
- 即便同日 headless cron 那次成功发出，也**持有 mac-device 1104s ≈ 18 分钟**（人手发只需 ~2min）。
- 根因：小红书发布页（图片上传位、富文本编辑器、`#话题` 自动补全、封面九宫格、"发布"键）布局动态、大量非文字目标，对"截图 + 坐标"极不友好；VLM 眼估坐标实测**中位 120px 误差**（见 vision spec §1.2），一 miss 就重试，叠起来就是 40 分钟。

### 1.3 需求一句话
> 在 **完全保持 human 特征（真实身份 + OS 级真输入 + 零自动化痕迹）** 的前提下，给 human_browser 一条 **DOM 级精确定位** 路径，把它要点的那个元素坐标稳稳拿到，终结"坐标一直出错"。

### 1.4 成功判据（验收对着这些）
1. 小红书发布页 `human_dom_locate('发布' / '标题' / …)` 命中正确元素、换算出的屏幕坐标落点准（tap + 截图确认）。
2. **小红书发布 e2e**（开页 → 填标题/正文/话题 → 选封面 → 发布）一次跑通，且显著快于现状的 18–40min。
3. **stealth 不变量保持**：`navigator.webdriver` 仍 false、无 CDP / 无 debug 端口、真实 profile、操作仍 OS 级真输入。
4. **通用**：非小红书站点同样能 `locate`（设计做成通用，第一个验收锚定小红书这条最硬流程）。

---

## 二、关键决策与追溯

| 决策 | 追回的需求/约束 | 理由 |
|---|---|---|
| **感知/操作分离**：DOM 只负责"定位"，操作仍走 core OS 级 tap/type | §1.3 保持 human 特征 | "human 特征" = 真实身份 + OS 级真输入（L4），**与读不读 DOM 无关**（§3）。读 DOM 只换"感知后端"。 |
| 读 DOM 的通道 = **Chrome 扩展 content script**（不用 CDP、不用 a11y） | §1.3 零自动化痕迹 + 真人高价值账号封号代价 | 三条零新增面通道里，扩展在**所有层**最干净（连 L3 本地 debug 通道都没有）、最通用最可靠；用户已拍板（§3 给出与既有 CDP 分析一致的论证）。 |
| 本地桥 **复用 server 现有 HTTP app** | 不加新进程、复用既有设施 | `_server_runtime` 已暴露 Starlette/FastMCP HTTP app（#58/#59），加一条 `127.0.0.1` 路由即可，可复用其 bearer 门。 |
| 工具面 **镜像 vision**（locate / tap / fill）+ **OCR 兜底** | 一致心智、复用已上线能力 | 与 `vision_locate/vision_tap` 同心智；DOM 拿不到的元素自然落回 `vision_locate`(OCR)。 |
| **mac 优先、设计通用** | pulse 跑 macmini；用户定"通用能力" | 复刻 win→mac 的分期节奏；扩展跨平台，坐标映射各平台各自标定。 |

---

## 三、stealth 论证（对齐既有 CDP 分析，保证不自相矛盾）

`docs/internal/design/2026-05-25-cdp-antibot-detection-analysis.md` 把自动化痕迹分四层，并实测得到一个**反直觉但重要**的结论：

| 层 | 谁能看到 | 结论（该分析实测） |
|---|---|---|
| L1 JS 指纹 | 任意网站 JS | 即便 agent_browser（CDP）也**几乎全过** |
| L2 CDP 协议 | 高级检测脚本 | 走 pipe + 不触发 Runtime.enable 副作用 → **基本探不到** |
| L3 进程/本地 | 宿主本机 / EDR | **暴露**（命令行标志、调试通道、profile）——但**网站看不到** |
| L4 行为 | 高级行为反爬 | **暴露**（合成输入轨迹非人类） |

**推论（本项目动机的精确表述）**：网站可见层（L1/L2）连 CDP 都基本干净，所以本项目真正要保住的，是 **L4（OS 级真输入，非合成）+ 真实身份（真 profile / cookie——agent_browser 用隔离 profile 拿不到）**。这两样 human_browser 本来就有，缺的只是 **DOM 精度**。

**为什么仍选扩展、而非"只读 CDP-via-pipe"**（即便后者按上表在网站层也可接受）：
- 扩展在 **L3 也最干净**——根本没有 debug 通道（CDP-via-pipe 仍在本地开了一条控制通道）；
- 扩展 content script 跑在 isolated world、**只读不改 DOM**、无 `web_accessible_resources`：页面 JS **无法通过常规 API 直接读取 content script 的上下文/变量**，只读不注入可探测符号 → **实际检出率极低**。（**诚实声明**：这是观察性结论、非密码学隔离——content script 的存在并非"物理不可见"：高级检测理论上可经 DOM mutation 时序、`MutationObserver` 触发等侧信道间接推断；对当前小红书量级足够，但"设计通用"下需正视。）
- 避免"误启 `Runtime.enable` → 触发经典 CDP 检测"这个工程脚枪；
- 对秦Pi 这种**真人高价值账号**，取最保守路径。`navigator.webdriver` 全程 false、全程无 CDP。

> **一个 L3 空白待 spike**：扩展走"手动 Load unpacked 进真实 profile"需开 Chrome Developer Mode。"开发者模式对网站 JS 不可见"目前是业界共识（页面无标准 API 读取该状态），但**本仓未实测**——列入 §十 spike：真机开 Developer Mode + 装扩展后，重跑 CDP 分析的 `bot.sannysoft.com` 探针集核验。

> CDP fast-mode（只读 CDP-via-pipe，按上表网站层可接受）作为"低风险/一次性账号"的 opt-in 留作未来，**v1 不做**（§十一）。

---

## 四、架构（数据流）

```
agent  ──human_dom_locate("发布")──▶ [MCP 工具 / server]
                                        │  op:locate(query)
                                        ▼
                          [本地桥 127.0.0.1 /dom-bridge]  ◀──WS──▶  [Chrome 扩展]
                                        ▲                              │ content script(active tab)
                                        │  candidates + viewport 几何   │ querySelector/文本匹配
                                        │                              │ → getBoundingClientRect (只读)
                                        ▼
                          [server: 视口坐标 → 屏幕坐标(point 空间)]
                                        │  候选 {text/role, center(屏幕), box, score}
                                        ▼
agent  ──human_dom_tap("发布")──▶ 内部 locate + core tap(x,y)   ◀── 操作仍 OS 级真鼠键
                                  （DOM 未命中 → 落 vision_locate(OCR) → VLM）
```
核心切分：**扩展只读 DOM 给坐标；所有"动作"仍是 OS 级真输入**——human 特征（L4 + 真实身份）原样保留。

---

## 五、组件详述

### 5.1 Chrome 扩展（MV3，只读）
- **manifest v3**；content script 按 `host_permissions` 注入目标页。
- **content script 职责**：收到 locate 请求 → 按 query（可见文本 / `aria-label` / `placeholder` / `title` / role + 可选 `css` 选择器）在 DOM 找候选 → 对每个候选取 `getBoundingClientRect()` + 文本 / role / 可见性 / 可点性 → 回传视口 rect 列表 + 当前视口几何。
- **只读铁律**：**绝不** `.click()` / `.value=` / 派发合成事件 / 改 DOM（动作归 OS 级 core 工具）；**无 `web_accessible_resources`**（降低页面探测扩展的可能；检出率极低但非密码学隔离，口径见 §3）。
- **连接持有方**：**content script 直连本地桥**（`host_permissions` 含 `http://127.0.0.1:<port>/*`），tab 存活即在线——**规避 MV3 service worker 易被杀的坑**。每个 content script 上报 `tabId / url / active`，server 优先应答 active tab。

### 5.2 本地桥（server 侧）
- **复用 server 现有 HTTP app**，但**挂载机制要点名**（architect 审出的实现盲区）：
  - FastMCP 的 `mcp.custom_route(path, methods=[...])`（`/health` 用的那个）**只支持 HTTP Route、不支持 WebSocket**——直接拿它挂 `/dom-bridge` 会 405/静默失败。**正确做法**：取 FastMCP 暴露的底层 Starlette app（`mcp.http_app(...)` 返回的对象），用 `app.add_websocket_route("/dom-bridge", handler)`（或在 `serve()` 前用外层 Starlette `Mount` 组合 WS handler 再交 uvicorn）。实现计划须先确认 FastMCP 这一版暴露 app/router 的具体入口。
  - **WS 不走 BearerAuthMiddleware**：现有 `BearerAuthMiddleware` 只在 `scope["type"]=="http"` 拦截，WS 升级请求 scope type 是 `"websocket"` → **直接放行、不经 bearer 门**。所以 WS 认证**要单独做**：连接 URL 带 `?token=<T>` 或首帧 `{type:"auth", token:<T>}` 校验（与 `serve()` 的同一 token），失败即关闭连接。绑 `127.0.0.1`。
- 协议（草案）：
  - server→ext：`{id, op:"locate", query, css?, max_results}`
  - ext→server（命中）：`{id, ok:true, candidates:[{text, role, rectViewport, visible, clickable}], viewport:{screenX, screenY, innerW, innerH, outerW, outerH, dpr, scrollX, scrollY}}`
  - ext→server（未命中）：`{id, ok:false, dom_candidates:[<可见文本前 N 条>], viewport:{…}}` —— **未命中也要回传若干可见文本**，供 §5.6 的 `dom_sample` 回传 agent 精化 query。
- **不做 long-poll 退化**：content script 直连 `http://127.0.0.1:<port>` 的 WS 在任何场景都可用，"WS 不可用但 long-poll 可用"无真实触发场景 → 删除，归 §十一 YAGNI。

### 5.3 坐标映射 viewport→screen（**头号技术风险**）
- 输入：候选 `rectViewport`（CSS px，视口相对，已含滚动）+ 视口几何（每次 locate 实时随包带回）。
- **明确公式（消除 DPR 歧义——architect 审强调，否则 Retina 必偏一倍）**：
  ```
  screen_x = window.screenX + rectViewport.left
  screen_y = window.screenY + (window.outerHeight - window.innerHeight) + rectViewport.top
  ```
  - `window.screenX/Y` 与 `getBoundingClientRect()` **都在 CSS 逻辑像素空间**；macOS 的 OS 点空间与 CSS px **1:1 对应**（DPR 由 OS 吸收）→ **坐标换算里不再乘 `devicePixelRatio`**。截图/`tap` 也在 point 空间（using-human-browser："截图像素 == tap 像素"），三者同空间。
  - `rectViewport` 已是滚动后、视口相对值（含 `getBoundingClientRect` 的滚动校正），故公式**不再额外减 `scrollY`**。
  - **页面 zoom**：`document` 级 zoom / `meta viewport scale` 会直接反映进 `rectViewport` 的值本身（不影响 `screenX/Y`），故无需单独项；`dpr`/`scroll*` 字段仅作诊断与跨平台（win）校准用，mac 主路径不参与上式。
- **标定 = 公式验证，不是存 offset**：`screenX/Y` 每次 locate 实时读取，窗口被移动也自动跟上 → **不需要、也不应存储偏移量**；标定只为在真机上验证上式正确（locate 已知元素 → 截图交叉验证落点）。映射置信低时**落 `vision_locate` 复核/兜底**。
- 这是"坐标不再错"的成败点，M1 真机标定。win 平台的 `screenX/Y`↔像素空间另行标定（§九）。

### 5.4 MCP 工具（能力模块 `human_dom`，镜像 vision）
- `human_dom_locate(query, css?, max_results?, tab?)` → 排序候选 `{text/role, center(屏幕), box(屏幕), score, visible}`
- `human_dom_tap(query, nth?, css?)` → 内部 locate + core `tap`（**locate+tap 合一**，缩小"定位到点击"间页面漂移的时间窗）
- `human_dom_fill(query, text, css?)` → locate + tap 聚焦 + `type_text`
- **query 语义**：默认对 可见文本 / `aria-label` / `placeholder` / `title` 模糊匹配 + role 过滤；`css` 可选精确选择器。排序：可见 + 可点 + 文本匹配度。

### 5.5 能力模块结构
- 新模块 `platforms/common/capabilities/human_dom/`（`origin = self-built`），与 human_browser **配对**（skill 写清：先 `human_browser_open`，再 `human_dom_*`）。
- **`availability()` 语义要划清**（architect 审：否则模块会"永远 unavailable"）：扩展是 content script 在用户**打开页面后才拨入**本地桥的，server 注册期根本不可能有扩展连入。所以 `availability()` **只探注册期能定的依赖**——① WS 库依赖是否就位；② `/dom-bridge` 路由能否绑定。**"是否有扩展在线"不归 availability**，那是**运行时** locate 调用的路由逻辑：桥无扩展连入 → 返回结构化错误 + 建议 `vision_locate`，绝不拖垮 server。
- `platform.toml [capabilities].enabled` 可选启用（mac 先开）。
- skill `using-human-dom`（或并入 `using-human-browser`）：DOM 路径用法 + 何时落 OCR。

### 5.6 降级链
DOM 桥未连 / 未命中 → **`vision_locate`(OCR)** → VLM 眼估。未命中带 `dom_sample`（命中的若干候选文本）回传供精化 query；**错误永不崩 server**。

---

## 六、扩展安装 / 分发
- **主**：一次性手动 "Load unpacked" 进真实 profile（持久驻留、无启动 flag、最不显眼）。扩展源随仓：`platforms/common/capabilities/human_dom/extension/`。
- **备**：`human_browser_open` 时可选 `--load-extension`（**非自动化指纹**，`navigator.webdriver` 仍 false；仅本地有"开发者模式"横幅、页面看不见）。**注意新版 Chrome 对 `--load-extension` 策略在收紧 → 以"手动装一次、持久驻留"为准。**
- 配一次性 setup 文档 + mac setup 脚本。

---

## 七、错误处理 / 安全护栏
- **content script 注入时序（architect 审：正常流程必撞，要定义）**：`human_browser_open(url)` 后页面还在 load、content script 尚未注入时调 `human_dom_locate`，桥里没有该 tab 的连接。行为定义：locate **短等 + 重试**（建议轮询桥 ~3s、间隔 ~300ms 等 active tab 的 content script 拨入），超时仍无 → 返回结构化"页面未就绪/桥无 active tab"错误 + 建议先 `take_screenshot` 确认页面 load 或落 `vision_locate`。skill `using-human-dom` 写明"`human_browser_open` 后等页面 load 再调 `human_dom_*`"。
- 桥未连 / 超时 / 错 tab / 未命中 / 坐标置信低 → 结构化错误 + 建议 `vision_locate`；**永不崩 server**。
- 仅自有设备 / 自有或授权账号 / 正当用途；扩展只读；操作 OS 级；桥绑 `127.0.0.1` + 可选 token 门。

---

## 八、测试策略
- **单测**（纯逻辑、平台无关，跟 `_server_runtime` / vision 测试同一路子，Linux CI 可跑）：坐标映射数学（含 Retina / scroll / zoom 边界）、query 匹配与排序、桥协议编解码。
- **扩展逻辑**：用 Playwright 加载扩展、断言 rect / 候选上报（**仅测试态**，不碰 stealth 生产路径）。
- **真机（macmini）**：小红书发布页 `locate` 落点验证；**小红书发布 e2e 作首个验收**（§1.4）。
- 提醒：CI 不覆盖 `platforms/common/tests` / server 测试（见 `reference-agentfleet-ci-coverage-gap`），相关 pytest 需本地实跑。

---

## 九、平台与里程碑（建议分期）
- **M1**：扩展 + 本地桥 + `human_dom_locate`（mac）；小红书发布页 locate **落点真机验证**（坐标映射标定）。
- **M2**：`human_dom_tap` / `human_dom_fill` + 降级链；**小红书发布 e2e 验收**。
- **M3**：能力模块接线 + `using-human-dom` skill + setup 文档/脚本 + 真机回归。
- **（后）**：win 推广（坐标映射各自标定）；CDP fast-mode opt-in（§十一，YAGNI 暂不做）。

---

## 十、风险与待 spike
1. **坐标映射准确度**（§5.3 公式在 Retina / 多屏 / 页面 zoom）——M1 真机标定（公式验证），兜底 OCR 复核。**最高风险**。
2. **扩展加载策略**（Chrome 版本对 `--load-extension` 收紧）——以手动持久 + setup 脚本兜底。
3. **MV3 / 连接保活**——已用 content-script 直连规避 SW 死亡；多 tab 的 active 选择需实测。
4. **桥挂 WS 的具体 API**——FastMCP `custom_route` 不支持 WS（§5.2），实现计划须先确认这一版 FastMCP 暴露底层 Starlette app/router 的入口（`add_websocket_route` / 外层 `Mount`）；WS 认证单独做（不经 BearerAuthMiddleware）。
5. **Developer Mode 的 L3 可见性**（§3 空白）——真机开 Developer Mode + 装扩展后重跑 `bot.sannysoft.com` 探针集，核验"开发者模式 + 扩展"对网站 JS 仍不可见、`navigator.webdriver` 仍 false。

---

## 十一、非目标（YAGNI 红线）
- 默认路径**不用 CDP / debug 端口**（CDP fast-mode 留未来 opt-in）。
- 扩展**不做 DOM 级操作**（不 `.click` / 不 `.value=` / 不派发合成事件）——动作永远 OS 级。
- **不替代 human_browser**（是其伴生能力）。
- **v1 不做 win**（mac 先验证）。
- 不做"自动融进 `find_elements`"。
- **不做 long-poll 退化**（§5.2：content script 直连 127.0.0.1 WS 恒可用，无真实触发场景）。
