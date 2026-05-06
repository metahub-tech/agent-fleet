# Windows MCP 测试主机一键安装脚本
# 用法（以管理员身份打开 PowerShell）:
#   cd <脚本所在目录>
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
#
# 前置：windows_gui_mcp.py 与 requirements.txt 必须与本脚本同目录

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== Windows MCP 测试主机安装 ===" -ForegroundColor Cyan

# ---------- 1. Tailscale ----------
Write-Host "`n[1/7] 检查 Tailscale ..." -ForegroundColor Yellow
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Host "    未安装，开始 winget 安装..."
    winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
    Write-Host "    安装完成。请打开托盘的 Tailscale 图标 → Login，登录后再继续。" -ForegroundColor Magenta
    Read-Host "登录完成后按回车继续"
} else {
    Write-Host "    已安装：$(tailscale version | Select-Object -First 1)"
}

# ---------- 2. OpenSSH Server ----------
Write-Host "`n[2/7] 配置 OpenSSH Server ..." -ForegroundColor Yellow
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*" | Select-Object -First 1
if ($cap.State -ne "Installed") {
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# 默认 shell 设为 PowerShell
if (-not (Test-Path "HKLM:\SOFTWARE\OpenSSH")) {
    New-Item -Path "HKLM:\SOFTWARE\OpenSSH" -Force | Out-Null
}
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
    -Value "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -PropertyType String -Force | Out-Null

# 防火墙
if (-not (Get-NetFirewallRule -Name "sshd" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
Write-Host "    OK。SSH 端口 22 已就绪，默认 shell = PowerShell。"

# ---------- 3. Node.js ----------
Write-Host "`n[3/7] 检查 Node.js ..." -ForegroundColor Yellow
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    Write-Host "    已安装：node $(node -v)"
}

# ---------- 4. 部署 GUI MCP Python 项目 ----------
Write-Host "`n[4/7] 部署 GUI MCP（Python 虚拟环境）..." -ForegroundColor Yellow
$mcpDir = "C:\mcp\gui"
New-Item -ItemType Directory -Path $mcpDir -Force | Out-Null
Copy-Item -Path (Join-Path $ScriptDir "windows_gui_mcp.py") -Destination $mcpDir -Force
Copy-Item -Path (Join-Path $ScriptDir "requirements.txt")    -Destination $mcpDir -Force

Push-Location $mcpDir
if (-not (Test-Path ".\.venv")) {
    python -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
Pop-Location
Write-Host "    OK。venv = $mcpDir\.venv"

# ---------- 5. 防火墙：8765 / 8766 仅 Tailscale 接口 ----------
Write-Host "`n[5/7] 配置 MCP 端口防火墙规则 ..." -ForegroundColor Yellow
$tsAdapter = Get-NetAdapter | Where-Object { $_.InterfaceDescription -like "*Tailscale*" } | Select-Object -First 1

# 清掉可能的旧规则
Get-NetFirewallRule -DisplayName "MCP DesktopCommander*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName "MCP WindowsGui*"        -ErrorAction SilentlyContinue | Remove-NetFirewallRule

if ($tsAdapter) {
    New-NetFirewallRule -DisplayName "MCP DesktopCommander (Tailscale)" `
        -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow `
        -InterfaceAlias $tsAdapter.Name | Out-Null
    New-NetFirewallRule -DisplayName "MCP WindowsGui (Tailscale)" `
        -Direction Inbound -Protocol TCP -LocalPort 8766 -Action Allow `
        -InterfaceAlias $tsAdapter.Name | Out-Null
    Write-Host "    OK。仅 $($tsAdapter.Name) 接口允许 8765/8766。"
} else {
    Write-Warning "    未发现 Tailscale 网卡。先放行所有接口（不安全），登录 Tailscale 后重新运行本脚本可收紧。"
    New-NetFirewallRule -DisplayName "MCP DesktopCommander (TEMP-ALL)" `
        -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow | Out-Null
    New-NetFirewallRule -DisplayName "MCP WindowsGui (TEMP-ALL)" `
        -Direction Inbound -Protocol TCP -LocalPort 8766 -Action Allow | Out-Null
}

# ---------- 6. Task Scheduler 注册自启 ----------
Write-Host "`n[6/7] 注册登录时自启任务 ..." -ForegroundColor Yellow

# 6a. desktop-commander：用 supergateway 把 stdio 包成 SSE
$dcAction = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument '/c npx -y supergateway --stdio "npx -y @wonderwhy-er/desktop-commander" --port 8765 --baseUrl http://0.0.0.0:8765 --ssePath /sse --messagePath /message'
$dcTrigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$dcSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MCP-DesktopCommander" -Action $dcAction -Trigger $dcTrigger `
    -Settings $dcSettings -RunLevel Highest -User "Administrator" -Force | Out-Null

# 6b. GUI MCP
$guiAction = New-ScheduledTaskAction `
    -Execute  "$mcpDir\.venv\Scripts\python.exe" `
    -Argument "$mcpDir\windows_gui_mcp.py" `
    -WorkingDirectory $mcpDir
$guiTrigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$guiSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MCP-WindowsGui" -Action $guiAction -Trigger $guiTrigger `
    -Settings $guiSettings -RunLevel Highest -User "Administrator" -Force | Out-Null

Write-Host "    OK。两个任务已注册（登录 Administrator 后自动启动）。"

# ---------- 7. 立即启动 ----------
Write-Host "`n[7/7] 立即启动一次（用于现场验证）..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName "MCP-DesktopCommander"
Start-ScheduledTask -TaskName "MCP-WindowsGui"
Start-Sleep -Seconds 5

Write-Host "`n=== 完成 ===" -ForegroundColor Green

$tsName = (tailscale status --json 2>$null | ConvertFrom-Json).Self.HostName
if (-not $tsName) { $tsName = "<windows-tailscale-name>" }

Write-Host @"

下一步：
1. 把你 Linux 端的公钥（~/.ssh/id_ed25519_winpc.pub 内容）写入：
     C:\ProgramData\ssh\administrators_authorized_keys
   并设置权限：
     icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r
     icacls C:\ProgramData\ssh\administrators_authorized_keys /grant "Administrators:F" /grant "SYSTEM:F"

2. 在 Linux 端验证：
     tailscale ping $tsName
     ssh Administrator@$tsName "Get-Date"
     curl -N http://${tsName}:8765/sse   # 应保持长连接（desktop-commander）
     curl -N http://${tsName}:8766/sse   # 应保持长连接（GUI MCP）

3. 在 Linux 端 ~/.claude/settings.json 加入 mcpServers 段（见 mcp-settings.json）。

排错：
  Get-ScheduledTaskInfo -TaskName MCP-DesktopCommander
  Get-ScheduledTaskInfo -TaskName MCP-WindowsGui
  netstat -ano | findstr "8765 8766"
"@ -ForegroundColor Cyan
