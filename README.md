# agent-test-bench

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-private%20alpha-orange.svg)](docs/roadmap.md)

> **A fleet of test devices that LLM agents can drive through MCP.**
> 让 Claude 等大模型 Agent 通过 MCP 直接驱动 Windows / macOS / Android / iOS 设备做测试与调试。

## 是什么

把一台开发机外的**真实设备**（Windows PC、Mac、Android 手机、iPhone）接进 LLM Agent 的工具链，让 Agent 像调用本地命令那样驱动这些设备：截屏、点按钮、跑测试、读日志、调试 GUI。

这是给 **agent-driven 软件测试与跨平台验证** 准备的基础设施。

```
┌─────────────────┐                              ┌──────────────┐
│  Agent (Linux)  │ ──── Tailscale Mesh ─────>  │ Windows PC   │
│  Claude Code /  │                              │ (8766 MCP)   │
│  Cursor / Cline │                              ├──────────────┤
│                 │                              │ macOS box    │ (planned)
│   MCP client    │                              ├──────────────┤
└─────────────────┘                              │ Android phone│ (planned)
                                                 ├──────────────┤
                                                 │ iPhone       │ (planned)
                                                 └──────────────┘
```

## 当前状态

| Platform | Version | Status |
|---|---|---|
| Windows 10/11 | `0.1.0` | ✅ Released (this repo) |
| macOS | `0.2.0` | 📋 Planned |
| Android | `0.3.0` | 📋 Planned |
| iOS | `0.4.0` | 📋 Planned |
| Cross-device coord | `0.5.0` | 🔭 Future |
| Public OSS release | `1.0.0` | 🔭 Future |

详见 [`docs/roadmap.md`](docs/roadmap.md)。

## 快速开始

### 中文（推荐路径）

完整手册：[`docs/platforms/windows.md`](docs/platforms/windows.md)（~500 行，14 个章节，含一键安装脚本与故障排查清单）

三步走：

1. **网络层**：Linux 与 Windows 各装 Tailscale，加入同一 tailnet
2. **设备主机**：Windows 上跑 [`platforms/windows/scripts/setup-windows.ps1`](platforms/windows/scripts/setup-windows.ps1) 一键完成 OpenSSH + Node.js + Python venv + Task Scheduler 自启
3. **Agent 端**：把 [`platforms/windows/examples/claude-settings.json`](platforms/windows/examples/claude-settings.json) 合并进 `~/.claude/settings.json`，重启 Claude Code

### English (Quick Start)

```bash
# Linux side
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_winpc -N ""
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
```

```powershell
# Windows side (Admin PowerShell)
winget install --id Tailscale.Tailscale -e
# Login to Tailscale via tray, then:
.\platforms\windows\scripts\setup-windows.ps1
```

```jsonc
// ~/.claude/settings.json on Linux
{
  "mcpServers": {
    "winpc-shell": { "type": "sse", "url": "http://<WIN_HOSTNAME>:8765/sse" },
    "winpc-gui":   { "type": "sse", "url": "http://<WIN_HOSTNAME>:8766/sse" }
  }
}
```

Full English documentation is part of the v1.0 milestone. Until then the authoritative guide is in Chinese under `docs/`.

## 架构

每个平台桥都是同样的三段式：

```
[Agent Host] ── Tailscale ──> [Device Host] ── Native Drivers ──> [Device / App]
                  cross-LAN     MCP server         pywinauto / AppleScript / adb / xcrun
```

工具接口在所有平台保持语义一致（`take_screenshot` / `click` / `launch_app` / ...），切换设备只需在 settings.json 里换 URL。

详见 [`docs/architecture.md`](docs/architecture.md)。

## 目录布局

```
agent-test-bench/
├── docs/                          # 通用文档
│   ├── architecture.md            # 通用桥架构
│   ├── roadmap.md                 # 平台路线图
│   └── platforms/<name>.md        # 各平台详细手册
├── platforms/                     # 每平台一舱，自包含
│   └── windows/
│       ├── server/                # MCP server 源码 + 依赖
│       ├── scripts/               # 安装脚本
│       └── examples/              # 参考配置
└── examples/                      # 跨平台示例
    └── multi-platform-claude-settings.json
```

新增平台 → 在 `platforms/<name>/` 下落入同样的子结构。

## License

[Apache 2.0](LICENSE)

## Contributing

私有阶段不开放外部贡献。开源后流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
