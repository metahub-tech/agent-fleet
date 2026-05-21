# Roadmap

## Status Snapshot

*Last updated: 2026-05-21*

| Version | Theme | Status |
|---|---|---|
| 0.1.0 | Windows 10/11 (initial) | ✅ Released |
| 0.2.0 | Windows 10/11 (win-device consolidated) | ✅ Released |
| 0.3.0 | macOS (12+) | ✅ Released |
| 0.4.0 | Android | ✅ Released |
| 0.5.0-alpha | `agent-fleet setup` wizard | ✅ Released |
| 0.6.0-alpha | role rename to `<os>-device` + macOS permission primer | ✅ Released |
| 0.6.1-alpha | UI element introspection (Android uiautomator + macOS AX) | ✅ Released |
| 0.6.2-alpha | Post-install smoke tests + setup-prompt UX | ✅ Released |
| 0.6.3-alpha | Smoke-runner bugfix + Android setup docs | ✅ Released |
| 0.6.4-alpha | Smoke connection fix (localhost; ExceptionGroup unwrap) | ✅ Released |
| 0.6.5-alpha | UI introspection bugfixes (AXValueGetValue + adb capture_bytes) | ✅ Released |
| 0.6.6-alpha | macOS legacy-plist migration cleanup | ✅ Released |
| 0.6.7-alpha | Windows GBK subprocess decode crash fix | ✅ Released |
| 0.6.8-alpha | install.sh/.ps1: uvx local path | ✅ Released |
| 0.6.9-alpha | Windows: UTF-8 PS + firewall try-catch | ✅ Released |
| **0.6.10-alpha** | **Windows: require admin upfront + try-catch ScheduledTask** | ✅ Released |
| 0.6.11–0.6.15-alpha | Internal renames, wizard hardening, SSE→http sweep, open-source readiness | ✅ Released |
| **0.7.0-alpha** | **Android multi-device: alias map, 25 tools, per-device holder, MCP instructions/resource** | ✅ Released |
| **0.8.0-alpha** | **iOS / iPadOS bridge: ios-device, 26 tools, WebDriverAgent + pymobiledevice3, iPad real-device verified** | ✅ Released |
| **0.8.2-alpha** | **iOS WDA daemon (boot-survival + keep-alive) · README i18n (9 langs) + demo · architecture diagram** | ✅ Released |
| 0.9.0 | Cross-device coordination | 🔭 Future |
| **0.10.0** | **HarmonyOS (鸿蒙) bridge** — 5th platform (hdc + uitest) | 📋 Planned |
| 0.11.0+ | Expanded device coverage (Android TV · Linux desktop · Wear OS · 车机/AAOS · …) — see [Future device coverage](#future-device-coverage) | 📋 Planned |
| 1.0.0 | Public open-source stable | 🔭 Future |

Legend: ✅ released · 🚧 in progress · 📋 planned · 🔭 future

---

## v0.1.0 — Windows (initial)
**Released 2026-05-06**

- Tailscale + 双 MCP 服务（desktop-commander 端口 8765 + 自写 GUI MCP 端口 8766）
- 17 个通用工具：屏幕 / 鼠标 / 键盘 / 窗口 / 进程 / PowerShell
- 一键安装脚本（含 Task Scheduler 自启）
- 中文 setup guide ~500 行

---

## v0.2.0 — Windows (win-device consolidated)
**Released 2026-05-08**

- 把 v0.1 的两服务（winpc-shell mcp-proxy + win-device FastMCP）合并到一个 FastMCP server，去掉 Node / mcp-proxy / supergateway / portproxy 依赖链
- 新增 `acquire_winpc` / `release_winpc` / `get_winpc_status` 多 agent 协作的状态模型
- 启动器加 restart loop，遇 session lock kill python 后自动恢复
- 日志改 UTF-8（PS 5.1 默认 UTF-16 LE 的坑）

---

## v0.3.0 — macOS
**Released 2026-05-09**

- macOS 12+ 设备主机桥（Intel + Apple Silicon 通用）
- 驱动栈：FastMCP + pyautogui + ImageGrab + AppleScript（osascript）
- 31 个工具，跨 9 类（state / screen / mouse / keyboard / process / file / search / zsh / AppleScript）
- launchd 服务自启 + KeepAlive，无需 while-loop launcher
- 一键 setup-macos.sh：brew Tier-3 容错、ERR trap、目录写权限预检
- 完整 GUI 权限文档：Python.app 拖入 + python3.12 自动二次授权 + Full Disk Access 一招覆盖文稿/桌面/Library
- `take_screenshot` server 端 resize 到 logical-px，screenshot 像素 = click 像素
- `using-mac` skill 含 GUI 烟测 recipe

---

## v0.4.0 — Android
**Released**

### 范围
- 驱动栈：adb + uiautomator2（Python 库）+ scrcpy（视频流）
- 设备主机可以是任意 OS，推荐 Linux/Mac
- USB 或 wireless adb（`adb tcpip 5555`）
- 工具集除通用外加：`install_apk` / `dump_ui_hierarchy` / `adb_shell`
- 端口 8768

### 已解决
- 多设备支持：一台主机接多个手机时按 serial number 命名空间隔离（v0.4.1）
- 截屏采用 adb screencap（无 scrcpy 依赖，更可靠）
- 国内厂商定制 ROM（华为/小米/OPPO/vivo）的 USB 调试授权差异已逐一记录在 SKILL.md

---

## v0.7.0-alpha — Android 多设备
**Released 2026-05-18**

单 MCP 入口，控制挂在同一台主机上的多台 Android 手机。

### 已实现
- 设备别名映射（`~/.agent-fleet/android-aliases.json`），wizard 自动推断 `{brand}-{slug(model)}`
- 所有 25 个工具新增 `device` 参数（serial 或别名），未传时自动路由单机
- 新工具 `set_default_device` / `get_default_device`：MCP 会话级 sticky 默认
- `acquire_android` / `release_android` / `get_android_status` 全部 per-device 路由
- FastMCP `instructions=` 在 initialize 握手告知 Claude 当前连接设备清单
- MCP resource `androidfleet://devices`：实时设备 JSON 快照
- `list_devices` 返回 `alias` / `brand` / `model` / `in_use` / `holder` / `default_for_session`

---

## v0.8.0 — iOS
**Released 2026-05-20 (daemon + i18n in 0.8.2-alpha, 2026-05-21)**

### 范围
- 必须运行在 macOS 上（Xcode 强依赖）
- 模拟器：`xcrun simctl` 一系列子命令（boot/install/screenshot/io）
- 真机：WebDriverAgent + idb（Facebook iOS bridge）
- 端口 8769

### 待解决问题
- WebDriverAgent 维护负担：原项目 Facebook 已 archive，跟社区 fork（如 appium-webdriveragent）
- 真机签名：personal team 7 天有效期 vs 付费开发者账号，文档化双路径
- iOS 18+ 的 Accessibility 限制：部分操作可能被系统拦截

---

## v0.10.0 — HarmonyOS (鸿蒙) bridge
**📋 Planned — 5th platform bridge**

沿用 jump-host 架构：电脑（Win/Mac/Linux）经 USB 接入华为 HarmonyOS 手机/平板，agent 经电脑驱动。

### 范围
- 驱动栈：**hdc**（HarmonyOS Device Connector，adb 的对应物）—— `hdc shell` / `hdc file send` / `hdc shell snapshot_display`（截图）/ `hdc install <hap>`（装包）
- UI 自动化：HarmonyOS **uitest / hypium**（`@ohos.UiTest`）—— dump 布局 + 控件查找 / 点击 / 输入；accessibility 通道
- Host：任意装了 hdc 的电脑（Win/Mac/Linux），与 Android 一样挂在跳板电脑上；端口预留 8770
- 复用 android-device 的多设备架构：别名映射 + per-device holder + `device` 参数 + MCP instructions/resource

### 待解决
- **HarmonyOS NEXT（纯血鸿蒙，API 12+）vs 旧版 HarmonyOS（≤4，部分兼容 adb/AOSP）**：NEXT 去 AOSP、走 ArkUI，uitest API 与 Android uiautomator 不同，需分别检测/支持
- HAP 包签名（DevEco 证书 / hdc 签名流程）文档化
- hdc + uitest 工具链以中文文档为主、仍在演进；CI / 真机验证依赖华为设备
- 截图朝向 / 多分辨率（折叠屏）处理

### 为什么优先
华为在中国市场份额 #1–2、HarmonyOS NEXT 推进迅猛 —— 国内 App 跨端测试是生产刚需。难度中等：hdc 与 adb 同构，android-device 的多设备 / 跳板模式可大量复用。

---

## v0.9.0 — Cross-device Coordination
**Future**

Agent 一次提示，串联多设备。例：

> 在 Mac 上启动 web 服务，用 Android 真机访问首页确认渲染正常，再用 iOS 模拟器对比布局差异。

### 需要建设
- 协调层 MCP server（meta-server），把单条工具调用 fan-out 到对应设备
- 共享会话状态（测试构件、截图 diff、跨设备日志）
- 因果排序：跨设备动作的时序保证
- 一份 settings.json 同时挂多设备桥（参考 `examples/multi-platform-claude-settings.json`）

---

## v1.0.0 — Public Open-Source Release
**Future**

### 前置条件
- 四大平台桥稳定运行（被实际项目长期验证过）
- Universal Tool Set 公约冻结
- 实现每调用鉴权 (per-call bearer token)
- 至少 Windows + macOS 桥有 CI（lint + smoke test）
- 公开 docs：英文 Quick Start + 中文完整指南
- License: Apache 2.0（已配置）
- 完善 issue / PR 模板、Code of Conduct、Contributor License Agreement

### 公开后
- 在 awesome-mcp / mcp-servers 列表登记
- 写一篇 launch blog（中英文）
- 准备 demo 视频：Agent 一句话调动 4 台设备完成一个测试任务

---

## Future device coverage

架构原则：**电脑做跳板 —— 理论上凡是人能经电脑管理的设备，agent 都能接入**。下表把生产场景可能用到的设备，按「普及程度 × 接入难度」排优先级（普及度区分全球 / 中国）。

| 设备类型 | 工具链 | Host | 普及度 | 难度 | Tier | 备注 |
|---|---|---|---|---|---|---|
| **HarmonyOS 手机/平板（鸿蒙）** | hdc + uitest | Win/Mac/Linux | 高（CN 极高） | 中 | **1** | 见 [v0.10.0](#v0100--harmonyos-鸿蒙-bridge)；android-device 模式大量复用 |
| **Android TV / Google TV** | adb（复用 Android 桥） | 任意 | 中高 | 低 | **1** | 近似 Android，主要适配焦点/遥控导航 |
| **Linux 桌面** | X11: xdotool + AT-SPI · Wayland: ydotool + grim | Linux | 高 | 中 | **1** | X11 易、Wayland 碎片化偏难；从旧 out-of-scope 提上来 |
| Wear OS（安卓手表） | adb | 任意 | 中 | 低-中 | 2 | 复用 Android；小屏 UI 适配 |
| Android Automotive / 车机 IVI | adb | 任意 | 中（CN 增长快） | 中 | 2 | IVI 多基于 Android，车机 HMI 测试刚需；需车端调试开放 |
| Apple TV（tvOS） | Xcode + XCUITest | **Mac** | 中 | 中-高 | 2 | 类 iOS；焦点引擎 + 遥控导航 |
| 浏览器 / Web 应用 | Playwright / Selenium | 任意 | 极高 | 低 | 2 | **已被 Playwright MCP 覆盖**；agent-fleet 侧做标准化/编排即可 |
| 树莓派 / Linux SBC | SSH + Linux GUI 工具 | 任意 | 中 | 低-中 | 2 | 同 Linux 桌面；多为 headless/SSH |
| Apple Watch（watchOS） | Xcode + 配对 iPhone | **Mac** | 中 | 高 | 3 | 自动化能力受限，依赖配对机 |
| 三星 Tizen（TV/穿戴） | sdb + Tizen Studio | Win/Mac/Linux | 中（区域） | 中-高 | 3 | sdb 类 adb，工具链小众 |
| LG webOS（TV） | ares-cli（webOS CLI） | Win/Mac/Linux | 中（区域） | 中-高 | 3 | 区域性，主要 TV app 测试 |

**Tier**：1 = 近期排期（高价值且可行）；2 = 中期；3 = 机会性 / 小众。具体版本号待 0.10.0（鸿蒙）落地后按反馈细排。

### 不同模型 / 暂不规划
- **云真机农场**（BrowserStack / Sauce Labs / AWS Device Farm）：REST API 接入，**不是 jump-host 模型** —— 作为未来「远端设备源」集成单独评估。
- **游戏主机**（PS / Xbox / Switch）：仅 NDA 开发套件，不可行。
- **裸 MCU / 嵌入式**（ESP32 / Arduino 等）：无「经电脑管理的 GUI」，仅烧录 / 串口，不在本舰队范畴。
