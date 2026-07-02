# 确定性装 human_dom 扩展（终结 GUI 视觉自助路线）— 设计 spec

> 来源需求：AgentHub #100 G2 真机 E2E（test-win11，2026-07-02）三轮实证「视觉自助 Load-unpacked」全失败，创始人裁决转确定性安装路线。对应 `agenthub-req-2026-07-02-deterministic-dom-install.md`。

## 1. 需求回溯（从用户痛点来）

- **用户需求**：发布员 operator（火山 kimi 视觉 agent）要在真账号页面用 human_dom 做 DOM 精度定位，前提是每个新团队的**全新 Chrome profile 必须先装上 human_dom 扩展**。
- **痛点**：Chrome 137+ 禁了 `--load-extension`，只剩 chrome://extensions「加载未打包」这一 GUI 路径；三轮真机实证 operator 视觉点「开发者模式」开关/「加载未打包」按钮**无一次独立成功**，轮3 实锤**视觉坐标系 DPI 失配**（截图算的开关坐标 (1347,82) vs 实际 (1893,115)）。
- **创始人裁决**：不能再依赖 agent 视觉点 GUI 装扩展；**每环节连续 5 次成功才算过关**。

## 2. 可行性调研结论（test-win11 / Chrome 149 真机实证）

### 2.1 ❌ 企业策略 force-install（自托管 off-store crx）— 实证不可行

按需求首选方案实测：Chrome `--pack-extension` 打包固定私钥 crx（id `fekca…ffoc`）→ 本地 http 服务 serve crx + update.xml → HKCU `ExtensionInstallForcelist` = `<id>;http://127.0.0.1:8912/update.xml`。

启全新 profile 后 **crx 未安装**；chrome://policy（CDP 读出）显示该条目为 **`[BLOCKED]`**，Chrome 明确报错：

> 「系统检测到本机计算机不属于企业环境，因此**只能自动安装 Chrome 应用商店中的扩展程序**。对应的 Chrome 应用商店更新地址为 https://clients2.google.com/service/update2/crx」

即：**非企业纳管机（无域加入 / 无 CBCM 云纳管）上，force-install 只认商店扩展**，自托管 off-store 一律 `[BLOCKED]`。要解锁必须让机器「企业纳管」（CBCM 云 token 或域加入）——创始人此前已明确否决（对 C 端要纳管用户浏览器、不可商用），商店上架也否决。**故 force-install 这条死。**

### 2.2 ✅ CDP `Extensions.loadUnpacked` — 实证可行，选定为落地方案

Chrome DevTools Protocol 的 `Extensions.loadUnpacked({path})`（浏览器级命令，Chrome 137+ 官方给自动化的 `--load-extension` 替代，Playwright 也走这条）在 **Chrome 149 实测通过**：

- 起 Chrome 带 `--remote-debugging-port=0`（临时端口，写进 `<udd>/DevToolsActivePort`）→ 连 CDP → `Extensions.loadUnpacked({path: <烤好的副本目录>})` → **返回扩展 id，零 UI、无需开发者模式开关、无需文件选择器、无视觉、无 DPI 依赖**。
- **端到端实证**：loadUnpacked 后导航到 http 页，content script 正常注入并连桥，auth 帧 `{"profile_id":"spiketest",...}` 与烤入值一致 → **PR#66 的 per-profile 路由完整保留**。
- **幂等**：同 path 二次 loadUnpacked 返回同 id、不报错 → 可在每次 `human_browser_open` 时无脑调用。
- **Secure Preferences 落盘**：loadUnpacked 会把扩展（含 source path）写进 `<profile>/Default/Secure Preferences` → 供 P0-B 查盘判 `installed`。

### 2.3 moat 分析（关键：human_browser 的「零自动化痕迹」不破）

human_browser 的立身之本是「无 debug 端口、无自动化标志 → 零痕迹」（真账号防风控）。加 CDP 与之张力，故实测确认 moat 不破：

| 信号 | 结果 |
|---|---|
| `navigator.webdriver`（仅加 `--remote-debugging-port`，不加 `--enable-automation`） | **false**（moat 主信号不变） |
| 网页 JS 连 CDP（带 Origin `https://evil.example.com`） | **403 Forbidden**（Chrome 默认挡 web-origin） |
| 我方 no-Origin 客户端连 CDP | 101 握手成功（**无需 `--remote-allow-origins`**，故不给网页开口子） |
| debug 端口 | `--remote-debugging-port=0` 临时端口、仅 127.0.0.1；网页 PNA/Origin 双重够不着 |

结论：临时 localhost debug 端口 + 无自动化标志 + 无 allow-origins → **网页侧零可达攻击面、`navigator.webdriver` 仍 false，moat 实质保全**。（更极致可用 `--remote-debugging-pipe` 彻底无端口，但 Windows 下 Python 传 fd handle 复杂，收益边际；先用 port=0，pipe 列为后续硬化项。）

## 3. 设计

### 3.1 P0-A：确定性装扩展（CDP loadUnpacked）

**新模块 `platforms/common/capabilities/human_dom/_loader.py`**（纯 stdlib，因真机无 `cryptography`/`websockets` 依赖）：
- `_read_devtools_port(udd, timeout)`：轮询 `<udd>/DevToolsActivePort` 拿临时端口（Chrome 启动后写，需重试）。
- 极简 CDP over websocket 客户端（stdlib socket + 自造帧，no-Origin）：连 `/json/version` 的 browser ws → 发 `Extensions.loadUnpacked` → 返回 `{ok, id}` 或 `{ok:False, error}`。**永不抛到 server**（装失败不阻断开浏览器）。
- `load_dom_extension(udd, ext_dir, timeout=8) -> dict`：编排上面两步。

**改 `_human_browser.py`**：
- `_human_launch_args`：起专用 profile 且要装 human_dom 时，加 `--remote-debugging-port=0`（临时端口）。
- `human_browser_open` 专用 profile 分支：auto-bake（已有）→ **起 Chrome 时不带目标 url（起空页）** → Popen → 调 `load_dom_extension(udd, ext_dir, navigate_url=url)` → 返回 `human_dom: {ok,id,navigated}`。装失败降级：仍开浏览器，note 提示回退。
- **关键顺序（真机实证）：必须 load 扩展后再 navigate**。content script 只在【新导航】时注入；若启动就带 url，扩展装好前页面已加载 → 脚本不注入 → 桥连不上。故 loader 装完再经 CDP `Page.navigate` 到目标页。
- docstring 更新：删掉「靠 chrome://extensions 持久 Load-unpacked / 视觉 agent 自助装」那套，改成「server 侧 CDP 自动装、operator 零操作」。

**win/mac server 注入**：`HumanBrowserCapability(bridge_port=_bridge_port)` 已注入桥端口，无需改接线（loadUnpacked 在能力内做）。

### 3.2 P0-B：`human_dom_status` 双维度 `{installed, connected, profiles, hint}`

- `compute_status` 增强：per-profile 除 `connected`（桥有该 profile_id 的活 client）外，`installed` = **`<ext_dir>/loaded.json` 标记存在**（`_loader` 在 CDP loadUnpacked 成功那刻写）。
- **为何不用 Chrome 的 Secure Preferences（原需求建议）**：真机实证 open 后 4s Secure Preferences 仍 size 0——Chrome 惰性 flush，即时查盘不可靠（会误判 installed=false 致验收失败）。unpacked 扩展也不落 `Extensions/<id>/`。故改用**我方在装成功即写的 `loaded.json`**：同样是盘上信号、但由我方控制时机、即时可靠。
- 顶层加 `hint`：讲清 installed=T/connected=F ⇒「已装、只是当前没连（没开页/没导航）→ 重开 human_browser_open 即自动重连，别重装」；installed=F ⇒「下次 human_browser_open 会自动装」。终结「未连接=未安装」误判。

### 3.3 P1-A：视觉坐标系 DPI 失配修复
（待 explorer 定位 win 截图/tap/DPI-awareness 代码后补实现细节；方向：让 take_screenshot 与 tap 统一坐标系——大概率 server 进程 DPI-unaware 致 Windows 虚拟化，需 `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`，或截图返回带实际分辨率/scale 让模型换算。有缩放机器实测。）

### 3.4 P2：平台感知路径 + paste_text 输入法
- CDP loadUnpacked 已消除「往文件选择器手输 `~/.fleet/...`」场景（P2 路径痛点的主因随之消解）；残留：status/note 里输出平台正确的绝对路径（不裸露 `~`）。
- `paste_text`：实证被搜狗中文输入法把 `//` 改 `、、`（`chrome:、、policy`）。粘贴/输入前强制切英文输入态（win：IMM `ImmSetOpenStatus(false)` / 切 en-US 布局；发完可复原）。（待 explorer 定位 paste_text 实现后补。）

## 4. 测试策略（TDD）

- `_loader.py`：纯函数/协议帧可单测（DevToolsActivePort 解析、CDP 帧编解码、loadUnpacked 结果映射）；真 CDP 交互靠 test-win11 真机烟测。
- `_human_browser.py`：`_human_launch_args` 加 debug-port 的纯函数断言；`human_browser_open` 调 loadUnpacked 用 monkeypatch 桩验编排 + 降级。
- `compute_status`：扩展现有 test，加 Secure Preferences 命中/未命中 + hint。
- P1-A/P2：纯函数（坐标换算 / IME 切换封装）单测 + 真机验。
- 每部分过 code-review subagent（章程质量门）。

## 5. 落地与版本

- v0.8.5-alpha = 合并 #66/#67/#68（baseline，创始人已批可代打）。
- 本需求新改动 = v0.8.6-alpha，跟进后续。
- test-win11 部署走 dev checkout + 重启 win server；创始人在 agenthub 侧接 5 连验收。

## 6. 验收标准（创始人定）

test-win11 连续 5 次：删团队→装新团队（全新 profile）→ operator 走到发布环节 → **扩展零人工就绪**（installed+connected true）→ human_dom_locate 出元素。5 连全绿才算过。

## 7. Architect 评审收口（有条件可落地 → 已收口）

architect 判 moat【可接受】：真正保住 moat 的是三条不变量——① 只 `--remote-debugging-port=0`、不加 `--enable-automation`（`navigator.webdriver` 恒 false）；② loader **装完即 detach、绝不 `Runtime.enable`/`Page.enable`**（故 operator 与真账号页交互时无任何 CDP domain enabled → 著名的 Runtime.enable 控制台侧信道不触发）；③ 端口临时/仅 127.0.0.1/网页 PNA+Origin 双重够不着（对目标站 JS 不可远程观测，残留仅本地攻击面）。

**收口项：**
1. **moat 回归护栏（已加）**：`test_moat_launch_never_enables_automation` / `test_moat_loader_never_enables_cdp_domains` / `test_moat_loader_detaches_after_load` —— 后人若给 loader 加 `Runtime.enable`、让 client 常驻、或误加 `--enable-automation`，测试即红。这是 moat 最脆弱点，已上锁。
2. **跨引擎破口（已知风险，措辞加粗，未机制强制）**：`human_browser_open` 不走共享 lease；若 `agent_browser` 先以 `--enable-automation` 起了同一 profile 的 udd，Chrome 单实例会把随后的 human_browser_open 转发进那个带自动化标志的实例 → `navigator.webdriver` 变 true、moat 破。**这是 human_browser 既有行为（非本 PR 引入），但本决策放大其后果。** 铁律：真账号 profile **全程只用 human_browser(+human_dom)、绝不与 agent_browser 混用同一 profile**（usage_hint 已声明）。后续硬化：让 open 走共享 lease 把「同 profile 拒混引擎」从文字升为机制。
3. **验收权威门 = `connected=true` / `human_dom_locate` 出元素**，`installed`(loaded.json) 仅作辅助——`_write_loaded_marker` 是 best-effort，落盘失败会 stale-false（功能正常但 installed 字面 false），故别把「installed 字面 true」当唯一硬门。
4. **「零操作」限定范围**：指 **operator 运行期零操作**（不点扩展页、不跑脚本）。新宿主仍需一次性 provisioning：`touch ~/.fleet/human-dom-ready` + 重启 server（host 级开关，决定是否注册 human_dom 工具族；在 5 连循环之外、之前完成，不绊验收）。
5. **已知边界**：`~/.fleet/human-dom-ext/<pid>` 按 profile（非 server）分目录、只烤一个 bridge_port；正式部署维持「一 profile 一 server」。`--remote-debugging-pipe`（彻底无端口，L3 更隐蔽）保留为 moat 后续硬化项（Windows 下 Python 传 fd handle 较复杂，收益边际）。
6. **需真机回归的触发点**：Chrome 大版本升级（CDP `Extensions` 域标 experimental，有签名/行为漂移可能）。
