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

脚本依次做 5 件事（外加 0/5 自动清理 v0.1 旧版残留），每步打印进度：

| 步骤 | 内容 |
|---|---|
| 0/5 | 自动清理 v0.1 残留（旧 task `MCP-DesktopCommander` / 旧防火墙规则 / npm 全局 `desktop-commander` / portproxy 项） |
| 1/5 | 检查 Tailscale 已登录 |
| 2/5 | 装 Python 3.12（若未装或版本 < 3.10） |
| 3/5 | 在 `platforms\windows\server\.venv` 建虚拟环境，装依赖 |
| 4/5 | 防火墙：8766 仅 Tailscale IP 段（100.64.0.0/10 + fd7a:115c:a1e0::/48）入站允许 |
| 5/5 | 注册 Task Scheduler 任务 `MCP-WinDevice`（登录时自启），立刻启动并自检端口 |

脚本结束时会打印你的 **Tailscale 主机名** 和 **win-device 的 SSE URL**，把这两条信息发给 Agent 操作员（或自己留着）。

> v0.1 还有第二个服务 `MCP-DesktopCommander`（端口 8765，npm + mcp-proxy 栈），v0.2 起合并进 win-device。setup 脚本会把老版本残留全部清理掉。

> **脚本可重复运行**：如果第一次有问题（比如 Tailscale 没登录），修复后直接再跑一次即可，不会破坏已有配置。

## 4. 验证

脚本最后已经自检过端口监听。手动复查：

```powershell
# 任务运行状态
Get-ScheduledTaskInfo -TaskName MCP-WinDevice

# 端口监听
Get-NetTCPConnection -LocalPort 8766 -State Listen
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
Unregister-ScheduledTask -TaskName MCP-WinDevice -Confirm:$false
# 如果是 v0.1 升级来的，可能还有：
Unregister-ScheduledTask -TaskName MCP-DesktopCommander -Confirm:$false -ErrorAction SilentlyContinue

# 删防火墙规则
Get-NetFirewallRule -DisplayName "MCP *" | Remove-NetFirewallRule

# 删 v0.1 portproxy 残留（如果还在）
netsh interface portproxy delete v4tov6 listenport=8765 listenaddress=0.0.0.0 2>$null

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

### 7.1 8766 没在监听

```powershell
# 看任务最近一次执行结果
Get-ScheduledTaskInfo -TaskName MCP-WinDevice | Format-List

# 手动跑 win-device 看实际错
$ServerDir = "C:\agent-test-bench\platforms\windows\server"
& "$ServerDir\.venv\Scripts\python.exe" "$ServerDir\windows_gui_mcp.py"
```

主要会卡在 pip 装依赖（`pyautogui` / `pywinauto` / `fastmcp`）失败 → 看 venv 输出。

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
Stop-ScheduledTask  -TaskName MCP-WinDevice
Start-ScheduledTask -TaskName MCP-WinDevice
```

### 7.3 Windows 重启后 GUI 服务不启

`Get-ScheduledTaskInfo MCP-WinDevice` 显示从未运行 → 没人登录到桌面。Task Scheduler 的 `AtLogOn` 触发器需要实际用户会话。配置自动登录见 § 5。

### 7.4 Tailscale ACL 加固

默认 tailnet 内全互通。如果你的 tailnet 还有其他人，建议在 [Tailscale Admin Console](https://login.tailscale.com/admin/acls) 加规则，限定只有 Agent 主机能访问 8766。

### 7.5 多 Agent 协作下的"使用状态"管理

win-device 是 FastMCP 原生 SSE，**支持多客户端并发连接**——所以多个 agent 同时连不会互相挤掉（这是相比 v0.1 的 winpc-shell 大的改进）。

但 GUI 操作（鼠标、键盘、截屏）有共享物理资源的风险——agent A 在打字时 agent B 抢着点鼠标会互相干扰。所以 win-device 引入了**advisory 单持有者**模式：

```
Agent A: acquire_winpc(holder_name="agent-A")     # 声明独占
Agent A: take_screenshot()                         # 干活
Agent A: type_text(...)
Agent A: release_winpc(holder_name="agent-A")     # 显式释放

Agent B: get_winpc_status()                        # 查谁在用
  → {"in_use": true, "holder": "agent-A", "idle_seconds": 3, ...}
```

- **advisory**：工具不强制阻止——anyone can call tools。但 `get_winpc_status` 显示当前持有者，agent 应该礼貌等待
- **idle 超时 10 分钟**自动释放（防止 holder 忘了 release 锁住设备）
- 持有者每次调用工具都会刷新 last_used_at
- 计划在 v0.5 加入强制模式（rejected if not holder）

---

## 附录 · 工具列表

`win-device` MCP（FastMCP 原生 SSE，监听 `0.0.0.0:8766/sse`）暴露的全部工具：

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

> v0.1 还有一个独立的 `winpc-shell` MCP（端口 8765，npm `desktop-commander` + Python `mcp-proxy`），由于 single-client 限制 + npm 缓存竞争 + IPv6-only 绑定 + Windows ENOTEMPTY 等等多个上游问题，v0.2 整层并入 win-device。原来 desktop-commander 的工具按等价语义重写为 Python，FastMCP 原生支持多客户端，且不再依赖 Node.js / npm。
