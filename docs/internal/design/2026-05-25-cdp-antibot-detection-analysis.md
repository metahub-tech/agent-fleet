# agent_browser 的 CDP 反爬检测深度分析

> 实测日期：2026-05-25　测试主机：test-win11（win-device，物理机，Chrome 148 + Playwright MCP 0.0.75）
> 方法：用 agent_browser 实访 `https://bot.sannysoft.com/`，配合 `browser_evaluate` JS 探针与宿主进程命令行取证；与 human_browser 逐层对比。
> 目的：摸清 agent_browser（Playwright over CDP + 真实 Chrome，headed）到底在哪一层暴露自动化痕迹，据此校准 agent_browser / human_browser 的路由边界。**仅用于理解自有工具的检测特征，不用于规避检测爬取第三方站点。**

---

## 0. 一句话结论

agent_browser 的 **JS 指纹层和经典 CDP 检测层几乎全部通过**（表现得像真实浏览器），真正的痕迹集中在**进程/本地层**（命令行有 `--remote-debugging-pipe` 等标志、隔离 profile）和**行为层**（合成输入轨迹非人类）。前者只有宿主本地/EDR 看得到、网站 JS 看不到；后者才是高级行为反爬（reCAPTCHA v3 / DataDome 类）真正能抓的点。**结论修正了"agent_browser 有明显自动化痕迹"的直觉——它在网站可见的指纹层其实相当干净。**

---

## 1. 痕迹的四个层次

| 层 | 谁能看到 | agent_browser 暴露程度 |
|---|---|---|
| L1 JS 指纹层（navigator/chrome/WebGL/permissions…） | 任意网站 JS | **几乎不暴露**（实测全过） |
| L2 CDP 协议层（Runtime.enable 副作用、控制通道） | 高级/定制检测脚本 | **基本不暴露**（用 pipe + 经典探针失效） |
| L3 进程/本地层（命令行标志、调试通道、profile） | 宿主本机进程 / EDR | **明确暴露**（但网站看不到） |
| L4 行为层（鼠标轨迹、输入时序、交互模式） | 高级行为反爬（服务端建模） | **暴露**（合成输入非人类；human_browser 同样有） |

---

## 2. L1 — JS 指纹层实测（agent_browser）

`browser_evaluate` 在 bot.sannysoft.com 页面上下文采集：

| 检测项 | 实测值 | 是否像真人 | 说明 |
|---|---|---|---|
| `navigator.webdriver` | **false** | ✅ | 未启用 `--enable-automation`，属性存在但值为 false（与真实 Chrome 一致） |
| `userAgent` | `Chrome/148.0.0.0`（无 `HeadlessChrome`） | ✅ | headed 真实 Chrome channel |
| `navigator.platform` | `Win32` | ✅ | |
| `navigator.languages` | `["zh-CN","zh"]` | ✅ | 真实语言 |
| `navigator.plugins.length` | **5** | ✅ | headless 通常为 0，5 说明是 headed 真实 Chrome |
| `mimeTypes.length` | 2 | ✅ | |
| `hardwareConcurrency` / `deviceMemory` | 8 / 16 | ✅ | 真实硬件 |
| `window.chrome` | 存在，keys = `[loadTimes, csi, app]` | ✅ | `chrome.loadTimes()`/`chrome.csi()` 都在（自动化/headless 常缺） |
| `outerWidth/innerWidth` | 945 / 929（有窗口边框差） | ✅ | headless 检测看 outer==0 或 outer==inner，此处正常 |
| WebGL vendor / renderer | `Google Inc. (AMD)` / `ANGLE AMD Radeon Vega 8 …D3D11` | ✅ | 真实 GPU（headless 常为 SwiftShader/Mesa） |
| automation 全局 (`cdc_`/`$cdc`/`__playwright`/`__webdriver`…) | **[] 空** | ✅ | 不像 Selenium chromedriver 注入 `cdc_` 变量 |
| `navigator.permissions` vs `Notification.permission` | prompt / default，**一致** | ✅ | headless 经典"权限不一致"检测通过 |

**L1 小结**：常见 bot 检测项（webdriver、headless、plugins、WebGL、权限一致性、注入全局）agent_browser **全部通过**。根因是它用 `--browser chrome`（真实 Chrome 通道，headed）而非 headless/chromedriver。

---

## 3. L2 — CDP 协议层实测

| 探针 | 原理 | 实测 | 结论 |
|---|---|---|---|
| `console.debug(errWithStackGetter)` | CDP `Runtime.enable` 监听控制台时会序列化参数，触发 `Error.stack` getter → 经典 CDP 在场检测 | `cdpRuntimeStackTriggered = **false**` | **经典 CDP 检测失效**：Playwright 当前版本不触发该副作用 |
| `Function.prototype.toString` 自检 | 检测原型链是否被注入篡改 | `[native code]` 完好 | 无 JS 注入痕迹 |
| `navigator.webdriver` 描述符 | 检测属性是否被伪造（getter/enumerable/configurable） | 与真实 Chrome 形态一致 | 未被 monkey-patch |

**L2 小结**：CDP 控制通道走 **pipe**（见 L3），不开 TCP 端口；经典"CDP 在场"JS 探针对它失效。网站 JS 想确定性判定"此页被 CDP 控制"非常困难——这正是 agent_browser 指纹干净的底层原因。

---

## 4. L3 — 进程/本地层取证（关键痕迹所在）

宿主 `Win32_Process` 取 agent_browser 的 Chrome 主进程命令行（节选关键标志）：

```
--user-data-dir=C:\Users\qjl\.fleet\agent-browser-profile
--remote-debugging-pipe
--no-first-run  --no-default-browser-check
--disable-background-networking
--disable-backgrounding-occluded-windows
--disable-back-forward-cache
```

要点：
- **`--remote-debugging-pipe`（不是 `--remote-debugging-port`）**：CDP 走进程间 pipe（stdio fd），**不暴露 TCP 调试端口**。所以 `netstat`/端口扫描看不到调试端口，其它本地进程也无法通过端口附着——比 chromedriver / `--remote-debugging-port=9222` 隐蔽得多。
- **无 `--enable-automation`**：没有"Chrome 正受自动化软件控制"信息栏，`navigator.webdriver` 保持 false（呼应 L1）。
- **无 `--test-type`**。
- **隔离 profile** `--user-data-dir=…\.fleet\agent-browser-profile`：全新环境，无真实 cookie / 历史 / 登录态 / 扩展。这是 agent_browser 在网站侧唯一的**间接**信号——站点可能因"全新、无登录、无历史指纹"而提高风控分，但这**不是确定性的自动化判定**。
- 一组 `--disable-*` 是 Playwright 标准启动参数，**仅本地命令行可见，网站 JS 完全看不到**。

**L3 小结**：agent_browser 最确定的痕迹在本地进程命令行（`--remote-debugging-pipe` + Playwright 标志）+ 隔离 profile。这些**对 EDR / 本机检测可见，对远端网站不可见**（除隔离 profile 带来的间接信号）。

---

## 5. L4 — 行为层（最难规避，两档共有）

L1–L3 是"静态指纹"；高级反爬（reCAPTCHA v3、DataDome、PerimeterX 等）越来越依赖**行为建模**：

- **鼠标轨迹**：agent_browser 的输入是 CDP `Input.dispatchMouseEvent` 合成——`isTrusted=true`，但轨迹是程序生成（直线/瞬移、无微抖动、无加速度曲线、无空闲漂移）。
- **输入时序**：打字间隔均匀、过快，缺乏人类节奏与误击改正。
- **交互模式**：无悬停徘徊、无误点、滚动是离散跳跃。

**这一层 human_browser 同样存在**：它经 OS 级 `SendInput` 注入（`isTrusted` 比 CDP 合成更底层、更"真"），但轨迹一样是 pyautogui 程序生成的，非人类。**两档要过行为反爬，都需要额外的"拟人化"轨迹/时序，仅靠引擎选择不够。**

---

## 6. agent_browser vs human_browser 分层对比

| 层 | agent_browser（Playwright/CDP + 真实 Chrome headed） | human_browser（OS 级真实输入 + 真人日常 Chrome） |
|---|---|---|
| L1 JS 指纹 | 干净（实测全过） | 干净（同为真实 Chrome） |
| L2 CDP 协议 | 走 pipe、经典探针失效，但**CDP 通道客观存在** | **无 CDP**（OS 输入，连 pipe 都没有） |
| L3 进程/本地 | `--remote-debugging-pipe` + Playwright `--disable-*` + **隔离 profile** | 纯 `chrome.exe <url>`，**真实日常 profile**，零自动化标志（前序实测确认） |
| 身份/环境 | 全新隔离环境，无登录态 | **真实身份**：真 cookie / 历史 / 登录 / 扩展 |
| L4 行为 | 合成输入，轨迹非人类 | 同样程序化轨迹（OS 输入更底层但仍非人类） |
| 控制精度 | 高（DOM snapshot+ref，精准、快） | 低（截图+坐标，慢、靠视觉） |

---

## 7. 路由结论（校准后）

- **碰真实账号 / 身份 / 登录态 → human_browser**：不是因为 agent_browser "JS 指纹脏"（它不脏），而是 ① 真实 profile（登录态/cookie/历史）只有 human_browser 有；② 无 CDP 通道、无本地调试痕迹，本机/EDR 角度更干净；③ OS 级 `isTrusted` 输入最底层。
- **测试 / 抓公开数据 / 浏览学习 → agent_browser**：JS 指纹足够干净可过绝大多数常规 bot 检测，且 DOM snapshot+ref 精准高效；隔离 profile 不污染真实身份。
- **要过高级行为反爬（reCAPTCHA v3 / DataDome）**：两档都需补"拟人化轨迹 + 时序"，单选引擎不够——这是 L4 的共性短板，是后续若有此需求的独立课题。
- **面对本机 EDR / 端侧自动化检测**：human_browser 明显更隐蔽（无 `--remote-debugging-*`、无 Playwright 标志、真实 profile）。

---

## 8. 复现方式

1. `agent_browser`：`browser_navigate("https://bot.sannysoft.com/")` → `browser_evaluate` 跑 §2/§3 探针（采集 navigator/chrome/WebGL/permissions/CDP 探针）。
2. 进程取证：宿主 `Get-CimInstance Win32_Process -Filter "Name='chrome.exe'"`，过滤含 `remote-debugging|user-data-dir` 的命令行。
3. human_browser 对比：`human_browser_open(url)` 后同样取证，命令行应为纯 `chrome.exe <url>`、无调试标志、指向真实日常 profile。

> 数据来自单次真机实测（Chrome 148 / Playwright MCP 0.0.75 / Windows 11）；不同 Chrome / Playwright 版本、是否 headless、是否加 stealth 插件都会改变结果，结论以"层次框架"为准，具体取值需按版本复测。
