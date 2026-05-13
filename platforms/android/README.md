# Android Platform Bridge — v0.4.0

> ✅ **状态：已实现**（v0.4.0）。pure-ADB 实现，无 uiautomator2 / scrcpy 依赖。首批验证机型：华为 P30 Pro (HarmonyOS 4.0 / EMUI 14 / 实际 Android 10 SDK 29)。

Android 测试设备桥，让 LLM agent 通过 ADB 驱动一台 Android 手机或模拟器。

## 架构

```
[Agent (any OS)]  ──Tailscale──>  [Host PC (Win/Mac)]:8768  ──ADB──>  [Android Phone]
   MCP client                       MCP server                          USB OR WiFi 都可
```

**关键三条**：

1. **MCP server 必须装在一台 PC 上**（Win 或 Mac），不能装在手机上——手机上跑不了 Python MCP server
2. **Server 通过 ADB 连手机**（不是直连），所以 PC 上要有 `adb` 二进制（platform-tools 的一部分）
3. **USB / WiFi 是 ADB → 手机的连接方式选项**，与 host OS 无关；server 内部模式无关，只关心 `adb devices` 能列出设备

## Host 安装矩阵

| Host OS | Setup 脚本 | 装 ADB 的方式 | 服务托管 |
|---|---|---|---|
| Windows 10/11 | `platforms/android/scripts/setup-android.ps1` | `winget install Google.PlatformTools` | Task Scheduler `MCP-AndroidDevice` |
| macOS 12+ | `platforms/android/scripts/setup-android.sh` | `brew install --cask android-platform-tools` | launchd `cc.metahub.android-device` |

setup 脚本会**问一次** ADB 连接模式，并据此走对应分支。模式选了之后写入 `~/.atb-android/config.toml`，之后 server 启动就用该模式。改模式只需改配置文件 + 重启 service。

## 正确的安装顺序（**严格按此顺序**，避免反复弹窗）

> ⚠️ 这是 v0.3.0 macOS 部署中得到的教训：操作顺序错误会导致 macOS / 手机弹窗先后顺序乱，每次都让人误以为"权限给了又没生效"。Android 这边按下面顺序走，能完全避免。

### 阶段 A：手机端准备（先做这个！）

1. 打开手机 **设置 → 关于手机**
2. 连续点 **版本号** 7 次，提示"已开启开发者选项"
3. 返回 **设置 → 系统与更新 → 开发人员选项**（HarmonyOS 在"系统与更新"下；原生 Android 在"系统"下）
4. 打开 **USB 调试**（如果走 USB 模式）或 **无线调试**（如果走 WiFi 模式）
5. **下一步与 PC 端配对前，不要插 USB 线**——先做完阶段 B 让 PC 端 adb 命令可用

### 阶段 B：PC 端 setup（Win 或 Mac 二选一）

#### Win11

```powershell
cd C:\path\to\agent-fleet
powershell -ExecutionPolicy Bypass -File platforms\android\scripts\setup-android.ps1
```

#### macOS

```bash
cd ~/path/to/agent-fleet
bash platforms/android/scripts/setup-android.sh
```

setup 脚本会：

1. 检查 / 装 Tailscale
2. 检查 / 装 Python 3.10+
3. 检查 / 装 platform-tools（adb）
4. 在 `platforms/android/server/.venv` 建虚拟环境装依赖
5. **询问 ADB 连接模式（USB / Wireless / Hybrid）**
6. 写入 `~/.atb-android/config.toml`
7. 注册自启 service（Task Scheduler 或 launchd）
8. 打印**第三阶段的具体步骤**，按你选的模式分支（避免你猜）

### 阶段 C：手机配对（按你选的模式）

#### C-1：USB 模式

1. 用 USB 线连手机到 PC
2. 手机弹**「允许此电脑进行 USB 调试」** → 勾选「始终允许」+ 点确定
3. PC 上 `adb devices` 应能列出手机 serial number

#### C-2：Wireless Debugging 模式（**仅 Android 11+ / SDK 30+**）

> ⚠️ HarmonyOS 4.0 部分机型（如 P30 Pro VOG-AL00）`ro.build.version.release` 实测为 **10**，对应 SDK 29，**没有原生无线调试**。先 `adb shell getprop ro.build.version.release` 确认 ≥11 再选这条路；不到就走 C-1 USB 或 C-3 Hybrid。

1. 手机 设置 → 开发者 → **无线调试 → 使用配对码配对设备**
2. 手机屏幕显示一个**配对码**（6 位数）和**手机 IP:端口**（IP 和 port 临时随机生成）
3. PC 上跑：
   ```
   adb pair <PHONE_IP>:<PAIRING_PORT>
   # 提示输入配对码 → 输入手机屏幕上那 6 位
   ```
4. 配对成功后 PC 上跑：
   ```
   adb connect <PHONE_IP>:<ADB_PORT>
   # ADB_PORT 在手机的「无线调试」主界面显示，与配对端口不是同一个
   ```
5. `adb devices` 列出手机

> 配对一次永久。手机重启 / WiFi 切换不会丢失（与 USB 模式不同）。

#### C-3：Hybrid（USB enroll + WiFi 日常）

1. 走 C-1 USB 步骤
2. 在 USB 状态下 `adb tcpip 5555`
3. 拔 USB 线
4. `adb connect <PHONE_IP>:5555`

> 手机重启后失效，需重新插 USB。仅 Android 5-10 推荐。

## 工具集（v0.4.0 实际暴露）

| 类别 | 工具 | 备注 |
|---|---|---|
| 状态 | `acquire_android` / `release_android` / `get_android_status` | 多 agent 协作 |
| 设备 | `list_devices` | 列出 host 上 adb 看到的所有设备 |
| 屏幕 | `take_screenshot` / `get_screen_size` | screencap 直读，1:1 像素，不缩放 |
| 触控 | `tap` / `swipe` / `long_press` | 物理屏幕坐标系 |
| 键盘 | `type_text` / `press_key` | press_key 别名：back/home/menu/recent/power/volume_up 等 |
| 应用 | `list_packages` / `install_apk` / `uninstall_app` / `start_app` / `kill_app` / `current_app` | apk 安装走 host->phone push |
| Shell | `adb_shell` | 在设备上跑 shell 命令（`getprop` / `dumpsys` / `am` 等） |
| 文件 | `push_file` / `pull_file` | host ↔ device |

> 16 个工具。`type_text` 仅 ASCII（Android `input text` 限制），中文 / emoji 不行；UI 内省（`dump_xml` / `find_by_resource_id`）走 v0.4.1 在 uiautomator2 后再加；视频录制走 v0.5（scrcpy --record 流式回传方案待定）。

## 已知限制

1. **`type_text` 不支持中文 / emoji** —— `adb input text` 在大多数 ROM 上是 ASCII-only
2. **单设备**：v0.4 只支持一个 device，多设备情况下要 unplug 其他或 set `ATB_ANDROID_SERIAL`
3. **OEM 截屏拦截**：Huawei / Xiaomi 部分 ROM 在 `exec-out screencap` 上有问题；我们有 `/sdcard` push-pull fallback，但更顽固的需要在 Developer Options 关闭"权限监控"
4. **Wireless Debugging 不通用**：HarmonyOS 4.0 P30 Pro 实际报 Android 10 / SDK 29，无原生无线调试。Hybrid 模式（USB enroll + tcpip 5555）是变通方案。

## License

Apache 2.0 — 见 [`../../LICENSE`](../../LICENSE)。
