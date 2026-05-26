# iOS Platform Bridge — v0.8.2-alpha

> 状态：已实现（v0.8.2-alpha）。WDA + pymobiledevice3 实现，无 Appium / XCTest 直接依赖。支持多设备同时挂载（别名映射 + per-device holder 锁）。首批验证机型：iPad（iOS 26.2.1）。

iOS/iPadOS 测试设备桥，让 LLM agent 通过 WebDriverAgent 驱动 iPhone 或 iPad。

## 架构

```
[Agent (any OS)]  ──Tailscale──>  [macOS host]:8769  ──usbmux forward──>  [WDA on iOS device]
   MCP client                       MCP server           pymobiledevice3       WDA HTTP API
```

**关键三条**：

1. **MCP server 必须装在 macOS 上**——WDA 需要 Xcode 签名，macOS-only
2. **Server 通过 pymobiledevice3 usbmux 转发连 WDA**（不是 WiFi），每台设备占用 `18100+N` 端口
3. **WDA 必须提前在 Xcode 里 build 并跑起来**——Setup 脚本只管 ios-device MCP server，不管 WDA 部署。WDA 部署步骤见 `docs/platforms/ios.md`

## 支持设备

| 平台 | 支持情况 |
|---|---|
| iOS 16+ / iPadOS 16+ | 完整支持，已验证 |
| iOS 13–15 | 应支持（未重点测试）|
| iOS 12 及以下 | 未测试；WDA 最低要求 iOS 12，但 pymobiledevice3 部分特性可能受限 |

## Host 安装

| 要求 | 说明 |
|---|---|
| 操作系统 | macOS 12+（Xcode 要求）|
| Homebrew | brew 安装脚本依赖 |
| Python | `brew install python@3.12`（系统 Python 3.9.6 无法运行 fastmcp）|
| Xcode | 完整 Xcode.app（非 CLT only）用于 build/sign WDA |
| Tailscale | 已登录，用于 agent 侧访问 |

```bash
cd <repo-root>
bash platforms/ios/scripts/setup-ios.sh
```

Setup 脚本会：

1. 检查 / 提示安装 brew + python@3.12
2. 在 `platforms/ios/server/.venv` 建虚拟环境并 `pip install -e .`（拉取 fastmcp / pymobiledevice3 / httpx / pillow / pydantic）
3. 注册 launchd plist `cc.metahub.ios-device`（RunAtLoad + KeepAlive=Crashed）
4. 启动 service 并验证端口 8769 监听

WDA 部署（Xcode 操作）**不在** setup 脚本覆盖范围内，见 `docs/platforms/ios.md`。

## Demo — example agent session

```text
You:   "Open Settings, then Maps, and screenshot each."
Agent: launch_app(target="com.apple.Preferences")      → launched
       take_screenshot()                               → Settings
       launch_app(target="com.apple.Maps")             → launched
       take_screenshot()                               → Maps
```

This is exactly the flow in the animated demo GIF in the [main README](../../README.md)
— a real iPad driven over MCP, no human hands.

## 工具集（v0.8.2-alpha 实际暴露，共 26 个）

所有工具均接受可选 `device` 参数（UDID 或别名）。未传 `device` 且只连 1 台设备时自动路由。

| 类别 | 工具 | 备注 |
|---|---|---|
| 状态 | `acquire` / `release` / `get_status` | per-device 协作锁 |
| 会话默认设备 | `set_default_device` / `get_default_device` | MCP 会话级 sticky 默认 |
| 设备 | `list_devices` | 列出连接设备（udid / alias / model / os_version / in_use） |
| 屏幕 | `take_screenshot` / `get_screen_size` | WDA points 坐标系（非物理像素）|
| 触控 | `tap` / `swipe` / `long_press` | WDA point 坐标 |
| 键盘/按键 | `type_text` / `press_key` | type_text 走 UIKit（支持 Unicode）；press_key 仅 home/volume_up/volume_down/lock |
| 应用 | `list_apps` / `install_app` / `uninstall_app` / `launch_app` / `terminate_app` / `activate_app` / `current_app` | install = pymobiledevice3；launch/terminate/activate/current = WDA |
| 文件 | `push_file_to_app` / `pull_file_from_app` | 仅限 UIFileSharingEnabled 应用的 Documents 沙箱 |
| UI 内省 | `dump_ui` / `find_elements` / `tap_element` | WDA /source + /elements；推荐 class chain 定位器 |
| 设备信息 | `device_info` | OS 版本、build、电量、型号（pymobiledevice3 lockdown + diagnostics）|

> 与 android-device 的主要差异：**无 `run_shell`**（iOS 沙箱），文件传输限于 UIFileSharingEnabled 应用，`press_key` 只支持 4 个物理按键，坐标系为 WDA points。

### Platform-specific extensions · 平台特定扩展

上面工具集表里属于 iOS 平台特定扩展（不在四平台 universal tool set 内）的工具：

- `activate_app` / `device_info` / `list_apps` — iOS-only（WDA `/wda/apps` + pymobiledevice3 lockdown/diagnostics）
- `push_file_to_app` / `pull_file_from_app` — iOS-only（pymobiledevice3 AFC，沙箱受限）
- `long_press` — mobile-only（Android / iOS 共有，桌面平台未对齐）
- `install_app` / `uninstall_app` — mobile-only（pymobiledevice3）

跨平台对照见 [`docs/architecture.md` 平台扩展节](../../docs/architecture.md#平台扩展)；完整签名见 [`docs/internal/blueprint/INTERFACE.md`](../../docs/internal/blueprint/INTERFACE.md)。

## 已知限制

1. **无 shell 工具**——iOS 完全沙箱化，不暴露 shell 访问；主机侧 shell 请用 mac-device 的 `run_shell`
2. **文件传输受限**——只能访问有 `UIFileSharingEnabled=true` 的应用 Documents 目录
3. **WDA 需手动部署**——每次证书过期（免费 Apple ID 7 天，付费 Developer 1 年）需在 Xcode 重新签名并启动
4. **hot-plug 通知未实现**——新插入/拔出设备需调 `list_devices()` 主动刷新
5. **install_app 大文件受限**——pymobiledevice3 子进程超时硬限 25s（fastmcp transport deadline），超大 ipa 需异步安装方案（规划中）

## 详细安装文档

见 [`docs/platforms/ios.md`](../../docs/platforms/ios.md)（WDA Xcode 构建步骤、证书续签、常见问题）。

## License

Apache 2.0 — 见 [`../../LICENSE`](../../LICENSE)。
