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
- 可附加 CSS selector 缩小范围：`"登录 css=button.submit"`。
- 返回候选列表，每项含 `{text, role, center:[x,y], box:{left,top,width,height}, visible, clickable}`（`center` 是 `[x,y]` 列表，无 `score` 字段）。
- **坐标空间**：屏幕逻辑点（与 `take_screenshot` 像素空间一致），可直接传给 `tap`。

### 3. 操作

```
human_dom_tap(query, nth=0, css="")   # 定位 + OS 级点击，一步完成
human_dom_fill(query, text, css="")   # 定位 + 聚焦 + 覆盖式填充
```

`human_dom_fill` 是**覆盖式**填充，内部：定位 → `tap` 聚焦 → Cmd+A 全选 → 剪贴板粘贴（**支持中文**，全选+粘贴的逻辑已内置在 fill 里，覆盖原有内容）。

### 4. OCR 兜底

若 `human_dom_locate` 返回 `suggest: "vision_locate"`（元素在 canvas、shadow DOM 深层、动态遮罩等位置），改用：

```
vision_locate(query)           # OCR 返回屏幕坐标候选
tap(x, y)                      # OS 级点击
```

## 边界与注意事项

- **只读扩展**：content script 仅遍历 DOM 拿坐标，不点击、不修改 DOM、不注入合成事件。动作全部由 OS 级工具完成（`tap` / `type_text` / `press_key`）。
- **需提前安装扩展**（一次性）：在真实 Chrome profile 里以开发者模式加载 `platforms/pc/browser-ext/` 目录，或通过 `setup-pc.sh` 自动安装。安装后对该 profile 永久生效。
- **桥监听在 127.0.0.1**：content script 通过 WebSocket 连 pc-device server（本机），不走网络。
- **真实身份**：human_dom 使用的是主机的日常 Chrome profile（真实 cookies / 登录态 / 扩展），操作即等同于本人操作——只在授权场景下使用。
- **无障碍树不含页面内容**：与 human_browser 一致，UIA/AX tree 只能看到 Chrome 的浏览器 chrome（地址栏、标签），不含页面元素。`find_elements` / `tap_element` 在此无效——页面内容靠 human_dom 或 vision_locate。
- **目前 mac 已接入**；win 及跨平台扩展安装脚本后续跟进。

## 与 human_browser 的对比

| | human_browser | human_dom |
|---|---|---|
| 定位方式 | screenshot + 目测坐标 | DOM 文字/aria/placeholder 精确匹配 |
| 输入方式 | OS 级（tap/type_text） | OS 级（tap/type_text）|
| automation traces | 零 | 零（扩展只读，不注入 CDP/webdriver） |
| profile | 真实 | 真实 |
| 适用 | 截图里看得清的元素 | 需要语义匹配 / 坐标精度要求高 |
| DOM 不可达时 | 手动截图猜坐标 | 自动 suggest vision_locate (OCR) |
