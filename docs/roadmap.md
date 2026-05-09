# Roadmap

## Status Snapshot

*Last updated: 2026-05-09*

| Version | Platform | Status |
|---|---|---|
| 0.1.0 | Windows 10/11 (initial) | ✅ Released |
| 0.2.0 | Windows 10/11 (winpc-gui consolidated) | ✅ Released |
| 0.3.0 | macOS (12+) | ✅ Released |
| 0.4.0 | Android | 📋 Planned |
| 0.5.0 | iOS (Simulator + real device) | 📋 Planned |
| 0.6.0 | Cross-device coordination | 🔭 Future |
| 1.0.0 | Public open-source release | 🔭 Future |

Legend: ✅ released · 🚧 in progress · 📋 planned · 🔭 future

---

## v0.1.0 — Windows (initial)
**Released 2026-05-06**

- Tailscale + 双 MCP 服务（desktop-commander 端口 8765 + 自写 GUI MCP 端口 8766）
- 17 个通用工具：屏幕 / 鼠标 / 键盘 / 窗口 / 进程 / PowerShell
- 一键安装脚本（含 Task Scheduler 自启）
- 中文 setup guide ~500 行

---

## v0.2.0 — Windows (winpc-gui consolidated)
**Released 2026-05-08**

- 把 v0.1 的两服务（winpc-shell mcp-proxy + winpc-gui FastMCP）合并到一个 FastMCP server，去掉 Node / mcp-proxy / supergateway / portproxy 依赖链
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
- `using-macbox` skill 含 GUI 烟测 recipe

---

## v0.4.0 — Android
**Target: TBD**

### 范围
- 驱动栈：adb + uiautomator2（Python 库）+ scrcpy（视频流）
- 设备主机可以是任意 OS，推荐 Linux/Mac
- USB 或 wireless adb（`adb tcpip 5555`）
- 工具集除通用外加：`install_apk` / `dump_uiautomator_xml` / `adb_command`
- 端口 8768

### 待解决问题
- 多设备支持：一台主机接多个手机时按 serial number 命名空间隔离
- 截屏用 uiautomator2 vs scrcpy snapshot：选 scrcpy（更快、视频流方便回放）
- 国内厂商定制 ROM（华为/小米/OPPO/vivo）的 USB 调试授权差异，需要逐个验证

---

## v0.5.0 — iOS
**Target: TBD**

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

## v0.6.0 — Cross-device Coordination
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

## Out of Scope (for now)

- **Linux 桌面桥** —— 当前没 GUI 测试需求；命令行任务通过 desktop-commander 已能覆盖
- **Web 浏览器桥** —— Playwright MCP 已覆盖
- **嵌入式 / IoT 设备** —— 接口太异构，等实际用例出现再考虑
- **跨平台 browser extension 测试** —— v1.x 之后再讨论
