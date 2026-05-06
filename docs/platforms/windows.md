# Windows 11 远程测试主机搭建手册

> 目标：让 Linux 上运行的 Claude Code 能直接驱动一台 Windows 11 电脑做 CLI/服务调试和桌面 GUI 自动化测试。
>
> 网络：**Tailscale** 跨网组网（不同局域网也通）
> 通道：**SSH**（命令行兜底）+ **两个 MCP 服务**（结构化工具调用）
>   - `desktop-commander`（端口 8765）：shell / 文件 / 进程，社区成熟方案
>   - `windows-gui`（端口 8766）：自写 FastMCP 服务，截屏 / 键鼠 / 控件树 / PowerShell
>
> 预计耗时：30~45 分钟

---

## 0. 文件清单

跟本文档一起的 `windows-mcp/` 目录下有四个文件：

| 文件 | 用途 | 部署到 |
|---|---|---|
| `windows_gui_mcp.py` | GUI MCP server 主程序 | Windows: `C:\mcp\gui\` |
| `requirements.txt` | Python 依赖 | Windows: `C:\mcp\gui\` |
| `setup-windows.ps1` | Windows 一键安装脚本 | Windows: 任意临时目录 |
| `mcp-settings.json` | Linux 端 Claude Code MCP 配置片段 | Linux: 合并进 `~/.claude/settings.json` |

---

## 1. 前置约定（占位符替换）

下文出现的占位符，第一次使用前先确定其值并保持一致：

| 占位符 | 含义 | 例 |
|---|---|---|
| `<WIN_NAME>` | Windows 在 Tailscale 里的 MagicDNS 主机名 | `desktop-abc123` |
| `<LINUX_NAME>` | Linux 在 Tailscale 里的 MagicDNS 主机名 | `worker-pc` |
| `<LINUX_PUBKEY>` | Linux 端生成的 ed25519 公钥**整行内容** | `ssh-ed25519 AAAA... claude-to-winpc` |

---

## 2. Linux 端：生成 SSH 密钥

```bash
# 生成专用 key（与其他 key 隔离，便于将来撤销）
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_winpc -C "claude-to-winpc" -N ""

# 拷出公钥内容备用
cat ~/.ssh/id_ed25519_winpc.pub
```

把输出的整行（`ssh-ed25519 AAAA...` 到末尾的注释）作为 `<LINUX_PUBKEY>` 保存。

---

## 3. Linux 端：装 Tailscale 并登录

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale status        # 看到自己出现
tailscale ip -4         # 记录 Tailscale IPv4
```

用浏览器跟随 `tailscale up` 给出的 URL 完成登录授权。从 `tailscale status` 输出里找到自己的主机名作为 `<LINUX_NAME>`。

---

## 4. Windows 端：装 Tailscale 并登录

**以管理员身份打开 PowerShell**（开始菜单搜 `PowerShell` → 右键"以管理员身份运行"），执行：

```powershell
winget install --id Tailscale.Tailscale -e `
    --accept-source-agreements --accept-package-agreements
```

安装完成后：

1. 任务栏托盘点 Tailscale 图标 → **Login** → 用同一账号登录
2. 回到 PowerShell：

```powershell
tailscale status
tailscale ip -4
```

记下 Windows 的主机名作为 `<WIN_NAME>`。

**双向连通性自检**：

```bash
# Linux 端
tailscale ping <WIN_NAME>     # 几次后应出现 via direct/DERP，说明通了
```

---

## 5. 把项目文件传到 Windows

SSH 这时还没配好，最快的方式是**临时 HTTP 服务下载**：

### 5.1 Linux 端起临时服务

```bash
cd ~/claude-test/claude-remote/windows-mcp   # 这三个文件所在目录
python3 -m http.server 8000
```

保持窗口开着。

### 5.2 Windows 端拉文件

在 Windows 管理员 PowerShell 里：

```powershell
mkdir C:\mcp-setup
cd C:\mcp-setup

$LINUX = "<LINUX_NAME>"   # 替换占位符
Invoke-WebRequest -Uri "http://${LINUX}:8000/setup-windows.ps1"  -OutFile setup-windows.ps1
Invoke-WebRequest -Uri "http://${LINUX}:8000/windows_gui_mcp.py" -OutFile windows_gui_mcp.py
Invoke-WebRequest -Uri "http://${LINUX}:8000/requirements.txt"   -OutFile requirements.txt

dir   # 应看到三个文件
```

拷完回 Linux 终端按 `Ctrl+C` 停掉 HTTP 服务。

> **替代方案**：如果你已经能 RDP 进 Windows，直接拖拽剪贴板复制；或先手动启用一次 OpenSSH，然后 `scp` 过去也行。

---

## 6. Windows 端：跑一键安装脚本

在 Windows 管理员 PowerShell：

```powershell
cd C:\mcp-setup
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
```

脚本会逐步执行，每步带进度提示：

| 步骤 | 内容 |
|---|---|
| 1/7 | 检查/安装 Tailscale（已装则跳过） |
| 2/7 | 装 OpenSSH Server，开启自启，默认 shell 设为 PowerShell，开放 22 端口 |
| 3/7 | 检查/安装 Node.js LTS |
| 4/7 | 部署 GUI MCP 到 `C:\mcp\gui`，建 venv，安装 Python 依赖 |
| 5/7 | 防火墙：8765/8766 仅 Tailscale 接口入站允许 |
| 6/7 | 注册两个 Task Scheduler 任务（登录 Administrator 时自启） |
| 7/7 | 立即启动一次（用于现场验证） |

⚠️ **如果中途暂停在 Tailscale 提示**：先去托盘 Login，再回 PowerShell 按回车。

⚠️ **如果第 1 步发现 Tailscale 网卡没识别到**：脚本会先临时放行所有接口（不安全），登录 Tailscale 后**重跑一次脚本**会自动收紧到只允许 Tailscale 接口。

---

## 7. Windows 端：放置 Linux 的 SSH 公钥

**关键**：Windows 11 的 `Administrator` 账户不用 `~\.ssh\authorized_keys`，必须用 `C:\ProgramData\ssh\administrators_authorized_keys`。

仍在管理员 PowerShell：

```powershell
# 把第 2 节拿到的 <LINUX_PUBKEY> 整行粘到引号里
$pub  = "ssh-ed25519 AAAA...替换我...claude-to-winpc"
$path = "C:\ProgramData\ssh\administrators_authorized_keys"

Set-Content -Path $path -Value $pub -Encoding ascii

# 锁权限（不锁的话 sshd 会因为"权限过宽"忽略此文件）
icacls $path /inheritance:r
icacls $path /grant "Administrators:F"
icacls $path /grant "SYSTEM:F"

# 重启 sshd 让配置生效
Restart-Service sshd
```

---

## 8. Linux 端：配 SSH 别名 + 测连通

编辑 `~/.ssh/config`，追加：

```sshconfig
Host winpc
  HostName <WIN_NAME>
  User Administrator
  IdentityFile ~/.ssh/id_ed25519_winpc
  StrictHostKeyChecking accept-new
```

测试：

```bash
ssh winpc "hostname; whoami; Get-Date"
```

期望输出 Windows 主机名、`<win>\Administrator`、当前时间。

> **失败常见原因**：
> - `Permission denied (publickey)`：公钥没正确写入 `administrators_authorized_keys`，或没锁权限。回到第 7 节。
> - `Connection refused`：sshd 服务没起，`Get-Service sshd` 看状态，`Start-Service sshd`。
> - `Connection timed out`：防火墙没放行 22，或 Tailscale 没连上。

---

## 9. Linux 端：配 Claude Code MCP

编辑 `~/.claude/settings.json`，把下面的 `mcpServers` 段合并进去（如果文件已有 `mcpServers`，把这两个 key 追加进去；如果文件已有别的 key 比如 `permissions`，并列保留即可）：

```json
{
  "mcpServers": {
    "winpc-shell": {
      "type": "sse",
      "url": "http://<WIN_NAME>:8765/sse"
    },
    "winpc-gui": {
      "type": "sse",
      "url": "http://<WIN_NAME>:8766/sse"
    }
  }
}
```

把 `<WIN_NAME>` 替换成第 4 节记下的 Windows Tailscale 主机名。

**完整 `settings.json` 示例**（如果你的文件原本是空的）：

```json
{
  "mcpServers": {
    "winpc-shell": {
      "type": "sse",
      "url": "http://desktop-abc123:8765/sse"
    },
    "winpc-gui": {
      "type": "sse",
      "url": "http://desktop-abc123:8766/sse"
    }
  }
}
```

---

## 10. 验证清单

按顺序执行，逐条打勾：

| # | 命令（Linux 端） | 期望结果 |
|---|---|---|
| 1 | `tailscale ping <WIN_NAME>` | 几次内出现 `via DERP` 或 `via direct` |
| 2 | `ssh winpc "Get-Process \| Select-Object -First 3"` | 列出 3 个 Windows 进程 |
| 3 | `curl -sN http://<WIN_NAME>:8765/sse \| head -c 200` | 输出 SSE 握手帧（`event:` 开头），不立刻断开 |
| 4 | `curl -sN http://<WIN_NAME>:8766/sse \| head -c 200` | 同上 |
| 5 | 重启 Claude Code 后运行 `/mcp` | `winpc-shell` 和 `winpc-gui` 都显示 `connected` |
| 6 | 跟 Claude 说"用 winpc-gui 截一下当前 Windows 屏幕" | Claude 能调用 `take_screenshot` 并看到图 |
| 7 | "用 winpc-gui 列出所有可见窗口" | 返回标题列表 |
| 8 | "用 winpc-gui 启动记事本，输入 'hello'，再截图" | 看到记事本窗口里显示 hello |

6/7/8 全部通过 = 全套打通。

---

## 11. GUI MCP 工具速查

`winpc-gui` 暴露给 Claude 的所有工具：

### 屏幕 / 视觉
- `get_screen_size()` — 主屏分辨率
- `take_screenshot(region?)` — 整屏或矩形区域截图，返回 PNG

### 窗口 / 控件
- `list_windows()` — 列所有可见顶层窗口（标题、类名、矩形、PID）
- `inspect_window(title_substring, max_depth=4)` — 打印 UIA 控件树
- `focus_window(title_substring)` — 把窗口拉到前台

### 鼠标 / 键盘
- `click(x, y, button="left", clicks=1)` — 屏幕坐标点击
- `move_mouse(x, y, duration=0.0)` — 移动鼠标
- `type_text(text, interval=0.02)` — ASCII 文本键入
- `paste_text(text)` — 任意文本（含中文）通过剪贴板贴入
- `press_key(keys)` — 单键或组合键（`enter` / `ctrl+s` / `alt+f4` / `win+d`）

### 进程 / 应用
- `launch_app(path, args=None)` — 启动应用
- `kill_process(pid)` — 杀进程
- `list_processes(name_filter=None)` — 列进程

### Shell
- `run_powershell(script, timeout=60)` — 执行任意 PowerShell

### desktop-commander（`winpc-shell`）补充
另外通过 `winpc-shell` 还能用 desktop-commander 提供的：shell 命令执行、文件读写、目录搜索、grep、文件 diff、进程管理等。

---

## 12. 已知坑 & 排错

### 12.1 GUI 任务必须有活动用户会话
Task Scheduler 触发器是 "登录 Administrator 时启动"。Windows 重启后**没人登录的话 GUI MCP 不会启**。两种办法：

**方案 A：开启自动登录（测试机推荐）**

```powershell
# 法一：图形界面（最简单）
netplwiz
# 在弹出窗口取消勾选"要使用本计算机，用户必须输入用户名和密码"，输入 Administrator 密码

# 法二：注册表（脚本化）
$AutoLogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty $AutoLogon "AutoAdminLogon"   "1"
Set-ItemProperty $AutoLogon "DefaultUserName"  "Administrator"
Set-ItemProperty $AutoLogon "DefaultPassword"  "你的密码"
```

**方案 B：远程时手动 RDP 进去登录一次**，保持会话即可。

### 12.2 高 DPI 屏幕坐标错位
如果发现 `click(x, y)` 点的位置和 `take_screenshot` 看到的不一致：

把 Windows 显示缩放设回 100%（设置 → 系统 → 显示 → 缩放与布局），或者在 `windows_gui_mcp.py` 顶部 import 后加：

```python
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    pass
```

改完重启 Task Scheduler 任务：

```powershell
Stop-ScheduledTask  -TaskName MCP-WindowsGui
Start-ScheduledTask -TaskName MCP-WindowsGui
```

### 12.3 端口被占用 / 任务起不来

```powershell
# 看任务执行状态
Get-ScheduledTaskInfo -TaskName MCP-DesktopCommander
Get-ScheduledTaskInfo -TaskName MCP-WindowsGui

# 看端口监听
netstat -ano | findstr "8765 8766"

# 看 GUI MCP 实际进程（python.exe 跑 windows_gui_mcp.py）
Get-Process python -ErrorAction SilentlyContinue | Format-List Id, Path, StartTime
```

如果 8765/8766 没占用而任务又"已运行"，多半是脚本启动后立刻崩溃。手动跑一次看错：

```powershell
# 手动跑 GUI MCP，看报错
cd C:\mcp\gui
.\.venv\Scripts\python.exe .\windows_gui_mcp.py

# 手动跑 desktop-commander
npx -y supergateway --stdio "npx -y @wonderwhy-er/desktop-commander" --port 8765
```

### 12.4 Claude Code 看不到 MCP 工具
- `/mcp` 命令显示 `failed`：检查 `~/.claude/settings.json` 的 URL 是否 `http://` 而非 `https://`，主机名拼对
- 显示 `connected` 但 Claude 调不到：重启 Claude Code 让它重新拉工具列表

### 12.5 supergateway 包名变更
脚本里写死了 `@wonderwhy-er/desktop-commander`。如果将来该包改名，从 https://github.com/wonderwhy-er/DesktopCommanderMCP README 找到当前安装命令，编辑：

```powershell
notepad C:\mcp-setup\setup-windows.ps1
```

定位 `Argument` 那行替换 `@wonderwhy-er/desktop-commander` 为新名，重跑脚本。

或者直接修改已注册的任务：

```powershell
Get-ScheduledTask -TaskName MCP-DesktopCommander | Select-Object -ExpandProperty Actions
# 修改后：
$newAction = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument '/c npx -y supergateway --stdio "npx -y <新包名>" --port 8765'
Set-ScheduledTask -TaskName MCP-DesktopCommander -Action $newAction
Stop-ScheduledTask  -TaskName MCP-DesktopCommander
Start-ScheduledTask -TaskName MCP-DesktopCommander
```

### 12.6 Tailscale ACL 加固（可选）
如果你的 tailnet 还有别人，建议在 Tailscale Admin Console（https://login.tailscale.com/admin/acls）加规则，限定只有你的 Linux 节点能访问 Windows 的 8765/8766：

```hujson
{
  "acls": [
    // 默认全互通保留你已有规则
    // ...

    // 收紧 Windows MCP 端口
    {
      "action": "accept",
      "src":    ["<linux-node-tag-or-user>"],
      "dst":    ["<windows-node>:8765,8766"]
    }
  ]
}
```

---

## 13. 后续运维常用命令

### 重启服务

```powershell
# 重启两个 MCP
Stop-ScheduledTask  -TaskName MCP-DesktopCommander
Start-ScheduledTask -TaskName MCP-DesktopCommander
Stop-ScheduledTask  -TaskName MCP-WindowsGui
Start-ScheduledTask -TaskName MCP-WindowsGui

# 重启 sshd
Restart-Service sshd
```

### 查看日志

Task Scheduler 任务的运行历史：
- 打开 "任务计划程序" (`taskschd.msc`)
- 任务计划程序库 → 找到 `MCP-WindowsGui` → 下面"历史记录"标签

或命令行：

```powershell
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational'; ID=200,201,203} -MaxEvents 20 |
    Where-Object {$_.Message -like "*MCP*"} | Format-Table TimeCreated, Id, Message -AutoSize
```

### 升级 Python 依赖

```powershell
cd C:\mcp\gui
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
Stop-ScheduledTask  -TaskName MCP-WindowsGui
Start-ScheduledTask -TaskName MCP-WindowsGui
```

### 完全卸载

```powershell
# 取消任务
Unregister-ScheduledTask -TaskName MCP-DesktopCommander -Confirm:$false
Unregister-ScheduledTask -TaskName MCP-WindowsGui        -Confirm:$false

# 删项目
Remove-Item -Recurse -Force C:\mcp

# 删防火墙规则
Get-NetFirewallRule -DisplayName "MCP *" | Remove-NetFirewallRule

# OpenSSH 不动（系统组件）；如要卸载：
# Remove-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

---

## 14. 操作顺序速记卡

打印或贴在屏幕上对照：

```
□ Linux: 生成 ssh key  (第 2 节)
□ Linux: 装 Tailscale 并登录  (第 3 节)
□ Win:   装 Tailscale 并登录，记 <WIN_NAME>  (第 4 节)
□ Linux: 起 http.server 临时服务  (第 5.1 节)
□ Win:   下载 3 个文件到 C:\mcp-setup  (第 5.2 节)
□ Win:   跑 setup-windows.ps1  (第 6 节)
□ Win:   写 administrators_authorized_keys + 锁权限  (第 7 节)
□ Linux: 配 ~/.ssh/config，ssh winpc 验证  (第 8 节)
□ Linux: 改 ~/.claude/settings.json  (第 9 节)
□ Linux: 重启 Claude Code，跑验证清单 1-8  (第 10 节)
```

跑完即可使用。
