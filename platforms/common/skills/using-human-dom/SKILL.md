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
| ① host 级 provisioning | 标记文件 `~/.fleet/human-dom-ready` 存在（server **启动时静态判定**，决定 human_dom 工具**注册不注册**） | `list_capabilities` 里 human_dom = `unavailable`，**根本没有 human_dom_* 工具** | mac 跑 `install-human-dom-extension.sh`（**引导用户在默认 profile 手动 Load unpacked + 自动写 marker**，脚本本身不自动装扩展）；win 暂无脚本 → `run_shell` 建 marker（见 per-profile 节）。**写完 marker 必须重连 / 重启 server** 才注册（框架不动态增删工具） |
| ② profile 级 扩展 | human_dom 扩展**已加载进你当前浏览的那个 Chrome profile**（扩展是 per-profile 的） | 工具在，但 `human_dom_locate` 对该 profile 的页面拿不到元素 | 任何 profile（默认 / 专用）都用 **chrome://extensions 持久 Load-unpacked**（见下节自助流程；`--load-extension` 在 Chrome137+ 已禁用） |

先 `list_capabilities`：
- **human_dom = unavailable**（无 marker）：缺第①层。补 marker + 重连 server 即注册（mac 跑 install 脚本，win 用下面 PowerShell 建 marker）。补好前先用 `vision_locate` 顶着。
- **human_dom = enabled 但 locate 拿不到**：缺第②层——你浏览的 profile 没装扩展，按下节自助 Load-unpacked 装进该 profile。

## 为一个【新 profile】启用 human_dom（per-profile 启用）

**关键事实：human_dom 扩展是 per-Chrome-profile 的。** 真账号 operator 常固定一个**专用持久 profile**（`human_browser_open(profile="~/.fleet/<account-id>")`，见 using-human-browser）；这个新建 profile **默认没装 human_dom 扩展**——即使 host 级 marker 在、human_dom 工具可用，对它的页面也定位不到。

> ⚠️ **`--load-extension` 命令行加载在 Chrome 137+ 已被 Google 禁用**（防恶意软件；本机实测 Chrome 148 完全失效，旧逃生开关 `--disable-features=DisableLoadExtensionCommandLineSwitch` 也失效）。所以**唯一可靠路径是 chrome://extensions 持久 Load-unpacked**——一次性、跨 run 持久、扛得住封禁。下面这套**视觉 agent 可全程自助**（test-win11 真机端到端验证过）。

### 自助 Load-unpacked 装扩展（视觉 agent 流程，已真机验证）

为专用 profile `~/.fleet/<account-id>` 装 human_dom 扩展，一次性：

1. **起该 profile**：`human_browser_open(profile="~/.fleet/<account-id>")`。全新 profile 会弹首启 promo（登录 Chrome / 设为默认）→ `vision_tap("不登录")`、`vision_tap("跳过")` 跳过。
2. **开扩展页**：点地址栏 → **`paste_text("chrome://extensions")`** → `press_key("enter")`。
   - ★ **务必用 `paste_text` 不要 `type_text`**：中文输入法会把 `//` 打成 `、`（实测踩过），`paste_text` 走剪贴板绕开。
3. **开开发者模式**：`tap` 右上角「开发者模式」开关（OFF→ON），随后左上出现「加载未打包的扩展程序」按钮 → `tap` 它。
4. **原生文件框**（"选择扩展程序目录"）：点「文件夹」输入框 → `paste_text("<扩展目录绝对路径>")` → `tap`「选择文件夹」。
   - 扩展目录：仓库内 `platforms/common/capabilities/human_dom/extension`（win 例：`C:\Users\<u>\agent-fleet\platforms\common\capabilities\human_dom\extension`）。
   - 装好后列表出现「agent-fleet human_dom locator」即成功；**持久**，跨 Chrome 重启仍在（比 --load-extension 强在这）。
5. **导航到目标网页**：扩展页（chrome://extensions）本身不连桥——先用地址栏 `paste_text` 导航到真正要操作的网页（如发布页）再继续。
6. **放行本地网络访问（PNA）**：在目标网页上，human_dom content script 连 `127.0.0.1:8779` 会触发 Chrome「<网站> 想要访问此设备上的其他应用和服务 [允许][屏蔽]」提示（Private Network Access，新版 Chrome 强制）→ **`vision_tap("允许")`**（每个新 profile/origin 一次性；之后持久）。放行后**重载页面**（win `press_key("f5")` / mac `press_key("cmd+r")`）让 content script 重连，桥即 Established。
7. 之后 `human_dom_locate/tap/fill` 正常用。

**注意事项：**
- **只读扩展 + 「开发者模式扩展」横幅**：本地可见、网页探测不到（不注入 CDP/webdriver，stealth 不破）。
- **全新 profile 首启可能落在新标签页而非 url**：已有 Chrome 在跑时带 url 启动新 user-data-dir 可能被单例把 url 转发给既有实例 + 走首启 promo → 别假设首启就到目标页；起好后用地址栏（`paste_text` + enter）导航。
- **仍需 host 级 marker**：上面装扩展只解决第②层；若 `list_capabilities` 显示 human_dom unavailable（缺第①层 marker），先补 marker 并重连 server（见下），工具才存在。
- **默认日常 profile**：mac 用 `install-human-dom-extension.sh` 引导一次 Load-unpacked；其它同上手动 Load-unpacked。

**win 上补 host 级 marker（暂无安装脚本）：** win-device 的 `run_shell` **跑 PowerShell**（不是 cmd），用 PowerShell 语法建空标记文件再重连 server——
```
run_shell:  New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.fleet" | Out-Null; New-Item -ItemType File -Force -Path "$env:USERPROFILE\.fleet\human-dom-ready" | Out-Null
```
（`~/.fleet` 在 win 即 `%USERPROFILE%\.fleet`；marker 在 → 重启 win-device server → human_dom 工具注册）。

## 工作流

### 1. 打开页面（必须等 load，再调 locate）

```
human_browser_open(url)
```

等待页面完成加载后再调 `human_dom_locate`。**不要在 `human_browser_open` 返回后立即 locate**：content script 的注入有时序，页面还在加载时 locate 会报"桥无 active tab"，短等后错误自愈——但若 locate 马上失败，等几秒重试即可。

### 2. 定位元素

```
human_dom_locate(query)
```

- `query`：自由文本，按以下顺序匹配：可见文字、`aria-label`、`placeholder`、`title`、`name` 属性。
- `css`（独立参数，如 `human_dom_locate("正文", css="[contenteditable]")`）：精确 CSS selector，绕过文字匹配。**富文本 / contenteditable 编辑器**（小红书正文、各类所见即所得编辑器）的 placeholder 常是 CSS 伪元素、按文字 locate 不到 → 直接用 `css="[contenteditable]"` 之类定位；再不行落 `vision_locate`。
- 返回候选列表，每项含 `{text, role, center:[x,y], box:[left,top,width,height], visible, clickable}`（`center` / `box` 都是列表，无 `score` 字段）。
- **坐标空间**：屏幕逻辑点（与 `take_screenshot` 像素空间一致），可直接传给 `tap`。

### 3. 操作

```
human_dom_tap(query, nth=0, css="")   # 定位 + OS 级点击，一步完成
human_dom_fill(query, text, css="")   # 定位 + 聚焦 + 覆盖式填充
```

`human_dom_fill` 是**覆盖式**填充，内部：定位 → `tap` 聚焦 → 全选（mac `Cmd+A` / win `Ctrl+A`）→ 剪贴板粘贴（**支持中文**，全选+粘贴的逻辑已内置在 fill 里，覆盖原有内容）。

### 4. OCR 兜底

若 `human_dom_locate` 返回 `suggest: "vision_locate"`（元素在 canvas、shadow DOM 深层、动态遮罩等位置），改用：

```
vision_locate(query)           # OCR 返回屏幕坐标候选
tap(x, y)                      # OS 级点击
```

## 边界与注意事项

- **只读扩展**：content script 仅遍历 DOM 拿坐标，不点击、不修改 DOM、不注入合成事件。动作全部由 OS 级工具完成（`tap` / `type_text` / `press_key`）。
- **扩展是 per-profile 的，须先装进你浏览的 profile**（两层启用模型见上文）：任何 profile 都用 **chrome://extensions 持久 Load-unpacked**（开发者模式→加载未打包→选扩展目录；见上节自助流程，视觉 agent 可自助）。`--load-extension` 命令行加载在 Chrome 137+ 已禁用。扩展目录在 `platforms/common/capabilities/human_dom/extension/`。mac 默认 profile 可用 `install-human-dom-extension.sh` 引导。
- **桥监听在 127.0.0.1:8779**：content script 通过 WebSocket 连本机 device server（mac/win 同）的独立 loopback 桥，只绑 127.0.0.1、不走网络。
- **真实身份**：human_dom 使用的是主机的日常 Chrome profile（真实 cookies / 登录态 / 扩展），操作即等同于本人操作——只在授权场景下使用。
- **无障碍树不含页面内容**：与 human_browser 一致，UIA/AX tree 只能看到 Chrome 的浏览器 chrome（地址栏、标签），不含页面元素。`find_elements` / `tap_element` 在此无效——页面内容靠 human_dom 或 vision_locate。
- **mac + win 双端已接入**（pc-device）。两端任何 profile 都用 chrome://extensions 持久 Load-unpacked 装扩展（见 per-profile 节自助流程，视觉 agent 可自助）；mac 默认 profile 可用 install 脚本。
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
