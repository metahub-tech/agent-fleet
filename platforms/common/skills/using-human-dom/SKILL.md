---
name: using-human-dom
description: Use when you need DOM-level precision (exact text/aria/placeholder matching → screen coordinates) while operating the host's real Chrome with human identity and zero automation traces. human_dom adds a read-only DOM locator alongside human_browser; all actions remain OS-level (tap/type_text/press_key). When the DOM locator misses (canvas, custom widgets, dynamic overlays) it falls back to vision_locate (OCR).
---

# Using human_dom

`human_dom` is a **DOM-perception companion** to `human_browser`: it extends the same zero-trace, real-profile, OS-level operating model with a **read-only DOM locator** sourced from a Chrome extension content script.

The extension **only reads** — it never clicks, never mutates the DOM, never injects synthetic events.  All input is still genuine OS-level: `tap`, `type_text`, `press_key`.  The result is DOM-accuracy coordinates delivered as screen points in the same space as `take_screenshot` and `tap`.

## 三选一路由（routing）

| 场景 | 用哪个 |
|---|---|
| 真实账号/身份 + 需要 DOM 精确定位（文字/aria/placeholder 匹配） | **human_dom**（本 skill） |
| 真实账号/身份，DOM 拿不到（canvas、自定义控件、动态悬浮层）或 human_dom_locate 返回 `suggest:"vision_locate"` | **vision_locate**（OCR 兜底），操作仍用 OS 级 tap/type_text |
| 自动化测试 / 抓取 / 隔离 profile / 无需真实身份 | **agent_browser**（Playwright，有 automation traces，独立 profile） |

**核心判断**：需要真实身份 → 选 human_dom 或 vision_locate 而非 agent_browser。需要 DOM 精度 → human_dom 优先；DOM 不可达 → OCR 兜底。

### human_browser 上元素定位的优先级顺序

在 human_browser 打开页面后，定位元素按以下优先级尝试：

1. **human_dom**（首选）：DOM 语义匹配，精确、0 token、抗动态遮罩，命中率高。
2. **vision_locate**（OCR 兜底）：DOM 拿不到时（canvas/shadow DOM/动态悬浮层），OCR 识别屏幕文字返回坐标；操作仍用 OS 级 tap/type_text。
3. **截图 + VLM 眼估**（最后手段）：take_screenshot 后让模型目测坐标，仅当 OCR 也失败时才用。

| 方法 | 精度 | token 消耗 | 适用场景 |
|---|---|---|---|
| human_dom | DOM 像素精确 | 0 | 有文字/aria/placeholder 的标准元素 |
| vision_locate (OCR) | ~1px | 极少 | canvas、自定义控件、动态覆盖层 |
| 截图 + VLM | ~5–20px | 高（图片 token） | OCR 也失败的极端情况 |

### 实战分工：表单字段用 human_dom，自定义按钮常需 vision 兜底

real-machine（小红书 / 公众号发布）经验，钉成规范：

- **标准表单字段**（标题 `<input>`、`<textarea>`、`[contenteditable]` 正文）→ **human_dom**（`human_dom_fill` / `human_dom_locate`），DOM 精确、0 token。
- **页面自定义按钮 / 控件**（底部固定栏的「发布」「暂存离开」、开关、话题下拉项、上传封面按钮等，多为 `div[role=button]`）→ 文字常**不进 human_dom 文本索引**（`human_dom_locate` 返回 `suggest:"vision_locate"`），改用 **`vision_locate` / `vision_tap`** 兜底，实测精准命中。
- 经验法则：**输入走 human_dom；点按钮先 human_dom，拿不到立刻转 vision**——不要在一个拿不到的按钮上反复 `human_dom_locate`。

### human_dom 的两层启用模型（先搞清楚再排错）

human_dom 能用 = **两层都满足**，排错时先分清缺哪一层：

| 层 | 是什么 | 缺了会怎样 | 怎么补 |
|---|---|---|---|
| ① host 级 provisioning | 标记文件 `~/.fleet/human-dom-ready` 存在（server **启动时静态判定**，决定 human_dom 工具**注册不注册**） | `list_capabilities` 里 human_dom = `unavailable`，**根本没有 human_dom_* 工具** | 跑安装脚本（mac `install-human-dom-extension.sh` / win `install-human-dom-extension.ps1`，**引导在目标 profile 手动 Load unpacked + 自动写 marker**），或手动 `run_shell` 建 marker（见 per-profile 节）。**写完 marker 必须重连 / 重启 server** 才注册（框架不动态增删工具） |
| ② profile 级 扩展 | human_dom 扩展**已加载进你当前浏览的那个 Chrome profile**（扩展是 per-profile 副本，每份烤入了该 profile 的桥端口 + profile_id） | 工具在，但 `human_dom_locate` 对该 profile 的页面拿不到元素，或路由到别的 profile | 副本现在由 **`human_browser_open(profile=X)` 自动烤**（起专用 profile 时算 profile_id+读桥端口生成 `~/.fleet/human-dom-ext/<id>/`，路径在其返回的 `human_dom_ext` 字段；无需另跑安装脚本——见下节第 0 步），再用 **chrome://extensions 持久 Load-unpacked 那个副本目录**（`--load-extension` 在 Chrome137+ 已禁用） |

先 `list_capabilities`：
- **human_dom = unavailable**（无 marker）：缺第①层。补 marker + 重连 server 即注册（mac 跑 `install-human-dom-extension.sh` / win 跑 `install-human-dom-extension.ps1`，脚本会自动写 marker；或手动建 marker，见下）。补好前先用 `vision_locate` 顶着。
- **human_dom = enabled 但 locate 拿不到 / 路由错**：缺第②层——你浏览的 profile 没装（对应 profile_id 的）扩展副本，按下节为该 profile 生成副本并 Load-unpacked。`human_dom_status()` 可一眼看出每个 profile 装没装 / 连没连。

## 为一个【新 profile】启用 human_dom（per-profile 启用）

**关键事实：human_dom 扩展是 per-Chrome-profile 副本，桥按 profile 路由。** 真账号 operator 常固定一个**专用持久 profile**（`human_browser_open(profile="~/.fleet/<account-id>")`，见 using-human-browser）；这个新建 profile **默认没装 human_dom 扩展**——即使 host 级 marker 在、human_dom 工具可用，对它的页面也定位不到。

> ★ **三处同一 profile 串铁律（最重要）：** `human_browser_open(profile=X)`、装扩展时传的 `PROFILE`、`human_dom_locate/tap/fill(profile=X)` —— 这**三处必须用同一个 profile 串**。桥**按 profile 路由**（不再全局猜 active tab）：调用方必须传「操作哪个 profile」，桥才把请求路由到该 profile 那张 tab。**不传 `profile` = 操作默认日常 Chrome**（`profile_id="default"`）；操作专用 profile 必须**显式传**，否则路由到 default 上找不到 / 找错。
>
> 每个 profile 各自装一份扩展副本（副本里烤入了该 profile 的桥端口 + profile_id）。多 profile 各传各的 `profile`，桥按 profile 隔离，**不会串线**（不再依赖「最小化别的窗口」那类规避 active-tab 串扰的 hack）。

> ⚠️ **`--load-extension` 命令行加载在 Chrome 137+ 已被 Google 禁用**（防恶意软件；本机实测 Chrome 148 完全失效，旧逃生开关 `--disable-features=DisableLoadExtensionCommandLineSwitch` 也失效）。所以**唯一可靠路径是 chrome://extensions 持久 Load-unpacked**——一次性、跨 run 持久、扛得住封禁。下面这套**视觉 agent 可全程自助**（test-win11 真机端到端验证过）。

### 自助 Load-unpacked 装扩展（视觉 agent 流程，已真机验证）

为专用 profile `~/.fleet/<account-id>` 装 human_dom 扩展，一次性。**全程认准同一个 PROFILE 串**（= 后面 `human_dom_locate(profile=...)` 要传的那个）：

0. **起该 profile（这一步会自动烤好扩展副本）**：`human_browser_open(profile="~/.fleet/<account-id>")`。
   - ★ **auto-bake（最省事，别漏）**：起【专用 profile】时 human_browser_open **自动为它烤好扩展副本**（算 profile_id + 读本 server 桥端口 → `~/.fleet/human-dom-ext/<profile_id>/`）；**副本目录路径在返回的 `human_dom_ext` 字段里**，第 3 步直接选它，**无需另跑安装脚本**。（不能直接 Load 仓库模板 —— 模板 `content.js` 里 `__AF_PORT__`/`__AF_PROFILE_ID__` 是占位符、未烤不连桥；漏烤直接去 Load 模板是最常见的失败。）
   - **全新 profile 首启弹窗**：会弹「登录 Chrome」「设为默认」两个原生弹窗 → `vision_tap("不登录")`、`vision_tap("跳过")` 跳过。（**若本 server 已部署 human_browser 的首启抑制启动 flag**〔随 AgentHub #211 配套交付，起专用 profile 时注入 `--no-first-run` 等〕，这两个弹窗不出现、可直接往下。）
   - 手动/特殊场景仍可：跑安装脚本（mac `install-human-dom-extension.sh "<PROFILE>"` / win `.ps1`）或 `prepare_extension(out_dir, bridge_port, profile_id)` 自己烤；**不传 PROFILE = 默认日常 Chrome**（profile_id=default、`human_dom_*` 也不传 profile）。
1. **开扩展页**：点地址栏 → **`paste_text("chrome://extensions")`** → `press_key("enter")`。
   - ★ **务必用 `paste_text` 不要 `type_text`**：中文输入法会把 `//` 打成 `、`（实测踩过），`paste_text` 走剪贴板绕开。
   - ★ **别用 `human_browser_open(url="chrome://extensions")` 开扩展页**：实测它只会**新开一个标签页、不导航**过去；要在已起的那个窗口里走地址栏 `paste_text`。
2. **开开发者模式**：`tap` 右上角「开发者模式」开关（OFF→ON），随后左上出现「加载未打包的扩展程序」按钮 → `tap` 它。
3. **原生文件框**（"选择扩展程序目录"）：点「文件夹」输入框 → `paste_text("<第 0 步返回的 human_dom_ext 副本目录绝对路径>")` → `tap`「选择文件夹」。
   - **选的是烤好的副本目录** `~/.fleet/human-dom-ext/<profile_id>/`（win 例：`C:\Users\<u>\.fleet\human-dom-ext\<profile_id>`），**不是**仓库模板目录 `platforms/common/capabilities/human_dom/extension`（模板有占位符、未烤不能用）。
   - 装好后列表出现「agent-fleet human_dom locator」即成功；**持久**，跨 Chrome 重启仍在（比 --load-extension 强在这）。
4. **导航到目标网页**：扩展页（chrome://extensions）本身不连桥——先用地址栏 `paste_text` 导航到真正要操作的网页（如发布页）再继续。
5. **放行本地网络访问（PNA）**：在目标网页上，human_dom content script 连本机桥（`127.0.0.1:<桥端口>`，桥端口由 server 启动时确定、烤进副本里）会触发 Chrome「<网站> 想要访问此设备上的其他应用和服务 [允许][屏蔽]」提示（Private Network Access，新版 Chrome 强制）→ **`vision_tap("允许")`**（每个新 profile/origin 一次性；之后持久）。放行后**重载页面**（win `press_key("f5")` / mac `press_key("cmd+r")`）让 content script 重连，桥即 Established。
6. 之后 `human_dom_locate/tap/fill` 正常用，**记得每次都传 `profile="<同一个 PROFILE 串>"`**（不传=操作 default）。可先 `human_dom_status()` 确认该 profile `installed:true / connected:true`。

**注意事项：**
- **只读扩展 + 「开发者模式扩展」横幅**：本地可见、网页探测不到（不注入 CDP/webdriver，stealth 不破）。
- **多 profile 各装一次、各传各的 profile**：每个要用 human_dom 的 profile 都重跑一遍上面流程（传它自己的 PROFILE），各生成各的副本目录；之后 `human_dom_locate(profile=X)` / `(profile=Y)` 各传各的，桥按 profile 路由互不串线。
- **别移动 `~/.fleet/human-dom-ext/<id>/` 目录**：Load-unpacked 扩展的 ID 由目录路径决定，移动后 Chrome 里该扩展会**消失**、需重新 Load-unpacked。重装扩展（换路径）也要重做一次 PNA 放行。
- **全新 profile 首启可能落在新标签页而非 url**：已有 Chrome 在跑时带 url 启动新 user-data-dir 可能被单例把 url 转发给既有实例 + 走首启 promo → 别假设首启就到目标页；起好后用地址栏（`paste_text` + enter）导航。
- **仍需 host 级 marker**：上面装扩展只解决第②层；若 `list_capabilities` 显示 human_dom unavailable（缺第①层 marker），先补 marker 并重连 server（脚本会自动写 marker；手动建见下），工具才存在。
- **默认日常 profile**：直接跑安装脚本不带 PROFILE 参数即可（profile_id=default），`human_dom_*` 也不传 profile。

**手动补 host 级 marker（脚本之外的兜底）：** 一般跑安装脚本会自动写 marker；若要手动建 —— win-device 的 `run_shell` **跑 PowerShell**（不是 cmd）——
```
run_shell:  New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.fleet" | Out-Null; New-Item -ItemType File -Force -Path "$env:USERPROFILE\.fleet\human-dom-ready" | Out-Null
```
mac 则 `run_shell: mkdir -p ~/.fleet && touch ~/.fleet/human-dom-ready`。建好后**重启对应 server** → human_dom 工具注册。

## 工作流

### 1. 打开页面（必须等 load，再调 locate）

```
human_browser_open(url, profile="<PROFILE>")
```

等待页面完成加载后再调 `human_dom_locate`。**不要在 `human_browser_open` 返回后立即 locate**：content script 的注入有时序，页面还在加载时 locate 会报"桥无该 profile 的 tab"，短等后错误自愈——但若 locate 马上失败，等几秒重试即可。**`human_browser_open` 与后续 `human_dom_*` 传同一个 `profile` 串**（不传=默认日常 Chrome）。

### 2. 定位元素

```
human_dom_locate(query, profile="<PROFILE>")
```

- `profile`：**操作哪个 profile 就传哪个**（与 `human_browser_open(profile=...)` / 装扩展时的 PROFILE 同一串）；桥按 profile 路由到该 profile 的 tab。**不传 = 默认日常 Chrome**（profile_id="default"）。三处同串是铁律（见 per-profile 节）。
- `query`：自由文本，按以下顺序匹配：可见文字、`aria-label`、`placeholder`、`title`、`name` 属性。
- `css`（独立参数，如 `human_dom_locate("正文", css="[contenteditable]")`）：精确 CSS selector，绕过文字匹配。**富文本 / contenteditable 编辑器**（小红书正文、各类所见即所得编辑器）的 placeholder 常是 CSS 伪元素、按文字 locate 不到 → 直接用 `css="[contenteditable]"` 之类定位；再不行落 `vision_locate`。
- 返回候选列表，每项含 `{text, role, center:[x,y], box:[left,top,width,height], visible, clickable}`（`center` / `box` 都是列表，无 `score` 字段）。
- **坐标空间**：屏幕逻辑点（与 `take_screenshot` 像素空间一致），可直接传给 `tap`。

### 3. 操作

```
human_dom_tap(query, nth=0, css="", profile="<PROFILE>")   # 定位 + OS 级点击，一步完成
human_dom_fill(query, text, css="", profile="<PROFILE>")   # 定位 + 聚焦 + 覆盖式填充
```

`tap` / `fill` 的 `profile` 同 `locate`：操作哪个 profile 就传哪个，不传=默认日常 Chrome。

`human_dom_fill` 是**覆盖式**填充，内部：定位 → `tap` 聚焦 → 全选（mac `Cmd+A` / win `Ctrl+A`）→ 剪贴板粘贴（**支持中文**，全选+粘贴的逻辑已内置在 fill 里，覆盖原有内容）。

### 4. OCR 兜底

若 `human_dom_locate` 返回 `suggest: "vision_locate"`（元素在 canvas、shadow DOM 深层、动态遮罩等位置），改用：

```
vision_locate(query)           # OCR 返回屏幕坐标候选
tap(x, y)                      # OS 级点击
```

### 5. 查每个 profile 的安装/连接状态

```
human_dom_status()
```

无参，返回 `{"profiles": [{profile_id, installed, bridge_port, connected}, ...]}`——只列归本 server 桥端口的 profile。`installed` = 该 profile 已在 `~/.fleet/human-dom-ext/` 下生成副本；`connected` = 该 profile 的 content script 已连上桥。排错先看这里：装了没（installed）、连上没（connected），判断缺第②层还是页面没放行 PNA / 没重载。

## 边界与注意事项

- **只读扩展**：content script 仅遍历 DOM 拿坐标，不点击、不修改 DOM、不注入合成事件。动作全部由 OS 级工具完成（`tap` / `type_text` / `press_key`）。
- **扩展是 per-profile 副本，须先为你浏览的 profile 生成副本再装进它**（两层启用模型见上文）：跑 `install-human-dom-extension.sh "<PROFILE>"`(mac)/`.ps1`(win) 烤好副本到 `~/.fleet/human-dom-ext/<id>/`，再 **chrome://extensions 持久 Load-unpacked 那个副本目录**（开发者模式→加载未打包→选副本目录；见上节自助流程，视觉 agent 可自助）。`--load-extension` 命令行加载在 Chrome 137+ 已禁用。模板目录 `platforms/common/capabilities/human_dom/extension/` 有占位符、**不能直接 Load**。`human_dom_status()` 查每个 profile 装没装 / 连没连。**别移动副本目录**（移动后扩展从 Chrome 消失需重装）。
- **桥端口在 server 启动时确定并持久化**（写 `~/.fleet/dom-bridge-<mcp_port>.port`，扩展副本烤的就是这个值）：默认回退 `mcp_port+13`（win :8766→桥 8779、mac :8767→桥 8780），可用 `--dom-bridge-port` 覆盖。content script 通过 WebSocket 连本机 device server 的独立 loopback 桥，只绑 `127.0.0.1`、不走网络。**一台机多 server 端口隔离**（如 win-device :8766→桥 8779、openclaw :8767→桥 8780 互不撞）。
- **真实身份**：human_dom 使用的是主机的日常 Chrome profile（真实 cookies / 登录态 / 扩展），操作即等同于本人操作——只在授权场景下使用。
- **无障碍树不含页面内容**：与 human_browser 一致，UIA/AX tree 只能看到 Chrome 的浏览器 chrome（地址栏、标签），不含页面元素。`find_elements` / `tap_element` 在此无效——页面内容靠 human_dom 或 vision_locate。
- **mac + win 双端已接入**（pc-device）。两端任何 profile 都先生成副本再 chrome://extensions 持久 Load-unpacked（见 per-profile 节自助流程，视觉 agent 可自助）；安装脚本 mac `.sh` / win `.ps1` 各一份。
- **win 坐标缩放 caveat**：win server 是 DPI-unaware（按逻辑像素工作），坐标公式在 **100% 缩放**真机验过准；**非 100%（125%/150%）缩放未验证**，可能整体偏移——遇偏移落 `vision_locate` 兜底。mac（Retina）公式已真机标定 `top_chrome_px = outerH − innerH`、不乘 dpr。

## 与 human_browser 的对比

| | human_browser | human_dom |
|---|---|---|
| 定位方式 | screenshot + 目测坐标 | DOM 文字/aria/placeholder 精确匹配 |
| 输入方式 | OS 级（tap/type_text） | OS 级（tap/type_text）|
| automation traces | 零 | 零（扩展只读，不注入 CDP/webdriver） |
| profile | 真实 | 真实 |
| 适用 | 截图里看得清的元素 | 需要语义匹配 / 坐标精度要求高 |
| DOM 不可达时 | 手动截图猜坐标 | 自动 suggest vision_locate (OCR) |
