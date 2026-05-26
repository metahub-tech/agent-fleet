# Windows Platform Bridge

Windows 10/11 device-host bridge for `agent-fleet`. Enables LLM agents to drive a Windows PC for CLI/GUI test automation over Tailscale + MCP.

## Quick Start

完整手册：[`../../docs/platforms/windows.md`](../../docs/platforms/windows.md)。

TL;DR（Windows 管理员 PowerShell）：

```powershell
winget install --id Tailscale.Tailscale -e
# 任务栏托盘登录 Tailscale

# 拿代码（浏览器下载 ZIP 解压到 C:\agent-fleet；或 git clone）
cd C:\agent-fleet

# 跑安装
powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\setup-windows.ps1
```

Agent 端配置见 [`../../docs/agent-host-setup.md`](../../docs/agent-host-setup.md)。

## Demo — example agent session

```text
You:   "Open Notepad, write the release note, and screenshot it."
Agent: launch_app(target="notepad")                   → started (pid 5012)
       type_text(text="agent-fleet v0.8.2-alpha ✅")   → typed
       take_screenshot()                              → 1920×1080 PNG returned to the agent
       list_windows()                                 → ["Untitled - Notepad", ...]
```

The agent drives the real Windows desktop over MCP — no human at the keyboard.
See the animated demo (a real iPad) in the [main README](../../README.md).

## 暴露的工具

`win-device` MCP server（FastMCP，原生多客户端）通过 streamable-http 监听 `0.0.0.0:8766/mcp`：

### core 工具（42 个）

| 类别 | 工具 |
|---|---|
| **使用状态** | `acquire`, `release`, `get_status` |
| 设备路由 | `list_devices`, `get_default_device`, `set_default_device` |
| 屏幕 | `get_screen_size`, `take_screenshot` |
| 窗口 / UI 内省 | `list_windows`, `focus_window`, `current_app`（当前前台应用）, `dump_ui`（前台窗口 UI 树）, `inspect_window`（更丰富的窗口内省，平台扩展） |
| 鼠标 | `tap`, `move_mouse`, `swipe` |
| 键盘 | `type_text`, `paste_text`, `press_key` |
| 元素操作 | `find_elements` / `tap_element`（按 query 语义找元素 / 点中心，canonical 跨平台） |
| 进程 / 应用（一次性） | `launch_app`, `terminate_app`（按应用标识终止）, `kill_process`（按 PID 终止，平台扩展）, `list_processes` |
| 长时进程 | `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions` |
| 文件系统 | `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info` |
| 文件搜索 | `start_search`, `get_more_search_results`, `list_searches`, `stop_search` |
| Shell | `run_shell`（底层 PowerShell） |

### 浏览器能力（可选）

除上面 42 个 core 工具外，win-device 运行时还由能力框架额外暴露 1 个发现工具 `list_capabilities`（all-platform always-on）+ 两个可选浏览器能力：`agent_browser`（嫁接 Playwright MCP，有头 Chrome / CDP，带自动化痕迹，27 个工具，依赖 Chrome + Node/npx，skill `using-fleet-browser`）与 `human_browser`（驱动真人日常 Chrome，零自动化痕迹，1 个工具 `human_browser_open`，依赖 Chrome，skill `using-human-browser`）。满配运行时共 **71 个工具**（42 + 1 + 27 + 1）。能力按"依赖齐全才暴露"渐进披露，调 `list_capabilities` 查本机实际可用的能力与工具。详见 [`../../docs/platforms/windows.md` 附录 B · 浏览器能力](../../docs/platforms/windows.md#附录-b--浏览器能力可选)。

> **v0.2 历史变更**：旧版还有一个独立的 `winpc-shell` MCP（mcp-proxy + npm desktop-commander，端口 8765），由于 single-client 限制 + npm 依赖问题在 v0.2.0 全部并入 `win-device`。`setup-windows.ps1` 会自动清理老版本残留。

## 目录布局

```
platforms/windows/
├── README.md                     # 本文件
├── server/                       # MCP server 源码 + 依赖
│   ├── win_device_mcp.py
│   ├── requirements.txt
│   └── pyproject.toml
├── scripts/                      # 一键安装
│   └── setup-windows.ps1
└── examples/                     # 参考配置
    └── claude-settings.json
```

## 运行依赖

| 组件 | 必须 | 用途 | 自动安装 |
|---|---|---|---|
| Tailscale | ✅ | 跨网组网 | 用户在第 1 步装 |
| Python 3.10+ | ✅ | 跑 win_device_mcp.py | setup-windows.ps1 自动装（如缺） |
| 用户活动登录会话 | ✅ | GUI 任务必须在用户桌面会话中执行 | 启用自动登录（手册 § 5） |

> v0.2 之后**不再需要 Node.js / npm**——所有工具都用 Python 实现。

## 故障排查

完整排错章节见 [`../../docs/platforms/windows.md` § 7](../../docs/platforms/windows.md#7-排错)：

- 端口未监听 / 任务起不来
- 高 DPI 屏幕坐标错位
- Windows 重启后 GUI 服务不启
- Tailscale ACL 加固
- 旧版 desktop-commander/mcp-proxy 残留清理（diagnose.ps1 § 0a 自动检测）

## Universal Tool Set 兼容

本平台桥实现了 [`docs/architecture.md`](../../docs/architecture.md) 定义的 Universal Tool Set 全部工具。`run_shell` 在 Windows 上的底层实现是 PowerShell。

## License

Apache 2.0 — 见仓库根的 [`LICENSE`](../../LICENSE)。
