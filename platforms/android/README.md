# Android Platform Bridge — v0.4 (Planned)

> 🚧 **状态：未实现**。这个目录目前是骨架占位，对应 [roadmap.md v0.4.0](../../docs/roadmap.md#v040--android)。文件结构和 windows / macos 平台严格对称，等真实实现填进来。

Android 测试设备桥，让 LLM agent 通过 ADB + uiautomator2 + scrcpy 驱动一台 Android 手机或模拟器。

## 计划架构

```
[Agent (any OS)] ──Tailscale──> [Device Host: Win/Linux/Mac] ──ADB──> [Android Device]
                                  MCP server :8768                       (USB OR Wireless OR Hybrid)
```

**设备主机不必是 Android 设备本身**——Android 不能跑 Python MCP server，所以 host 是任意 OS（Win/Linux/Mac 都行），通过 ADB 桥到一台或多台真实手机。Win/Linux/Mac 都有 `adb` 二进制（来自 Android platform-tools），跨平台行为一致。

**Host 与现有桥共存**：完全允许在已经跑 winpc-gui (8766) 的 Win11 上叠加 Android server (8768)——两个 service 互不干扰，端口不冲突，分别有自己的 venv 和 scheduled task。这是项目"平台 silo"设计有意支持的多桥共存场景。

## ADB 连接模式：USB ≠ 强制

| 模式 | Android 兼容 | 步骤 | 说明 |
|---|---|---|---|
| **Wireless Debugging（推荐）** | Android 11+ / HarmonyOS 4+ | 手机 设置 → 开发者 → 无线调试 → 配对码 → host `adb pair` + `adb connect` | 一次配对，永久连。不需要 USB 线。 |
| **USB 调试** | 全版本 | 插线 → 手机授权 → `adb devices` | 每次插线都要在手机弹窗点信任。OEM 驱动是常见痛点（华为需 HiSuite，小米需开发版）。 |
| **Hybrid（legacy tcpip）** | Android 5-10 | 插一次 USB → `adb tcpip 5555` → 拔线 → `adb connect <ip>:5555` | 重启手机后失效，需重新插线。仅向后兼容 |

`setup-android` 安装脚本应当**让用户显式选择**这三种模式，不要 hardcode USB。MCP server 内部模式无关——只要 `adb devices` 能列出设备就能驱动。

## 计划工具集（Universal + Android-specific）

| 类别 | 工具（计划） | 备注 |
|---|---|---|
| 状态 | `acquire_android` / `release_android` / `get_android_status` | 多 agent 协作 |
| 屏幕 | `take_screenshot` | scrcpy snapshot 优先，回退 uiautomator2 |
| 触控 | `tap` / `swipe` / `long_press` | 比 Windows/macOS 多手势类型 |
| 键盘 | `type_text` / `press_key` (back/home/menu/recent) | Android 物理 key 语义 |
| 应用 | `install_apk` / `uninstall_app` / `start_app` (intent) / `kill_app` | apk 文件管理 |
| Shell | `adb_shell` (在设备上)，`run_bash` (在 host 上) | 区分两个执行域 |
| UI 内省 | `dump_uiautomator_xml` / `find_by_resource_id` | accessibility tree 查询 |
| 录像 | `start_recording` / `stop_recording` | scrcpy --record 长任务 |

## 计划开发难点

- 国内厂商定制 ROM 的 USB 调试授权（华为 / 小米 / OPPO / vivo）行为差异——**用 Wireless Debugging 能绕开大半**
- HarmonyOS 4.0+ 与原生 AOSP 的 ADB 兼容性（首批测试机 P30 Pro 用 HarmonyOS 4.0.0）
- 多设备：一个 host 接多台手机时按 serial number 命名空间隔离（`acquire_android(device_serial="...")`）；单设备自动选默认
- scrcpy 视频流的 SSE 兼容性（可能不直接 stream，转 frame snapshot）
- 多桥共存：host 同时跑 winpc-gui (8766) + android (8768) 时的资源 / 日志隔离

## 当前结构

```
platforms/android/
├── README.md                       # 本文件
├── server/                         # （空）将来放 android_mcp.py + 依赖
├── scripts/                        # （空）将来放 setup-android.sh
├── skills/using-android/           # （空）将来放 SKILL.md
└── examples/                       # （空）将来放 claude-settings.json
```

## 启动开发

按 [`docs/install-pattern.md` § 5（添加新平台·范式）](../../docs/install-pattern.md#5-添加新平台--范式) 八步走起。从 macOS 平台 port，把 pyautogui / ImageGrab 替换成 uiautomator2 + scrcpy。

设备端：

- 主开发机一台 Linux/Mac（host）
- 一台真机（推荐华为 P30 Pro HarmonyOS 4.0.0 做兼容性 baseline）
- 备用模拟器一份（Android Studio AVD 或 genymotion）

## License

Apache 2.0 — 见 [`../../LICENSE`](../../LICENSE)。
