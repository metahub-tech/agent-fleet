# agent-fleet

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-v0.6.13--alpha-blue.svg)](https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.13-alpha)

> **Give your LLM agent its own fleet of physical devices.**
> 给 LLM agent 配一队真实硬件——Windows / macOS / Android（以后 iOS），通过 MCP 让 agent 像人一样操作它们。一行命令安装：
>
> ```bash
> uvx --from "git+https://github.com/metahub-tech/agent-fleet@v0.6.13-alpha#subdirectory=cli" agent-fleet setup
> ```

## 是什么

把一台开发机外的**真实设备**（Windows PC、Mac、Android 手机、iPhone）接进 LLM Agent 的工具链，让 Agent 像调用本地命令那样驱动这些设备：截屏、点按钮、跑测试、读日志、调试 GUI。

这是给 **agent-driven 软件测试与跨平台验证** 准备的基础设施。

```
┌─────────────────┐                              ┌──────────────┐
│  Agent (any OS) │ ──── Tailscale Mesh ─────>  │ Windows PC   │ win-device     :8766 ✅
│  Claude Code /  │                              ├──────────────┤
│  Cursor / Cline │                              │ macOS box    │ mac-device     :8767 ✅
│  / OpenClaw /   │                              ├──────────────┤
│  Antigravity /  │                              │ Android phone│ android-device :8768 ✅
│  Hermes / ...   │                              ├──────────────┤
└─────────────────┘                              │ iPhone       │ ios-device     :8769 (v0.7 planned)
                                                 └──────────────┘
            ↑                                                ↑
   uvx agent-fleet setup           generates 6 frameworks' configs
   一行命令装 client 端 + 装 server / 配 Tailscale / 引导权限 / 自检 / 生成 snippet
```

## 当前状态

| Component | Version | Status |
|---|---|---|
| Windows 10/11 bridge | `0.2.0` | ✅ Released (win-device consolidated, 33 tools, streamable-http) |
| macOS 12+ bridge | `0.3.0` | ✅ Released (mac-device, launchd, 31 tools, GUI-permission flow) |
| Android bridge | `0.4.0` | ✅ Released (android-device, 20 tools, USB + Wireless + Hybrid ADB, OEM variants) |
| agent-fleet CLI wizard | `0.5.0-alpha` | ✅ Released (`uvx agent-fleet setup` 一键安装；6 框架配置生成) |
| role rename → `<os>-device` + macOS permission primer | `0.6.0-alpha` | ✅ Released (mac-device/win-device/android-device；wizard 自动触发 TCC 对话框) |
| UI element introspection (Android uiautomator + macOS AX) | `0.6.1-alpha` | ✅ Released (mac-device +3 tools, android-device +3 tools；find/tap/click by text/role/resource-id) |
| Post-install smoke tests + setup-prompt UX | `0.6.2-alpha` | ✅ Released (wizard auto-calls 4–5 tools per role after install; pass/fail table) |
| Smoke-runner bugfix + Android setup docs | `0.6.3-alpha` | ✅ Released (smoke now actually runs; OEM Android dev-mode guidance moved to [`docs/android-setup.md`](docs/android-setup.md)) |
| Smoke connection fix (use 127.0.0.1, unwrap ExceptionGroup) | `0.6.4-alpha` | ✅ Released (smoke now connects via localhost not Tailscale MagicDNS; collapses repeated connection failures into one row) |
| UI introspection bugfixes (AXValueGetValue + adb capture_bytes) | `0.6.5-alpha` | ✅ Released (Mac AX returns position/size/center; Android dump_ui_hierarchy returns XML) |
| macOS legacy-plist migration cleanup | `0.6.6-alpha` | ✅ Released (setup auto-cleans pre-v0.6.0 plists + orphan procs) |
| Windows GBK subprocess decode crash fix | `0.6.7-alpha` | ✅ Released (UTF-8 + errors=replace on subprocess) |
| install.sh/.ps1: uvx local path | `0.6.8-alpha` | ✅ Released (skip uv's libgit2 bug) |
| Windows: UTF-8 PS console + firewall try-catch | `0.6.9-alpha` | ✅ Released (UTF-8 PS output + firewall graceful skip) |
| Windows: require admin upfront (v0.6.9 was wrong about non-admin) | `0.6.10-alpha` | ✅ Released (install.ps1 admin check; Register/Unregister try-catch so silent echoes can't mask failures) |
| Internal file rename: `{windows,macos}_gui_mcp.py` → `*_device_mcp.py` + log filenames | `0.6.11-alpha` | ✅ Released (naming consistency w/ the v0.6.0 role-ID rename; setup auto-kills orphans from old names) |
| `interact_with_process` friendly error on dead child + legacy `agent-test-bench` → `agent-fleet` rename finished | `0.6.12-alpha` | ✅ Released (poll() check instead of `.closed`; rename completed across code/scripts/skills/pyproject; platform-doc TL;DRs now point at one-shot installer) |
| **Setup scripts report MagicDNS name, not OS computer name** | **`0.6.13-alpha`** | ✅ **Released** (5 setup scripts derived hostname from `Self.HostName` = OS computer name, stale after an admin-console device rename; now use the first label of `Self.DNSName`) |
| iOS bridge | `0.7.0` | 📋 Planned (macOS host + WebDriverAgent) |
| Cross-device coordination | `0.8.0` | 🔭 Future |
| Public stable release | `1.0.0` | 🔭 Future (after community feedback on alpha) |

详见 [`docs/roadmap.md`](docs/roadmap.md)。

## 快速开始

**新手 / 一键流**：在被控设备（PC / 接了手机的 PC）上：

```bash
# macOS / Linux  —  NOT `curl ... | bash`!  The wizard is interactive and bash
# piped from curl uses stdin for the script itself, so questionary's prompts
# die with EOFError.  The `bash -c "$(...)"` form puts the script in argv and
# leaves stdin = terminal.
bash -c "$(curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh)"

# Windows  —  `irm | iex` is fine on PowerShell because iex runs the script in
# the current session and Read-Host reads from the console host, not stdin.
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"
```

或，如果已经有 uv（v0.6.13-alpha 阶段从 git 拉，未上 PyPI）：

```bash
uvx --from "git+https://github.com/metahub-tech/agent-fleet@v0.6.13-alpha#subdirectory=cli" agent-fleet setup
```

> macOS 12 用户首次跑前需 `brew install coreutils`（uv 的 wrapper 用到 `realpath`，macOS 12 默认不带；见 [#2](https://github.com/metahub-tech/agent-fleet/issues/2)）。

wizard 会带你走完：选角色 → 装 MCP server → 配 Tailscale → GUI 权限 / ADB 授权交互式引导 → 自动健康检测 → 输出 6 个 agent 框架的配置片段。

**老手**：仍可直接调底层脚本——`docs/install-pattern.md` 仍有效（"高级用户手册"）。

| 你是 | 看哪个 |
|---|---|
| **新手**（让 wizard 带你走） | 跑上面那行命令，跟着提示选 |
| **设备管理员，要自己写脚本编排部署** | [`docs/install-pattern.md`](docs/install-pattern.md)（底层脚本契约）|
| **Agent 操作员** | wizard 输出的 snippet 直接 paste 到对应 agent 配置；也可参考 [`docs/agent-host-setup.md`](docs/agent-host-setup.md) |
| **设计文档**（贡献者） | [`docs/design/2026-05-11-agent-fleet-cli.md`](docs/design/2026-05-11-agent-fleet-cli.md) |

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

工具接口在所有平台保持语义一致（`take_screenshot` / `click` / `launch_app` / ...），切换设备只需在 `~/.claude.json` 里换 URL。

详见 [`docs/architecture.md`](docs/architecture.md)。

## 目录布局

```
agent-fleet/
├── docs/                          # 通用文档
│   ├── install-pattern.md         # 开发者基准：两个角色 / 两条安装路径 / 目录契约
│   ├── architecture.md            # 通用桥架构
│   ├── agent-host-setup.md        # Agent 端配置（~/.claude.json + skill 软链）
│   ├── roadmap.md                 # 平台路线图
│   └── platforms/<name>.md        # 各平台详细手册（设备端）
├── platforms/                     # 每平台一舱，自包含
│   ├── windows/
│   │   ├── README.md              # 速览
│   │   ├── server/                # MCP server 源码 + 依赖
│   │   ├── scripts/               # 安装 / 启动 / 排错脚本
│   │   ├── skills/using-win/    # 给 agent 用的 skill 文档
│   │   └── examples/              # claude-settings.json 片段
│   └── macos/                     # 同样子结构
├── scripts/                       # 仓库级脚本
│   └── install-agent-side.py      # 一行命令把 MCP + skill 装到 ~/.claude.json
├── examples/                      # 跨平台示例
│   └── multi-platform-claude-settings.json
└── CHANGELOG.md
```

新增平台 → 在 `platforms/<name>/` 下落入同样的子结构。范式见 [`docs/install-pattern.md` § 添加新平台](docs/install-pattern.md)。

## License

[Apache 2.0](LICENSE)

## Contributing

私有阶段不开放外部贡献。开源后流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
