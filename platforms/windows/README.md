# Windows Platform Bridge

Windows 10/11 device-host bridge for `agent-test-bench`. Enables LLM agents to drive a Windows PC for CLI/GUI test automation over Tailscale + MCP.

## Quick Start

完整手册：[`../../docs/platforms/windows.md`](../../docs/platforms/windows.md)。

TL;DR（Windows 管理员 PowerShell）：

```powershell
winget install --id Tailscale.Tailscale -e
# 任务栏托盘登录 Tailscale

# 拿代码（浏览器下载 ZIP 解压到 C:\agent-test-bench；或 git clone）
cd C:\agent-test-bench

# 跑安装
powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\setup-windows.ps1
```

Agent 端配置见 [`../../docs/agent-host-setup.md`](../../docs/agent-host-setup.md)。

## 暴露的工具

`win-device` MCP server（FastMCP，原生多客户端）通过 SSE 监听 `0.0.0.0:8766`：

| 类别 | 工具 |
|---|---|
| **使用状态** | `acquire_winpc`, `release_winpc`, `get_winpc_status` |
| 屏幕 | `get_screen_size`, `take_screenshot` |
| 窗口 | `list_windows`, `inspect_window`, `focus_window` |
| 鼠标 | `click`, `move_mouse` |
| 键盘 | `type_text`, `paste_text`, `press_key` |
| 进程（一次性） | `launch_app`, `kill_process`, `list_processes` |
| 长时进程 | `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions` |
| 文件系统 | `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info` |
| 文件搜索 | `start_search`, `get_more_search_results`, `list_searches`, `stop_search` |
| Shell | `run_powershell` |

> **v0.2 历史变更**：旧版还有一个独立的 `winpc-shell` MCP（mcp-proxy + npm desktop-commander，端口 8765），由于 single-client 限制 + npm 依赖问题在 v0.2.0 全部并入 `win-device`。`setup-windows.ps1` 会自动清理老版本残留。

## 目录布局

```
platforms/windows/
├── README.md                     # 本文件
├── server/                       # MCP server 源码 + 依赖
│   ├── windows_gui_mcp.py
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
| Python 3.10+ | ✅ | 跑 windows_gui_mcp.py | setup-windows.ps1 自动装（如缺） |
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

本平台桥实现了 [`docs/architecture.md`](../../docs/architecture.md) 定义的 Universal Tool Set 全部工具。`run_powershell` 是平台扩展（同时也是 `run_shell` 的 PowerShell 实现）。

## License

Apache 2.0 — 见仓库根的 [`LICENSE`](../../LICENSE)。
