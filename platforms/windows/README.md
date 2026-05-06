# Windows Platform Bridge

Windows 10/11 device-host bridge for `agent-test-bench`. Enables LLM agents to drive a Windows PC for CLI/GUI test automation over Tailscale + MCP.

## Quick Start

完整手册：[`../../docs/platforms/windows.md`](../../docs/platforms/windows.md)（~500 行，14 个章节）。

TL;DR：

1. **Linux 端**：`ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_winpc -N ""`
2. **两端**：装 Tailscale，加入同一 tailnet
3. **Windows 端**（管理员 PowerShell）：
   ```powershell
   # 把本目录拉到 C:\mcp-setup\，然后：
   powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
   ```
4. 把公钥写入 `C:\ProgramData\ssh\administrators_authorized_keys` 并锁权限
5. **Linux 端**：合并 [`examples/claude-settings.json`](examples/claude-settings.json) 进 `~/.claude/settings.json`

## 暴露的工具

`windows-gui` MCP server 通过 SSE 监听 `0.0.0.0:8766`：

| 类别 | 工具 |
|---|---|
| 屏幕 | `get_screen_size`, `take_screenshot` |
| 窗口 | `list_windows`, `inspect_window`, `focus_window` |
| 鼠标 | `click`, `move_mouse` |
| 键盘 | `type_text`, `paste_text`, `press_key` |
| 进程 | `launch_app`, `kill_process`, `list_processes` |
| Shell | `run_powershell` |

外加 `desktop-commander`（社区 MCP）通过 supergateway stdio→SSE 桥接，监听 `0.0.0.0:8765`，提供：shell 命令执行、文件读写、目录搜索、grep、文件 diff、进程管理等。

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

| 组件 | 必须 | 用途 |
|---|---|---|
| Tailscale | ✅ | 跨网组网 |
| OpenSSH Server (Windows feature) | ✅ | CLI 兜底通道 |
| Node.js LTS | ✅ | 跑 supergateway + desktop-commander |
| Python 3.10+ | ✅ | 跑 GUI MCP server |
| Administrator 活动会话 | ✅ | GUI 任务必须在用户会话中执行（推荐自动登录） |

## 故障排查

完整排错章节见 [`../../docs/platforms/windows.md` § 12](../../docs/platforms/windows.md)：

- 自动登录配置（GUI 任务必须有活动用户会话）
- 高 DPI 屏幕坐标错位
- 端口冲突 / 任务起不来
- supergateway / desktop-commander 包名变更
- Tailscale ACL 加固

## Universal Tool Set 兼容

本平台桥实现了 [`docs/architecture.md`](../../docs/architecture.md) 定义的 Universal Tool Set 全部工具。`run_powershell` 是平台扩展（同时也是 `run_shell` 的 PowerShell 实现）。

## License

Apache 2.0 — 见仓库根的 [`LICENSE`](../../LICENSE)。
