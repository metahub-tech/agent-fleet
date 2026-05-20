# iOS 接入流程优化设计

> 目标：用户介入越少越好、越简单越好、越明确越好（可引导）。
> 来源：v0.8.0 iOS bring-up（iPhone XR + iPad，iPadOS 26 / iOS 18）真机踩坑全记录。

## 一、人工介入点全量清单（17 个）

| # | 介入点 | 阶段 | v0.8.0 怎么做的 | 分级 |
|---|---|---|---|---|
| 1 | 装 git | host | `xcode-select --install` | 🟡 引导（install.sh preflight 已做）|
| 2 | 装 brew | host | gitee 镜像脚本 | 🟡 引导（已做）|
| 3 | 装 python@3.12 | host | brew install | 🟢 setup 自动 |
| 4 | 装完整 Xcode | host | App Store 手动 17GB | 🟡 xcodes 引导 |
| 5 | xcode-select -s + license | host | 手动 sudo | 🟢 脚本自动 |
| 6 | Xcode 登录 Apple ID | host | GUI | 🔴 免费必须 / 🟢 付费 API key |
| 7 | 插 USB + 信任电脑 | 设备 | GUI + 密码 | 🔴 物理+安全 |
| 8 | 开 Developer Mode + 重启 | 设备 | GUI 进设置 | 🟢 amfi 触发 + 🔴 锁屏确认 |
| 9 | 关屏幕使用时间限制 | 设备 | GUI | 🔴 安全（可检测引导）|
| 10 | 信任开发者证书 | 设备 | GUI | 🔴 安全 / 🟢 付费缓解 |
| 11 | 开 UI Automation + 重启 | 设备 | GUI + 重启 | 🔴 安全（可检测）|
| 12 | 自动锁定永不 + 解锁 | 设备 | GUI | 🔴（可引导）|
| 13 | automation 密码确认 | 设备 | 输密码 | 🔴 安全 / 🟢 无密码或付费 |
| 14 | Xcode 配 signing (Team+Bundle) | WDA | GUI（易选错 target）| 🟢 CLI signing |
| 15 | xcodebuild test | WDA | CLI ✅ | 🟢 已自动 |
| 16 | WDA 保活 | 运维 | xcodebuild 常驻（会挂）| 🟢 daemon 化（#155）|
| 17 | 证书 7 天过期 | 运维 | 重 build | 🟢 付费 1 年 |

## 二、关键技术发现

### CLI signing 的免费 account 限制（实测）
- `xcodebuild -allowProvisioningUpdates DEVELOPMENT_TEAM=<id> PRODUCT_BUNDLE_IDENTIFIER=<新bundle>` 对**新 bundle id** 失败：`No Accounts: Add a new account`。免费 Apple ID 的 automatic provisioning 新 profile 需要 account 认证，launchd/非 GUI shell 拿不到。
- **但**：**已有 profile 的 bundle id** + `-allowProvisioningUpdates` 命令行 build **任意新设备** work（自动加 UDID，无需新认证）。v0.8.0 用 iPad 的 bundle id 命令行 build XR 成功验证。
- **结论**：免费 account 首次需 GUI 配 1 个 bundle id 生成 initial profile；之后所有设备命令行复用。付费 + App Store Connect API key (`-authenticationKeyPath`) 可连首次 GUI 都免。

### Team ID 自动提取（实测 work）
```bash
security find-identity -v -p codesigning | grep "Apple Development" | head -1 | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/'
# → 88JD8354S4 (Personal Team ID)
```

### pymobiledevice3 设备自动化能力（实测）
- `amfi reveal-developer-mode` — 让 Developer Mode 选项在设备 UI 出现（免去"先连 Xcode 才出现"）
- `amfi enable-developer-mode` — 远程触发开启（设备重启 + 锁屏确认仍需用户）
- `amfi developer-mode-status` — 查状态（wizard 检测用）
- `diagnostics restart` — 远程重启设备
- `usbmux list` — pairing/设备检测
- WDA `/status` — UI Automation + WDA 健康探测

## 三、优化后用户体验

**免费 account**：首次每机一次性 GUI（登录 Apple ID + 配 1 bundle id + build 1 次）。之后每台设备只需 4 个不可绕过的物理/安全确认：
1. 插 USB 点信任电脑
2. Developer Mode 重启后锁屏点打开
3. 信任开发者证书
4. automation 密码（无密码/付费可免）

**其余全自动**：host 工具链、Developer Mode 触发+重启、WDA build+signing、状态检测。

**付费 account**：连首次 GUI 都免（API key automatic provisioning）。

## 四、实现路线（O1–O4 + daemon）

- **O1**（#156）✅ `platforms/ios/scripts/build-wda.sh` — Team ID 自动提取 + 统一 bundle id + allowProvisioningUpdates 命令行 build 任意设备。消除每台设备 GUI 配 target。
- **O2**（#157）设备配置自动化：setup-ios.sh 集成 amfi reveal/enable developer-mode + developer-mode-status 检测 + diagnostics restart。
- **O3**（#158）setup-ios.sh wizard v2：自动化 O1+O2 + 检测每步前置状态 + 4 必须项明确分步引导（带设备路径）+ 多设备循环。
- **O4**（#159）xcodes CLI 自动装 Xcode（Apple ID + 2FA 一次）+ xcode-select/license 自动。
- **daemon**（#155）WDA daemon 化（go-ios / pymobiledevice3 xctest）解保活 + 配合付费证书解 7 天痛点。

## 五、付费 Apple Developer 的价值（建议）
$99/年 解锁：证书 1 年（vs 免费 7 天）+ App Store Connect API key 命令行完全自动 provisioning（消除首次 GUI 登录/配 bundle）+ 100 设备注册。对长期多设备 agent-fleet 部署 ROI 高。PoC 已用免费 account 验证全链路，可转付费。
