# Agent Host Setup Guide

> 配置你的 Agent 主机（Linux / macOS / Windows / 任何能跑 MCP client 的环境）通过 MCP 调用一台或多台远程测试设备。
>
> 本指南假设你已经按对应的 [`platforms/<name>.md`](platforms/) 配好至少一台设备主机，并从设备管理员那里拿到了它的 Tailscale 主机名。

## 0. 前置条件

- 一个 [Tailscale](https://tailscale.com) 账户（与设备主机同一 tailnet）
- 你的 MCP client：Claude Code / Cursor / Cline / 其他兼容 MCP 的 LLM 客户端
- 设备主机的 Tailscale 主机名（如 `windows-test-1`）

## 1. 加入 Tailscale

**Linux**:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**macOS**:
```bash
brew install --cask tailscale
# 然后打开 Tailscale.app 登录
```

**Windows**:
```powershell
winget install --id Tailscale.Tailscale -e
# 然后任务栏托盘 -> Login
```

确认与设备主机连通：

```bash
tailscale ping <DEVICE_HOSTNAME>
```

几次内出现 `via direct` 或 `via DERP` 即通。

## 2. 配置 MCP Client

### Claude Code 单设备示例

编辑 `~/.claude.json`（顶级单文件，**不是** `~/.claude/settings.json`），把 `mcpServers` 段合并进去：

```json
{
  "mcpServers": {
    "win-device": {
      "type": "http",
      "url": "http://<WIN_HOSTNAME>:8766/mcp"
    }
  }
}
```

> **历史变更（v0.6.0）**：之前用 SSE（`"type": "sse"` + `/sse`），但长任务（>60s）会让 SSE 心跳超时被 Tailscale DERP / NAT 中转切断，client 留旧 session_id，server 不认 → `-32602` 至 `/exit` 重启。已迁到 streamable-http (`"type": "http"` + `/mcp`)，per-request 自动重连，问题根除。如果你的 `~/.claude.json` 仍是 `sse`/`/sse`，跑 `install-agent-side.py` 自动覆写。

把 `<WIN_HOSTNAME>` 替换为设备管理员告诉你的 Tailscale 主机名。

> 也可以从 [`../platforms/windows/examples/claude-settings.json`](../platforms/windows/examples/claude-settings.json) 直接复制片段。
>
> **v0.2 历史变更**：旧版还有 `winpc-shell`（端口 8765），现已合并到 `win-device`。如果 `~/.claude.json` 里还有 `winpc-shell` 条目，删掉它即可。

### 多设备

参考 [`../examples/multi-platform-claude-settings.json`](../examples/multi-platform-claude-settings.json)。把多个设备桥的 `mcpServers` 条目都列进去，命名建议 `<role>-<service>` 形式（例：`win-device` / `mac-device` / `android-test1`）。

### 其他 MCP client

`url` 与 `type=http (streamable-http)` 的概念其他 MCP client 也用，差异在配置文件位置：

| Client | 配置文件 | 字段名 |
|---|---|---|
| Claude Code（用户级） | `~/.claude.json` | `mcpServers` |
| Claude Code（项目级） | `<repo>/.mcp.json` | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` |
| Cline (VS Code) | VS Code Extension settings | `cline.mcpServers` |

> ⚠️ **`~/.claude.json` 不等同于 `~/.claude/settings.json`**——前者是 Claude Code 主状态文件（顶级单文件），MCP 配置只在这里生效；后者是 Claude Code 的偏好/权限/插件设置，MCP 段在这里会被静默忽略。

具体语法以各 client 官方文档为准。

## 3. 验证

### 3.1 重启 client

让 MCP client 重新加载配置。Claude Code 中：退出后重开 / 或运行 `/mcp` 查看当前状态。

### 3.2 看连接状态

Claude Code 中运行 `/mcp`，应看到：

```
win-device  [http]  connected
```

### 3.3 多 Agent 协作（v0.2+）

如果团队里多个 agent 共用同一台设备，**先 acquire 再用**：

```
# Windows
> 帮我 acquire winpc 用 holder_name="agent-A"
> （干活...）
> 用完了，release winpc holder_name="agent-A"

# macOS
> 帮我 acquire mac 用 holder_name="agent-A"
> （干活...）
> release mac holder_name="agent-A"
```

每平台有自己的状态工具：

| 平台 | acquire | release | status |
|---|---|---|---|
| Windows v0.2+ | `acquire_winpc` | `release_winpc` | `get_winpc_status` |
| macOS v0.3+ | `acquire_mac` | `release_mac` | `get_mac_status` |

10 分钟无活动会自动 release。详见各平台 setup 文档的状态管理章节。

### 3.4 一行命令装 MCP + skill

如果你嫌手动改 `~/.claude.json` + 拉 skill 软链麻烦，仓库提供：

```bash
python3 scripts/install-agent-side.py --platform mac-device --hostname <DEVICE_HOSTNAME>
# 也支持 --platform win-device
```

会自动备份 `~/.claude.json` → 把 mcpServers 条目 merge 进去 → 把 `platforms/<name>/skills/using-<name>` 软链到 `~/.claude/skills/`。幂等，重复跑无害。详见 [`install-pattern.md`](install-pattern.md)。

### 3.5 调一个工具

让 Agent 跑：

> 用 win-device 截一下当前 Windows 屏幕

应能看到截图返回。再试：

> 用 win-device 跑 `Get-Date` 看一下 Windows 当前时间

应能看到 PowerShell 输出。

## 4. 排错

### 4.1 `/mcp` 显示 `failed` 或 `disconnected`

按从下往上排查：

```bash
# 1. URL 协议是 http:// 不是 https://
grep -A 2 "mcpServers" ~/.claude.json

# 2. 主机名能解析
tailscale status | grep <WIN_HOSTNAME>
ping <WIN_HOSTNAME>

# 3. 端口可达（streamable-http 端点）
curl -sI http://<WIN_HOSTNAME>:8766/mcp --max-time 5

# 都通了还失败 -> 重启 Claude Code
```

### 4.2 主机名不解析

Tailscale MagicDNS 可能未开启。两种应对：

```bash
# A. 用 IP（IP 总是有效，主机名可能因 MagicDNS 关闭失效）
tailscale status        # 找设备主机的 100.x.x.x IP
# 然后把 ~/.claude.json 里的主机名换成 IP

# B. 启用 MagicDNS
# 浏览器打开 https://login.tailscale.com/admin/dns
# 勾选 "Enable MagicDNS"
```

### 4.3 工具调用超时 / 没响应

设备主机端的 MCP 服务可能没起。让设备管理员（或自己在设备主机上）检查：

```powershell
# Windows 端
Get-NetTCPConnection -LocalPort 8766 -State Listen
Get-ScheduledTaskInfo -TaskName MCP-WinDevice
```

详见对应平台的 setup guide § 7（排错段）。

### 4.4 截图返回空白 / GUI 操作无效

通常是 Windows 端没有用户处于登录会话。GUI MCP 必须有活动桌面才能工作。让设备管理员配置自动登录，见 [`platforms/windows.md` § 5](platforms/windows.md)。

---

## 5. 进阶

### 5.1 一份 settings 同时挂多个设备

从 v0.5.0 开始，cross-device 协调会成为一等特性。当前阶段就可以这样写：

```json
{
  "mcpServers": {
    "win-device":   { "type": "http", "url": "http://win-test:8766/mcp" },
    "mac-device":  { "type": "http", "url": "http://mac-test:8767/mcp" },
    "android-device": { "type": "http", "url": "http://win-test:8768/mcp" }
  }
}
```

Agent 通过 server 名（`win-device` / `mac-device` / `android`）选择设备。

### 5.2 限定哪些 Agent 主机能连设备

在 [Tailscale Admin Console](https://login.tailscale.com/admin/acls) 配 ACL：

```hujson
{
  "acls": [
    {
      "action": "accept",
      "src":    ["tag:agent-host"],
      "dst":    ["tag:test-device:8766,8767,8768,8769"]
    }
  ]
}
```

把 Agent 主机标 `tag:agent-host`，设备主机标 `tag:test-device`，其他成员就连不到 MCP 端口。
