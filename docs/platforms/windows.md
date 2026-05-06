# Windows Platform Setup Guide

> 把一台 Windows 10/11 配置为 agent-test-bench 测试主机。整个过程通常 < 15 分钟，绝大部分由 `setup-windows.ps1` 自动化。
>
> 本指南只面向 **Windows 主机的本地管理员**。Agent 端（你的 Linux/Mac 开发机或 Claude Code 所在主机）的配置见 [`../agent-host-setup.md`](../agent-host-setup.md)。

## 0. 前置条件

- Windows 10 或 11
- 一个具有管理员权限的 Windows 账户
- 一个 [Tailscale](https://tailscale.com) 账户（免费档够用）
- 互联网连接

## 1. 安装 Tailscale 并登录

任意 PowerShell 窗口（管理员可选）：

```powershell
winget install --id Tailscale.Tailscale -e
```

装完打开任务栏托盘的 Tailscale 图标 → **Login** → 用与 Agent 主机相同的账号登录。

```powershell
tailscale status
```

看到本机和 Agent 主机都在列表里就 OK。

## 2. 拿到本项目代码

### 选项 A · 浏览器下载 ZIP（最简单，不需要装 Git）

1. 浏览器打开 https://github.com/metahub-tech/agent-test-bench
2. 点绿色 `Code` 按钮 → `Download ZIP`
3. 解压到 `C:\agent-test-bench`（路径任选，避免空格）

### 选项 B · git clone

如果你已经装了 [Git for Windows](https://git-scm.com/) 或 [GitHub CLI](https://cli.github.com/)：

```powershell
# 公开版本（v1.0+）
git clone https://github.com/metahub-tech/agent-test-bench.git C:\agent-test-bench

# 当前私有阶段：用 GitHub CLI 鉴权
gh auth login
gh repo clone metahub-tech/agent-test-bench C:\agent-test-bench
```

## 3. 跑安装脚本

**以管理员身份打开 PowerShell**，进入仓库目录：

```powershell
cd C:\agent-test-bench
powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\setup-windows.ps1
```

脚本依次做 6 件事，每步打印进度：

| 步骤 | 内容 |
|---|---|
| 1/6 | 检查 Tailscale 已登录 |
| 2/6 | 装 Python 3.12（若未装或版本 < 3.10） |
| 3/6 | 装 Node.js LTS（若未装） |
| 4/6 | 在 `platforms\windows\server\.venv` 建虚拟环境，装依赖 |
| 5/6 | 防火墙：8765 / 8766 仅 Tailscale 接口入站允许 |
| 6/6 | 注册 Task Scheduler 任务（登录时自启），立刻启动并自检端口 |

**首次运行**最后一步会停在等待端口阶段最长 60 秒——`npx` 第一次跑要下载 supergateway 和 desktop-commander。

脚本结束时会打印你的 **Tailscale 主机名** 和 **MCP URL**，把这两条信息发给 Agent 操作员（或自己留着）。

> **脚本可重复运行**：如果第一次有问题（比如 Tailscale 没登录），修复后直接再跑一次即可，不会破坏已有配置。

## 4. 验证

脚本最后已经自检过端口监听。手动复查：

```powershell
# 任务运行状态
Get-ScheduledTaskInfo -TaskName MCP-DesktopCommander
Get-ScheduledTaskInfo -TaskName MCP-WindowsGui

# 端口监听
Get-NetTCPConnection -LocalPort 8765,8766 -State Listen
```

## 5. 自动登录（GUI 测试必需）

GUI MCP 服务靠 Task Scheduler 在 **用户登录时** 启动。Windows 重启后必须有用户处于登录状态，否则 GUI 服务不会运行。

```powershell
netplwiz
```

弹窗里：

1. 取消勾选 **"要使用本计算机，用户必须输入用户名和密码"**
2. 确定
3. 输入两次当前用户的密码

> 仅推荐用于专用测试机；不要在共用电脑上启用。

## 6. 卸载

```powershell
# 取消任务
Unregister-ScheduledTask -TaskName MCP-DesktopCommander -Confirm:$false
Unregister-ScheduledTask -TaskName MCP-WindowsGui        -Confirm:$false

# 删防火墙规则
Get-NetFirewallRule -DisplayName "MCP *" | Remove-NetFirewallRule

# 删 portproxy 转发
netsh interface portproxy delete v4tov6 listenport=8765 listenaddress=0.0.0.0

# 删仓库目录（venv、所有依赖一起删干净）
Remove-Item -Recurse -Force C:\agent-test-bench
```

---

## 7. 排错

### 7.0 一键诊断（先跑这个）

```powershell
powershell -ExecutionPolicy Bypass -File .\platforms\windows\scripts\diagnose.ps1
```

打印 8 段（监听地址 / 进程 / localhost 自测 / Tailscale IP 自测 / 防火墙规则 / 网卡 / Tailscale 状态 / 任务最后一次运行结果）。把结果发给 Agent 操作员通常 1 分钟就能定位问题。

下面按问题类型对照修。

### 7.1 8765 / 8766 没在监听

```powershell
# 看任务最近一次执行结果
Get-ScheduledTaskInfo -TaskName MCP-WindowsGui | Format-List

# 手动跑 GUI MCP 看实际错
$ServerDir = "C:\agent-test-bench\platforms\windows\server"
& "$ServerDir\.venv\Scripts\python.exe" "$ServerDir\windows_gui_mcp.py"
```

如果是 desktop-commander 没起：

```powershell
npx -y supergateway --stdio "npx -y @wonderwhy-er/desktop-commander" --port 8765 --baseUrl http://0.0.0.0:8765 --ssePath /sse --messagePath /message
```

### 7.2 高 DPI 屏点击坐标错位

如果 Agent 那边发现 `click(x, y)` 点的位置和 `take_screenshot` 看到的不一致，要么把 Windows 显示缩放设回 100%（设置 → 系统 → 显示），要么在 `windows_gui_mcp.py` 顶部 import 后加：

```python
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    pass
```

改完重启 Task：

```powershell
Stop-ScheduledTask  -TaskName MCP-WindowsGui
Start-ScheduledTask -TaskName MCP-WindowsGui
```

### 7.3 Windows 重启后 GUI 服务不启

`Get-ScheduledTaskInfo MCP-WindowsGui` 显示从未运行 → 没人登录到桌面。Task Scheduler 的 `AtLogOn` 触发器需要实际用户会话。配置自动登录见 § 5。

### 7.4 Tailscale ACL 加固

默认 tailnet 内全互通。如果你的 tailnet 还有其他人，建议在 [Tailscale Admin Console](https://login.tailscale.com/admin/acls) 加规则，限定只有 Agent 主机能访问 8765 / 8766。

### 7.5 supergateway / desktop-commander 包名变更

Task 调用 `npx -y @wonderwhy-er/desktop-commander`。如该包改名，更新任务参数：

```powershell
# 看当前命令
Get-ScheduledTask -TaskName MCP-DesktopCommander | Select-Object -ExpandProperty Actions

# 重建（替换 <NEW_PACKAGE>）
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument '/c npx -y supergateway --stdio "npx -y <NEW_PACKAGE>" --port 8765 --baseUrl http://0.0.0.0:8765 --ssePath /sse --messagePath /message'
Set-ScheduledTask -TaskName MCP-DesktopCommander -Action $action
Stop-ScheduledTask  -TaskName MCP-DesktopCommander
Start-ScheduledTask -TaskName MCP-DesktopCommander
```

---

## 附录 · 工具列表

`windows-gui` MCP 暴露的工具（监听 `0.0.0.0:8766/sse`）：

| 类别 | 工具 |
|---|---|
| 屏幕 | `get_screen_size`, `take_screenshot` |
| 窗口 | `list_windows`, `inspect_window`, `focus_window` |
| 鼠标 | `click`, `move_mouse` |
| 键盘 | `type_text`, `paste_text`, `press_key` |
| 进程 | `launch_app`, `kill_process`, `list_processes` |
| Shell | `run_powershell` |

`desktop-commander` 是社区 MCP（端口 8765），提供 shell 命令执行、文件读写、目录搜索、grep、文件 diff、进程管理等。文档见 https://github.com/wonderwhy-er/DesktopCommanderMCP。
