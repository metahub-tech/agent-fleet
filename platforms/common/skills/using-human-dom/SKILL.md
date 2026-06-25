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
| ② profile 级 扩展 | human_dom 扩展**已加载进你当前浏览的那个 Chrome profile**（扩展是 per-profile 的） | 工具在，但 `human_dom_locate` 对该 profile 的页面拿不到元素 | 默认日常 profile：Load unpacked 持久安装；**新建专用 profile：`human_browser_open(profile=X, with_human_dom=True)` 免 GUI 自动加载**（见下节） |

先 `list_capabilities`：
- **human_dom = unavailable**（无 marker）：缺第①层。补 marker + 重连 server 即注册（mac 跑 install 脚本，win 用上面 PowerShell 建 marker）。补好前先用 `vision_locate` 顶着。
  - 唯独**默认日常 profile 的持久安装**才需手动 GUI Load unpacked（且易被输入法 / 文件框卡住，建议让用户做）；**专用 profile 走下节 `with_human_dom=True` 的 `--load-extension` 路完全免 GUI、agent 可自助**。
- **human_dom = enabled 但 locate 拿不到**：缺第②层——你浏览的 profile 没装扩展。若是专用 profile，用下节 `with_human_dom=True` 重开。

## 为一个【新 profile】启用 human_dom（per-profile 启用）

**关键事实：human_dom 扩展是 per-Chrome-profile 的。** 真账号 operator 常固定一个**专用持久 profile**（`human_browser_open(profile="~/.fleet/<account-id>")`，见 using-human-browser）；这个新建 profile **默认没装 human_dom 扩展**——即使 host 级 marker 在、human_dom 工具可用，对它的页面也定位不到。

给这个新 profile 开 human_dom，**一次到位、免 GUI**：

```
human_browser_open(url, profile="~/.fleet/<account-id>", with_human_dom=True)
```

- `with_human_dom=True` 在启动该专用 profile 的 Chrome 时附加 `--load-extension=<human_dom 扩展目录>`，把扩展直接灌进这个 profile —— **无需手动 Load unpacked**，agent 可自助为新 profile 启用 DOM 精度。
- 返回里 `human_dom_ext: true` 表示扩展已随启动加载。

**注意事项（写进流程别踩）：**
- **只在【全新启动】生效**：`--load-extension` 只在 Chrome 进程冷启时加载。若该 profile 的 Chrome 已在跑，要先**真正关掉它的进程**再带 `with_human_dom=True` 重开。**注意 `browser_quit` 关不掉 human_browser 起的 Chrome**（human_browser 走裸进程启动、不走租约，`browser_quit` 只对 agent_browser 的进程有效）——改用进程级关闭：win `run_shell` 跑 `Stop-Process -Name chrome -Force`（或确保该 `user-data-dir` 无存活 chrome 进程）、mac `pkill -x "Google Chrome"` 或退出 Chrome 窗口。
- **会有「开发者模式扩展」横幅**：本地可见、网页探测不到（扩展只读、不注入 CDP/webdriver，stealth 不破）。
- **仅对专用 `profile=` 生效**：`profile` 留空（默认日常 Chrome）走 `open -a` / 直起，不支持 `--load-extension` → 默认 profile 请用持久 Load unpacked（install 脚本）装一次，永久生效。
- **仍需 host 级 marker**：`with_human_dom=True` 只解决第②层（profile 内扩展），**不创建 marker**。若 `list_capabilities` 显示 human_dom unavailable，先补第①层 marker 并重连 server，工具才存在。

**win 上补 host 级 marker（暂无安装脚本）：** win-device 的 `run_shell` **跑 PowerShell**（不是 cmd），用 PowerShell 语法建空标记文件再重连 server——
```
run_shell:  New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.fleet" | Out-Null; New-Item -ItemType File -Force -Path "$env:USERPROFILE\.fleet\human-dom-ready" | Out-Null
```
（`~/.fleet` 在 win 即 `%USERPROFILE%\.fleet`；marker 在 → 重启 win-device server → human_dom 工具注册）。专用 profile 的扩展仍用 `with_human_dom=True` 免 GUI 加载，**无需在 win 上手点 chrome://extensions**。

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
- **扩展是 per-profile 的，须先装进你浏览的 profile**（两层启用模型见上文）：默认日常 profile → install 脚本 Load unpacked 持久安装一次（写 `~/.fleet/human-dom-ready` 标记，重连后 enabled）；**新建专用 profile → `human_browser_open(profile=X, with_human_dom=True)` 免 GUI `--load-extension`**。扩展目录在 `platforms/common/capabilities/human_dom/extension/`。
- **桥监听在 127.0.0.1:8779**：content script 通过 WebSocket 连本机 mac-device server 的独立 loopback 桥，只绑 127.0.0.1、不走网络。
- **真实身份**：human_dom 使用的是主机的日常 Chrome profile（真实 cookies / 登录态 / 扩展），操作即等同于本人操作——只在授权场景下使用。
- **无障碍树不含页面内容**：与 human_browser 一致，UIA/AX tree 只能看到 Chrome 的浏览器 chrome（地址栏、标签），不含页面元素。`find_elements` / `tap_element` 在此无效——页面内容靠 human_dom 或 vision_locate。
- **mac + win 双端已接入**（pc-device）。两端的专用 `profile=` 都推荐用 `with_human_dom=True` 免 GUI 加载扩展（见 per-profile 节）；默认日常 profile 用 install 脚本（mac 有，win 暂无）。
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
