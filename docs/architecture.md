# Architecture

## Vision

`agent-fleet` 是一支被 LLM Agent 通过 MCP 直接驱动的**测试设备舰队**。Agent 坐在开发机上，可以像调用本地命令一样，操控 Windows PC、Mac、Android 手机、iOS 设备执行：

- 跑测试用例并读取结果
- 调试桌面/移动端 GUI
- 验证跨平台行为差异
- 自动化软件质量工作流

## 通用三段式架构

每个平台桥都是同样的三段式：

```
[Agent Host (Linux/Mac/anywhere)]  ── Tailscale ──>  [Device Host]  ── Native Drivers ──>  [Device / App]
            MCP Client                                MCP Server                            GUI / CLI / USB / ADB
```

### Segment 1 — 网络层：Tailscale

- 跨局域网、自动 NAT 穿透、MagicDNS 主机名
- 每台设备主机加入同一 tailnet
- Tailscale ACL 限定 Agent 主机才能访问设备主机

### Segment 2 — MCP Server（每台设备主机一个）

- 通过 SSE / Streamable-HTTP 暴露稳定的工具集
- 监听 `0.0.0.0:<platform_port>`；防火墙限制只有 Tailscale 接口可达
- 用户登录时自启（Task Scheduler / launchd / systemd）

### Segment 3 — 原生驱动（每平台不同）

| 平台 | 设备主机 OS | 驱动栈 | 端口预留 |
|---|---|---|---|
| Windows | Windows 10/11 | pywinauto + pyautogui + PowerShell | 8766 |
| macOS | macOS 12+ | AppleScript + pyobjc + Accessibility API | 8767 |
| Android | 任意（推荐 Linux/Mac） | adb + uiautomator2 + scrcpy | 8768 |
| iOS | macOS（强制） | xcrun simctl + WebDriverAgent + idb | 8769 |

端口预留按平台递增，避免一台主机同时跑多个桥时冲突（如 Mac 上同时跑 macOS 桥和 iOS 桥）。

另：`8765` 是 desktop-commander（社区通用 shell/file MCP）的端口，所有平台都可复用。

## 工具公约 (Universal Tool Set)

每个平台桥**必须实现下面的通用工具集**，工具名与语义保持一致。这样 Agent 切换设备时几乎不用换思维方式——只在 settings.json 里换 server URL。

### Universal Tools

| 类别 | 工具 | 语义 |
|---|---|---|
| 屏幕 | `get_screen_size()` | 返回 `{width, height}` |
| 屏幕 | `take_screenshot(region?)` | 返回 PNG bytes |
| 窗口 | `list_windows()` | 列可见顶层窗口 |
| 窗口 | `inspect_window(title_substring, max_depth?)` | 返回窗口的 UI 树 |
| 窗口 | `focus_window(title_substring)` | 把窗口拉到前台 |
| 鼠标 | `click(x, y, button?, clicks?)` | 屏幕坐标点击 |
| 鼠标 | `move_mouse(x, y, duration?)` | 移动指针 |
| 键盘 | `type_text(text, interval?)` | 键入 ASCII 文本 |
| 键盘 | `paste_text(text)` | 通过剪贴板贴入文本（支持 Unicode） |
| 键盘 | `press_key(keys)` | 单键或组合键（`enter` / `cmd+s`） |
| 进程 | `launch_app(path, args?)` | 启动应用，返回 PID |
| 进程 | `kill_process(pid)` | 根据 PID 杀进程 |
| 进程 | `list_processes(name_filter?)` | 列运行中进程 |
| Shell | `run_shell(script, timeout?)` | 执行平台原生 shell |

实现新平台桥时如果某个工具语义无法对应（例如 iOS 没有传统"窗口"概念），优先做语义映射（窗口 ≈ App + Scene），实在不能映射的工具留 stub 抛 `NotImplementedError`，并在该平台 README 里登记不支持。

### 平台扩展

| 平台 | 额外工具 |
|---|---|
| Windows | `run_powershell`（`run_shell` 的 PowerShell 别名） |
| macOS | `run_applescript`, `osascript_window_action` |
| Android | `adb_command`, `install_apk`, `dump_uiautomator_xml` |
| iOS | `xcrun_simctl`, `wda_action`, `boot_simulator` |

扩展工具名必须与 Universal Tool Set 不冲突。建议用 `<platform>_<verb>` 前缀避免歧义。

## 为什么是 Tailscale + MCP

| 需求 | 解决方案 |
|---|---|
| 跨局域网访问且不暴露公网端口 | Tailscale (WireGuard mesh) |
| 不维护 DNS 也能拿稳定主机名 | Tailscale MagicDNS |
| 细粒度访问控制（哪台设备能被谁连） | Tailscale ACL |
| LLM Agent 调用结构化工具 | MCP (SSE / streamable-HTTP) |
| 长连接、热加载工具列表 | MCP server 长驻进程 |

成本：Tailscale 免费档（100 设备以内）足够个人和中小团队使用。Linux/Mac/Windows 行为一致。

## 仓库布局

```
agent-fleet/
├── docs/                          # 跨平台文档
│   ├── architecture.md            # 本文件
│   ├── roadmap.md                 # 平台交付计划
│   └── platforms/                 # 各平台 setup guide
│       ├── windows.md
│       ├── macos.md
│       └── android.md
├── platforms/                     # 每平台一舱，自包含
│   ├── windows/
│   │   ├── README.md              # 平台快速上手
│   │   ├── server/                # MCP server 源码 + 依赖
│   │   ├── scripts/               # 安装脚本
│   │   └── examples/              # 参考配置
│   ├── macos/                     # 同样子结构
│   └── android/                   # 同样子结构
└── examples/                      # 跨平台示例
    └── multi-platform-claude-settings.json
```

加新平台时按 `platforms/<name>/` 目录树落入即可。

## 安全模型

按信任递减排列：

1. **Tailscale ACL** —— 只有 Agent 主机能连到设备主机（按 IP / tag 锁定）
2. **OS 防火墙** —— MCP 端口只允许 Tailscale 接口（Windows 上限定 `Tailscale` 网卡，macOS 上限定 `utun*`）
3. **MCP server bind** —— 设备本地 `0.0.0.0`，被防火墙限制范围
4. **Auth (规划中)** —— 每设备独立 bearer token；当前未实现，依赖 1–3 层

私有网络内此模型够用。公网部署需要额外的：
- 每调用鉴权
- 速率限制
- 审计日志

这些在 [`roadmap.md`](roadmap.md) v1.0.0 里跟进。
