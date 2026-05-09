# Android Platform Bridge — v0.4 (Planned)

> 🚧 **状态：未实现**。这个目录目前是骨架占位，对应 [roadmap.md v0.4.0](../../docs/roadmap.md#v040--android)。文件结构和 windows / macos 平台严格对称，等真实实现填进来。

Android 测试设备桥，让 LLM agent 通过 ADB + uiautomator2 + scrcpy 驱动一台 Android 手机或模拟器。

## 计划架构

```
[Agent (Linux/Mac)] ──Tailscale──> [Device Host (Linux/Mac)] ──USB/wifi adb──> [Android Device]
                                       MCP server :8768                            (P30 Pro / Pixel / 模拟器)
```

**设备主机不必是 Android 设备本身**——Android 不能跑 Python MCP server，所以 host 是普通 Linux/Mac，通过 ADB 桥到一台或多台真实手机。

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

- 国内厂商定制 ROM 的 USB 调试授权（华为 / 小米 / OPPO / vivo）行为差异
- HarmonyOS 4.0+ 与原生 AOSP 的 ADB 兼容性（首批测试机 P30 Pro 用 HarmonyOS 4.0.0）
- 多设备：一个 host 接多台手机时按 serial number 命名空间隔离（`acquire_android(device_serial="...")`）
- scrcpy 视频流的 SSE 兼容性（可能不直接 stream，转 frame snapshot）
- USB 唤醒 / wifi adb 切换 (`adb tcpip 5555`) 自动化

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
