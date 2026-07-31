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
| ① host 级 provisioning | 标记文件 `~/.fleet/human-dom-ready` 存在（server **启动时静态判定**，决定 human_dom 工具**注册不注册**） | `list_capabilities` 里 human_dom = `unavailable`，**根本没有 human_dom_* 工具** | 建 marker：`run_shell` 建 `~/.fleet/human-dom-ready`（见 per-profile 节末尾）或跑安装脚本自动写。**写完 marker 必须重连 / 重启 server** 才注册（框架不动态增删工具）。这是 host 级一次性 provisioning、非操作员运行期步骤 |
| ② profile 级 扩展 | human_dom 扩展**已加载进你当前浏览的那个 Chrome profile**（扩展是 per-profile 副本，每份烤入了该 profile 的桥端口 + profile_id） | 工具在，但 `human_dom_locate` 对该 profile 的页面拿不到元素，或路由到别的 profile | **`human_browser_open(profile=X)` 一步自动装**（auto-bake 副本 + server 侧 CDP `Extensions.loadUnpacked` 装进该 profile + 关 LNA 检查直连桥）——操作员零手动，见下节 |

先 `list_capabilities`：
- **human_dom = unavailable**（无 marker）：缺第①层。补 marker + 重连 server 即注册（mac 跑 `install-human-dom-extension.sh` / win 跑 `install-human-dom-extension.ps1`，脚本会自动写 marker；或手动建 marker，见下）。补好前先用 `vision_locate` 顶着。
- **human_dom = enabled 但 locate 拿不到 / 路由错**：缺第②层——你浏览的 profile 还没经 `human_browser_open(profile=X)` 装扩展（或没导航到目标页）。`human_dom_status()` 可一眼看出每个 profile 装没装（installed）/ 连没连（connected）；重开 `human_browser_open(profile=X)` 即幂等自动装+连。

## 为一个【新 profile】启用 human_dom（per-profile 启用）

**关键事实：human_dom 扩展是 per-Chrome-profile 副本，桥按 profile 路由。** 真账号 operator 常固定一个**专用持久 profile**（`human_browser_open(profile="~/.fleet/<account-id>")`，见 using-human-browser）；这个新建 profile **默认没装 human_dom 扩展**——即使 host 级 marker 在、human_dom 工具可用，对它的页面也定位不到。

> ★ **三处同一 profile 串铁律（最重要）：** `human_browser_open(profile=X)`、装扩展时传的 `PROFILE`、`human_dom_locate/tap/fill(profile=X)` —— 这**三处必须用同一个 profile 串**。桥**按 profile 路由**（不再全局猜 active tab）：调用方必须传「操作哪个 profile」，桥才把请求路由到该 profile 那张 tab。**不传 `profile` = 操作默认日常 Chrome**（`profile_id="default"`）；操作专用 profile 必须**显式传**，否则路由到 default 上找不到 / 找错。
>
> 每个 profile 各自装一份扩展副本（副本里烤入了该 profile 的桥端口 + profile_id）。多 profile 各传各的 `profile`，桥按 profile 隔离，**不会串线**（不再依赖「最小化别的窗口」那类规避 active-tab 串扰的 hack）。

> ⚠️ **`--load-extension` 命令行加载在 Chrome 137+ 已被 Google 禁用**（防恶意软件；实测旧逃生开关 `--disable-features=DisableLoadExtensionCommandLineSwitch` 也失效）。**v0.8.6 起改由 server 侧 CDP `Extensions.loadUnpacked` 确定性装**（真机端到端验证过）——操作员**不再需要**开 chrome://extensions 手动 Load-unpacked，`human_browser_open(profile=..)` 一步自动装好（见下节）。

### 起 profile 即自动装（v0.8.6+ 确定性 CDP 安装，操作员零手动）

**为专用 profile 装 human_dom：一步到位，server 侧自动完成，操作员什么都不用做。** 全程认准同一个 PROFILE 串（= 后面 `human_dom_locate(profile=...)` 要传的那个）：

```
human_browser_open(url="<目标页>", profile="~/.fleet/<account-id>")
```

server 起这个专用 profile 时自动：

1. **auto-bake** 该 profile 的扩展副本（算 profile_id + 读本 server 桥端口 → `~/.fleet/human-dom-ext/<profile_id>/`，烤入端口 + profile_id）；
2. 起 Chrome：加临时 debug 端口 + `--disable-features=…,LocalNetworkAccessChecks`（关本地网络访问检查）+ 首启抑制 flag；
3. 经 **CDP `Extensions.loadUnpacked`** 把副本装进该 profile —— **零 GUI / 零视觉 / 零 DPI**（Chrome 137+ 禁了 `--load-extension`，这是官方替代）；
4. 导航到目标 url —— content script 在【新导航】时注入、**直连本机桥、无「本地网络访问」弹窗**、即 connected。

返回里 **`human_dom.ok=true`（含 `id`/`navigated`）即已装好**。之后直接 `human_dom_locate/tap/fill(profile="<同一个 PROFILE 串>")`；可先 `human_dom_status()` 确认该 profile `installed:true / connected:true`。

> ★ **这些老步骤 v0.8.6 起已被 server 接管、操作员一律别做了**：开 `chrome://extensions`、点「开发者模式」、Load-unpacked 选目录、点「本地网络访问-允许」、F5 重载。`human_browser_open(profile=..)` 一步全包。若 `human_dom.ok=false`，多半是缺 host 级 marker（见文末）；仍打开了目标页，可截图 + tap 兜底、并重试 `human_browser_open`。

**注意事项：**
- **只读扩展、网页探测不到**：不注入 CDP/webdriver；临时 debug 端口仅 127.0.0.1、网页带 Origin 被 Chrome 403 够不着；关 LNA 检查是 feature flag 非自动化标志（`navigator.webdriver` 仍 false）——stealth/moat 不破。
- **多 profile 各传各的 profile**：每个 profile 首次 `human_browser_open(profile=X)` 各自装一份副本；`human_dom_locate(profile=X)/(profile=Y)` 各传各的，桥按 profile 路由互不串线。
- **仍需 host 级 marker（一次性、非操作员步骤）**：`list_capabilities` 显 human_dom unavailable（缺第①层 marker）→ 补 `~/.fleet/human-dom-ready` marker 并重启 server，工具才注册（见下）。
- **默认日常 profile**：`human_browser_open` 不传 profile = 默认日常 Chrome（profile_id=default），`human_dom_*` 也不传 profile。

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

> **动手前先查前台（查→不对才拉）**：`human_dom_tap`/`human_dom_fill` 底层是**绝对屏幕坐标的 OS 级 tap + 全选粘贴**，打在**当时的前台窗口**——前台不是目标浏览器就会误点、或把内容全选粘贴进别的应用（数据错发，比抢焦点更糟）。按【组】非逐帧：一组无中断连续动作组首查一次；任何等待/加载/跳页/重试后必重查（用户可能在你等的那几秒切走应用）：
> - `human_dom_focused(profile="<PROFILE>")` → `focused=true` 直接操作；
> - `focused=false` → `human_browser_open(profile="<PROFILE>", activate=True)` 拉回 → 复查 → 操作；
> - `focused=None` / 工具不存在 / 调用报错（旧 server 未升级）→ 回落 `take_screenshot` 目测前台，别卡住别重试。
> `human_dom_focused` 省略 profile 时与 locate/tap/fill 走同一 `resolve_profile_id`（继承活跃 operator）。

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

返回 `{installed, connected, profiles:[{profile_id, installed, bridge_port, connected}, ...], hint}`。`installed` = **纯盘扫描**：该 profile 已装入（`~/.fleet/human-dom-ext/<id>/loaded.json` 标记，装成功即写；**不按桥端口过滤**，换 server/端口后不丢）；`connected` = 该 profile 的 content script 当前连在【本 server 的桥】。`hint` 讲清语义。排错先看这里：**installed=true / connected=false ≠ 未安装**——多半是没开页/没导航到目标页，重开 `human_browser_open(profile=..)`（幂等自动重装+重连）或导航到目标页即可，**别重复装**。

## 边界与注意事项

- **只读扩展**：content script 仅遍历 DOM 拿坐标，不点击、不修改 DOM、不注入合成事件。动作全部由 OS 级工具完成（`tap` / `type_text` / `press_key`）。
- **扩展是 per-profile 副本，由 `human_browser_open(profile=X)` 自动装**（两层启用模型见上文）：起专用 profile 时 server 自动 auto-bake 副本到 `~/.fleet/human-dom-ext/<id>/` + 经 CDP `Extensions.loadUnpacked` 装进该 profile + 关 LNA 检查直连桥；操作员零手动（`--load-extension` 在 Chrome 137+ 已禁用，CDP 是替代）。DEV 手动烤仍可 `prepare_extension(out_dir, bridge_port, profile_id)`。`human_dom_status()` 查每个 profile 装没装（installed，纯盘扫描）/ 连没连（connected）。
- **桥端口在 server 启动时确定并持久化**（写 `~/.fleet/dom-bridge-<mcp_port>.port`，扩展副本烤的就是这个值）：默认回退 `mcp_port+13`（win :8766→桥 8779、mac :8767→桥 8780），可用 `--dom-bridge-port` 覆盖。content script 通过 WebSocket 连本机 device server 的独立 loopback 桥，只绑 `127.0.0.1`、不走网络。**一台机多 server 端口隔离**（如 win-device :8766→桥 8779、openclaw :8767→桥 8780 互不撞）。
- **真实身份**：human_dom 使用的是主机的日常 Chrome profile（真实 cookies / 登录态 / 扩展），操作即等同于本人操作——只在授权场景下使用。
- **无障碍树不含页面内容**：与 human_browser 一致，UIA/AX tree 只能看到 Chrome 的浏览器 chrome（地址栏、标签），不含页面元素。`find_elements` / `tap_element` 在此无效——页面内容靠 human_dom 或 vision_locate。
- **mac + win 双端已接入**（pc-device）。两端 `human_browser_open(profile=X)` 都一步自动装（server 侧 CDP loadUnpacked，见 per-profile 节）。
- **win 坐标缩放**：win server v0.8.6 起进程设为 per-monitor DPI aware（take_screenshot 与 tap/get_screen_size 统一到物理像素、坐标自洽）；100% 缩放真机验过准，缩放机器坐标一致性建议再验一次——遇偏移落 `vision_locate` 兜底。mac（Retina）公式已真机标定 `top_chrome_px = outerH − innerH`、不乘 dpr。

## 与 human_browser 的对比

| | human_browser | human_dom |
|---|---|---|
| 定位方式 | screenshot + 目测坐标 | DOM 文字/aria/placeholder 精确匹配 |
| 输入方式 | OS 级（tap/type_text） | OS 级（tap/type_text）|
| automation traces | 零 | 零（扩展只读，不注入 CDP/webdriver） |
| profile | 真实 | 真实 |
| 适用 | 截图里看得清的元素 | 需要语义匹配 / 坐标精度要求高 |
| DOM 不可达时 | 手动截图猜坐标 | 自动 suggest vision_locate (OCR) |
