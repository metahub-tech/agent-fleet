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

按角色查阅对应文档：

| 你是 | 看哪个 |
|---|---|
| **Windows 测试主机管理员** | [`docs/platforms/windows.md`](docs/platforms/windows.md) |
| **Agent 操作员**（Linux/Mac/Win，跑 Claude Code 等 MCP client） | [`docs/agent-host-setup.md`](docs/agent-host-setup.md) |

典型流程：

1. **设备管理员** 按 [windows.md](docs/platforms/windows.md) 把 Windows 测试机配好（Tailscale + 一行 PowerShell 跑安装脚本）
2. 设备管理员把自己的 Tailscale 主机名告诉 Agent 操作员
3. **Agent 操作员** 按 [agent-host-setup.md](docs/agent-host-setup.md) 在自己的 MCP client 里加这台设备

如果两个角色都是同一个人（最常见），按上面顺序自己走两遍即可。

## English Quick Start

The authoritative documentation is currently in Chinese; full English docs ship with the v1.0 milestone. Two pages cover the entire setup:

- Device admin: [`docs/platforms/windows.md`](docs/platforms/windows.md)
- Agent admin: [`docs/agent-host-setup.md`](docs/agent-host-setup.md)

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
