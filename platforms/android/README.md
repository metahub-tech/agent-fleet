# Android Platform Bridge — v0.4 (Planned)

> 🚧 **状态：未实现**。这个目录目前是骨架占位，对应 [roadmap.md v0.4.0](../../docs/roadmap.md#v040--android)。文件结构和 windows / macos 平台严格对称，等真实实现填进来。

Android 测试设备桥，让 LLM agent 通过 ADB + uiautomator2 + scrcpy 驱动一台 Android 手机或模拟器。

## 计划架构

```
[Agent (any OS)]  ──Tailscale──>  [Host PC (Win/Mac)]:8768  ──ADB──>  [Android Phone]
   MCP client                       MCP server                          USB OR WiFi 都可
```

**关键三条**：

1. **MCP server 必须装在一台 PC 上**（Win 或 Mac），不能装在手机上——手机上跑不了 Python MCP server
2. **Server 通过 ADB 连手机**（不是直连），所以 PC 上要有 `adb` 二进制（platform-tools 的一部分）
3. **USB / WiFi 是 ADB → 手机的连接方式选项**，与 host OS 无关；server 内部模式无关，只关心 `adb devices` 能列出设备

## Host 安装矩阵（共 4 条独立 walkthrough）

| Host OS | Setup 脚本 | 装 ADB 的方式 |
|---|---|---|
| Windows 10/11 | `platforms/android/scripts/setup-android.ps1` | `winget install Google.PlatformTools` |
| macOS 12+ | `platforms/android/scripts/setup-android.sh` | `brew install android-platform-tools` |

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
cd C:\path\to\agent-test-bench
powershell -ExecutionPolicy Bypass -File platforms\android\scripts\setup-android.ps1
```

#### macOS

```bash
cd ~/path/to/agent-test-bench
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

#### C-2：Wireless Debugging 模式（推荐）

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

## 计划工具集（Universal + Android-specific）

| 类别 | 工具（计划） | 备注 |
|---|---|---|
| 状态 | `acquire_android` / `release_android` / `get_android_status` | 多 agent 协作 |
| 屏幕 | `take_screenshot` | scrcpy snapshot 优先，回退 uiautomator2 |
| 触控 | `tap` / `swipe` / `long_press` | 比 Windows/macOS 多手势类型 |
| 键盘 | `type_text` / `press_key` (back/home/menu/recent/volume_up/...) | Android 物理 key 语义 |
| 应用 | `install_apk` / `uninstall_app` / `start_app` (intent) / `kill_app` | apk 文件管理 |
| Shell | `adb_shell` (在设备上)，`run_bash` / `run_powershell` (在 host 上) | 区分两个执行域 |
| UI 内省 | `dump_uiautomator_xml` / `find_by_resource_id` | accessibility tree 查询 |
| 录像 | `start_recording` / `stop_recording` | scrcpy --record 长任务 |

## 计划开发难点（按优先级）

1. **国内厂商定制 ROM 的 USB 调试授权差异**——华为 / 小米 / OPPO / vivo 各家弹窗时机和措辞不一；**Wireless Debugging 模式下基本绕开**
2. **HarmonyOS 4.0+ 与原生 AOSP 的 ADB 兼容性**（首批测试机 P30 Pro 用 HarmonyOS 4.0.0；底层 Android 12 但 EMUI/HarmonyOS 加了若干限制）
3. **多设备**：一个 host 接多台手机时按 serial number 命名空间隔离（`acquire_android(device_serial="...")`）；单设备自动选默认
4. **scrcpy 视频流的 SSE 兼容性**（可能不直接 stream，转 frame snapshot）
5. **多桥共存**：host 同时跑 winpc-gui (8766) + android (8768) 时的 scheduled task / venv / 日志隔离

## 当前结构

```
platforms/android/
├── README.md                       # 本文件
├── server/                         # （空）将来放 android_mcp.py + 依赖
├── scripts/                        # （空）将来放 setup-android.ps1 + setup-android.sh
├── skills/using-android/           # （空）将来放 SKILL.md
└── examples/                       # （空）将来放 claude-settings.json
```

## 启动开发

按 [`docs/install-pattern.md` § 5（添加新平台·范式）](../../docs/install-pattern.md#5-添加新平台--范式) 八步走起。从 macOS 平台 port，把 pyautogui / ImageGrab 替换成 uiautomator2 + scrcpy。

## License

Apache 2.0 — 见 [`../../LICENSE`](../../LICENSE)。
