# iOS Device Setup Guide

> ⚠️ **v0.8.0-alpha WIP**：iOS bridge 处于实验阶段，仅在 macOS host + WebDriverAgent 路径上验证。文档持续更新。

接入流程比 Android 复杂得多——iOS 没有 `adb` 等价物，所有 UI 自动化必须经过苹果的 XCTest 框架（WebDriverAgent，简称 WDA）。本指南覆盖：

1. [Host 要求](#host-要求)
2. [Step 1 — 完整 Xcode + Apple ID](#step-1--完整-xcode--apple-id)
3. [Step 2 — 信任电脑 + 连接设备](#step-2--信任电脑--连接设备)
4. [Step 3 — Clone & Build WebDriverAgent](#step-3--clone--build-webdriveragent)
5. [Step 4 — 信任开发者证书 + 验证 WDA](#step-4--信任开发者证书--验证-wda)
6. [Step 5 — 启动 ios-device server](#step-5--启动-ios-device-server)
7. [多设备模式](#多设备模式)
8. [Server 管理](#server-管理)
9. [Troubleshooting](#troubleshooting)

---

## Host 要求

| 项 | 要求 |
|---|---|
| OS | **macOS only**（Xcode 必需，Linux/Windows 无法替代）|
| Hardware | Apple Silicon 或 Intel Mac；建议 ≥16GB RAM、≥40GB 空闲磁盘 |
| Xcode | **完整 Xcode 16+ / Xcode 26+**（不是 Command Line Tools）|
| Apple ID | 免费即可（7 天证书过期需重新 build），或 $99/年付费版 |
| Python | 3.9+（macOS 26 默认 3.9.6 够用；3.10+ 也行）|
| ADB-like | **不需要** adb / libimobiledevice CLI；后端用 `pymobiledevice3` 纯 Python |

### 设备支持矩阵

| 设备 | iOS / iPadOS 版本 | 状态 |
|---|---|---|
| iPhone (iOS 13+) | ✅ 完整支持 |
| iPad (iPadOS 13+) | ✅ 完整支持 |
| iPhone (iOS 12 及更老) | ⚠️ **untested** — WDA 1.x fork + 老 Xcode/Mac 环境难凑齐，**不推荐** |
| iPad Mini / Pro 26+ | ✅ 同 iPad，验证机型 iPad15,7 + iPadOS 26.2.1 |

---

## 脚本自动化（v0.8.1+，推荐）

下面 Step 1-5 是完整手动流程（理解每步用）。实际接入有三个脚本把能自动的都自动了，剩下的明确引导：

| 脚本 | 做什么 |
|---|---|
| `platforms/ios/scripts/setup-ios.sh` | 一键 wizard：装 server venv + launchd + **[6] 设备接入引导**（检测每台设备 Developer Mode 状态、跑自动化、检测 WDA、逐台提示下一步）|
| `platforms/ios/scripts/ios-device-prep.sh <udid>` | 单设备：amfi 自动开 Developer Mode + 检测 + 打印剩余必须项清单（带 Settings 路径）|
| `platforms/ios/scripts/build-wda.sh <udid> <bundle_id>` | 全命令行 build WDA：Team ID 自动提取 + 任意设备复用 profile（**不碰 Xcode IDE**）|

**最少介入流程**（免费 Apple ID）：
1. 一次性：Xcode 登录 Apple ID + 配 1 个 bundle id build 一次生成 profile（免费账号的 provisioning 限制，见 [设计文档](../internal/design/2026-05-20-ios-onboarding-optimization.md)）
2. 每台设备：`ios-device-prep.sh <udid>`（自动 Developer Mode + 引导清单）→ 照清单点几下 → `build-wda.sh <udid> <bundle_id>`（全自动）
3. `setup-ios.sh` 一键把 server + 设备引导串起来

付费 Apple Developer + App Store Connect API key 可连第 1 步 GUI 都免。

---

## Step 1 — 完整 Xcode + Apple ID

### 1.1 装 Xcode

**App Store 路径**（推荐，最稳）：
- macOS 上打开 App Store → 搜索 "Xcode" → 安装
- 下载 ~17GB，30 分钟到 2 小时不等

**developer.apple.com 路径**（直接下载 .xip 包，比 App Store 快）：
- 登录 [developer.apple.com/download/all](https://developer.apple.com/download/all/?q=Xcode)
- 选最新版 Xcode → 下载 `.xip`（~10GB）
- 双击解压 → 拖到 `/Applications/`

### 1.2 切换 active developer dir 到 Xcode

Xcode 装好后跑：

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -version
# Xcode 26.5  Build version 17F42
```

### 1.3 登录 Apple ID

打开 Xcode → 菜单栏 **Xcode → Settings → Accounts** → 左下角 `+` → Apple ID → 输入你的 Apple ID + 密码 + 2FA 验证码。登录后会显示 Team（个人 Apple ID 显示为 "Personal Team"）。

> **付费 Developer 账号** 登录后会有真实 Team 名（如 "Your Company - $TEAMID"），证书 1 年有效；免费 Personal Team 证书 7 天过期，到期后需在 Xcode 重新 Build & Run 一次重签。

---

## Step 2 — 信任电脑 + 连接设备 + 开启 Developer Mode

1. iPhone/iPad 用 USB 数据线连接 macOS host
2. **设备会弹"信任此电脑？"** → 点信任 + 输入设备解锁密码（Face ID/Touch ID 不能跳过）
3. **开启 Developer Mode（iOS / iPadOS 16+ 必须）**：
   - 设备 **设置 → 隐私与安全性（Privacy & Security）→ 滑到底部 → 开发者模式（Developer Mode）**
   - 打开开关 → 系统提示**重启设备**
   - 重启后锁屏会弹"是否打开开发者模式" → 点**打开** + 输密码
   - ⚠️ 不开 Developer Mode，WDA 会安装但**无法启动**，`xcodebuild test` 报 `Developer Mode disabled`
   - 💡 Developer Mode 选项只在设备**连过 Xcode/开发工具后**才出现；若看不到，先做一次 Step 3 的 build
4. 验证 host 端能看到设备：

```bash
~/Library/Python/3.9/bin/pymobiledevice3 usbmux list
# [
#   {
#     "ConnectionType": "USB",
#     "DeviceClass": "iPhone",
#     "DeviceName": "您的 iPhone",
#     "Identifier": "00008020-...",
#     "ProductType": "iPhone11,8",
#     "ProductVersion": "18.7.9",
#     ...
#   }
# ]
```

如果列表为空：拔掉重插 + 重新点信任 + 检查数据线（充电线没有数据通道）。

---

## Step 3 — Clone & Build WebDriverAgent

### 3.1 Clone repo

```bash
cd ~
git -c http.version=HTTP/1.1 clone https://github.com/appium/WebDriverAgent.git --depth 1
```

> 国内有时 GitHub HTTP2 framing layer 报错，加 `-c http.version=HTTP/1.1` 强制 HTTP/1.1 绕开。

### 3.2 用 Xcode 打开 WDA project

```bash
open ~/WebDriverAgent/WebDriverAgent.xcodeproj
```

Xcode 会启动并加载 project。等待 indexing 完成（左上进度条停转）。

### 3.3 配置签名

**这一步对每台 iOS 设备各做一次**。

1. 左侧 navigator 选 `WebDriverAgent` project（最上面的蓝图标）
2. 中间面板选 target `WebDriverAgentRunner`（**不是** `WebDriverAgentLib`）
3. 选 **Signing & Capabilities** tab
4. 勾选 ☑ **Automatically manage signing**
5. **Team** dropdown 选你 Apple ID 登录的 Team（个人就选 "Personal Team"）
6. **Bundle Identifier** 改为唯一值，比如：
   - iPhone XR: `com.qjl.WebDriverAgentRunner.iphonexr`
   - iPad: `com.qjl.WebDriverAgentRunner.ipad`

> 免费 Personal Team 限制每个 Apple ID 最多 3 个 App ID，每个 ID 必须全宇宙唯一（不能与别人重复）。`com.qjl.WebDriverAgentRunner` 这种自有 prefix 不会冲突。
>
> 如果 Xcode 报 "Failed to register bundle identifier"，把 bundle id 换成更独特的值（加日期/随机串）。

7. 同样设置 `IntegrationApp` target（在中间面板下拉切换）

### 3.4 Build & Run 到设备

1. Xcode 顶部工具栏 **scheme** dropdown 选 `WebDriverAgentRunner`
2. **device** dropdown 选目标 iPhone（必须真机；模拟器跑 WDA 没意义）
3. 菜单栏 **Product → Test**（**注意是 Test 不是 Run**——WDA 作为 XCTest runner 必须 `Test` 而非普通 build）

或者命令行（推荐自动化）：

```bash
cd ~/WebDriverAgent
xcodebuild \
  -project WebDriverAgent.xcodeproj \
  -scheme WebDriverAgentRunner \
  -destination "id=<UDID>" \
  test
```

> UDID 用 `pymobiledevice3 usbmux list` 输出的 `Identifier` 字段。
>
> 第一次 build 较慢（5-10 分钟），编译 SwiftUI / XCTest framework。

Build 成功时控制台会出现 `XCTRunner` 启动信息 + WDA 监听 `device:8100`。

---

## Step 4 — 信任开发者证书 + 验证 WDA

### 4.1 信任开发者证书

iOS 默认不信任**任何**第三方开发者签名的 app（包括你自己用免费 Apple ID 签的）。**每台设备必须手动信任一次**：

1. iPhone/iPad 上：**设置 → 通用 → VPN与设备管理**（旧版可能是 "描述文件与设备管理"）
2. "开发者 App" 下找到你 Apple ID 对应的 entry → 点进入
3. 点 "信任 \"<你的 Apple ID>\"" → 弹窗确认

不信任的话，下次 launch 时会立刻 crash，dmesg 显示 codesign denied。

### 4.2 验证 WDA 在跑

USB 接 host，跑：

```bash
# pymobiledevice3 USB-forward 一个本地端口到 device:8100
~/Library/Python/3.9/bin/pymobiledevice3 usbmux forward 18100 8100 --udid <UDID> &
# 然后访问
curl http://127.0.0.1:18100/status
# {"value":{"build":{"time":"...","productBundleIdentifier":"com.qjl.WebDriverAgentRunner.iphonexr"},...}}
```

返回 `state: success` 即 WDA 健康。Ctrl-C 停 forward 进程（后续 ios-device server 自己会拉起）。

---

## Step 5 — 启动 ios-device server

### 5.1 第一次手动启（PoC 阶段）

```bash
cd ~/agent-fleet/platforms/ios/server
./.venv/bin/python ios_device_mcp.py
```

输出示例：

```
ios-device MCP server starting
  python    = /Users/qjl/agent-fleet/platforms/ios/server/.venv/bin/python
  devices   = 2 attached
    - apple-iphone11-8  (00008020…, iPhone iOS 18.7.9)
    - apple-ipad15-7    (00008120…, iPad iOS 26.2.1)
  transport = http (streamable) on 0.0.0.0:8769/mcp
```

Server 会**自动**为每台设备启动 USB-forward（device:8100 → host:18100+N）。如果 forward 失败（通常是 WDA 没在设备上跑），server 仍启动 + per-tool 调用时重试。

### 5.2 永久部署（待 v0.8.1 wizard 落地）

v0.8.0-alpha 阶段 **没有** launchd plist 自动重启支持，需要手动重启。

临时方案——后台 detach 启动：

```bash
cd ~/agent-fleet/platforms/ios/server
nohup ./.venv/bin/python ios_device_mcp.py >> ~/agent-fleet-ios-server.log 2>&1 &
```

⚠️ **不要**用 `Start-Process -RedirectStandardOutput` 等会让父 shell 持 child stdio handle 的方式，会导致远程 `mac-device.run_zsh` 调用看似 hang（与 [Android 同 bug](android.md#server-管理)）。

---

## 多设备模式

`ios-device` server 单 MCP 入口 mirror Android 的设计：

- `~/.claude.json` 只配一个 `ios-device` 入口指向 macmini:8769
- Server 自己按 `device` 参数路由到对应 UDID
- 24 个 tool 全部接受可选 `device=<udid|alias>` 参数
- `set_default_device(device="apple-iphone11-8")` 设当前 session 默认
- 别名自动从 ProductType 推断：`apple-iphone11-8` / `apple-ipad15-7`；重名按 UDID 字典序加 `-1/-2`
- 用户覆盖 alias：`~/.agent-fleet/ios-aliases.json`

详见 README + setup wizard 输出。

---

## Server 管理

(待 setup-ios.sh + launchd plist 完成后补充)

### 重启 server

```bash
# 找端口 8769 owner
lsof -iTCP:8769 -sTCP:LISTEN
# kill + 重启
pkill -f ios_device_mcp.py
cd ~/agent-fleet/platforms/ios/server
nohup ./.venv/bin/python ios_device_mcp.py >> ~/agent-fleet-ios-server.log 2>&1 &
```

### 看 log

```bash
tail -f ~/agent-fleet-ios-server.log
```

---

## Troubleshooting

| 现象 | 排查 |
|---|---|
| `usbmux list` 空 | 拔重插 + 重新信任电脑；检查数据线 |
| Xcode `Failed to register bundle identifier` | Bundle ID 改成更独特的值（加日期/随机串）|
| iPhone 上 WDA 安装后启动立刻闪退 | 没信任开发者证书。设置 → 通用 → VPN与设备管理 → 信任 |
| `pymobiledevice3 forward` 报 `Connection refused` | WDA 没在设备上跑。Xcode Product → Test 重跑一次 |
| WDA 几小时后失效 | 免费证书 7 天过期；Xcode 里重新 Test 一次自动重签 |
| Server 启动后看不到设备 | `xcode-select -p` 是否指向 Xcode.app 而非 CommandLineTools |

任意问题贴在 [GitHub Issues](https://github.com/metahub-tech/agent-fleet/issues)。
