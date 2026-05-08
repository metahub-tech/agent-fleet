# macOS Platform Setup Guide

> 把一台 macOS 12+ 配置为 agent-test-bench 测试主机。整个过程通常 10-20 分钟，绝大部分由 `setup-macos.sh` 自动化；GUI 权限是唯一需要手动点击的步骤。
>
> 本指南只面向 **macOS 主机的本地管理员**。Agent 端（你的 Linux/Windows 开发机）的配置见 [`../agent-host-setup.md`](../agent-host-setup.md)。

## 0. 前置条件

- macOS 12 (Monterey) 或更新；Apple Silicon 或 Intel 都行
- 一个有管理员权限的用户账户
- 一个 [Tailscale](https://tailscale.com) 账户（与 Agent 主机同一 tailnet）
- 互联网连接
- **GUI 物理可达**（一次性手动授权 GUI 权限要求）

## 1. 安装 Tailscale 并登录

任意 Terminal：

```bash
# 没装 Homebrew 先装一下
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install --cask tailscale
```

打开 menubar 里的 Tailscale 图标 → **Login** → 用与 Agent 主机相同的账号登录。

确认登录成功：

```bash
tailscale status
```

应能看到本机和 Agent 主机都在列表里。

## 2. 拿到本项目代码

### 选项 A · git clone（推荐）

```bash
# 公开版本（v1.0+）
git clone https://github.com/metahub-tech/agent-test-bench.git ~/agent-test-bench

# 当前私有阶段：先 GitHub CLI 鉴权
brew install gh
gh auth login
gh repo clone metahub-tech/agent-test-bench ~/agent-test-bench
```

### 选项 B · 浏览器下载 ZIP

1. 浏览器打开 https://github.com/metahub-tech/agent-test-bench
2. 点 `Code` → `Download ZIP`
3. 解压到 `~/agent-test-bench`

## 3. 跑安装脚本

```bash
cd ~/agent-test-bench
bash platforms/macos/scripts/setup-macos.sh
```

脚本依次做 5 件事：

| 步骤 | 内容 |
|---|---|
| 1/5 | 检查 Tailscale 已登录 |
| 2/5 | 装 Python 3.12（若未装或版本 < 3.10）；通过 brew |
| 3/5 | 在 `platforms/macos/server/.venv` 建虚拟环境，装依赖 |
| 4/5 | 装 launchd plist 到 `~/Library/LaunchAgents/cc.metahub.macbox-gui.plist` |
| 5/5 | 启动并验证端口 8767 监听 |

脚本结束时会打印：
- 你的 Tailscale 主机名
- macbox-gui 的 SSE URL
- **GUI 权限授权清单**（必须手动做）

## 4. GUI 权限授权（必须，一次性）

macOS 强制：除非用户在系统设置中显式授权，否则脚本控制鼠标、键盘、屏幕、其他 App 都会被静默拒绝。

打开 **苹果菜单 → 系统设置 → 隐私与安全性**，依次进入：

### 4.1 辅助功能 (Accessibility)
点 +，添加 `~/agent-test-bench/platforms/macos/server/.venv/bin/python3`，确保开关 ON。
（控制鼠标 / 键盘 / `pyautogui` 一切都需要这个）

### 4.2 屏幕录制 (Screen Recording)
同样添加 venv 的 python3。
（`take_screenshot` 需要这个；macOS 13+ 新增的限制）

### 4.3 自动化 (Automation)
展开 `python3` 这一行——会列出它请求控制的所有 App（如 System Events / Finder / Safari）。**给每个想脚本控制的 App 打勾**。
（`run_applescript` 控制其他 App 时需要；首次运行 AppleScript 控制某 App 会自动弹出请求，**点允许**即生效，但你也可以提前一次性批量授权）

> ⚠️ 这些列表里的 entry 是按**完整可执行路径**记录的。如果你删了 venv 重建，新 venv 的 python3 路径相同，但 hash 可能变，macOS 通常会让你重新授权。

### 4.4 验证授权生效

回到 Terminal：

```bash
~/agent-test-bench/platforms/macos/server/.venv/bin/python3 -c "
import pyautogui
print('mouse pos:', pyautogui.position())
"
```

如果输出鼠标位置坐标 → 辅助功能 OK。如果报 `OSError` 或 hang → 没给权限。

```bash
~/agent-test-bench/platforms/macos/server/.venv/bin/python3 -c "
from PIL import ImageGrab
img = ImageGrab.grab()
print('screen:', img.size)
"
```

如果输出尺寸（如 `(2880, 1800)`）→ 屏幕录制 OK。如果输出全黑或失败 → 没给权限。

## 5. 验证

脚本最后已经自检过端口监听。手动复查：

```bash
# 服务进程
launchctl list | grep macbox

# 端口
lsof -nP -iTCP:8767 -sTCP:LISTEN

# 日志
tail -20 ~/agent-test-bench/platforms/macos/logs/macos-gui.log
```

## 6. 卸载

```bash
# 卸载 launchd 服务
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist
rm ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist

# 删仓库目录（venv、所有依赖一起删干净）
rm -rf ~/agent-test-bench

# 收回 GUI 授权（可选）：系统设置 → 隐私与安全性 → 辅助功能 / 屏幕录制 / 自动化
# 把列表里的 python3 entry 删掉
```

---

## 7. 排错

### 7.1 8767 没在监听

```bash
# 看 launchd 服务状态（最后一列是 last exit code，0=ok）
launchctl print "gui/$(id -u)/cc.metahub.macbox-gui" | head -30

# 看 traceback
tail -50 ~/agent-test-bench/platforms/macos/logs/macos-gui.log

# 手动跑看实时错
~/agent-test-bench/platforms/macos/server/.venv/bin/python3 \
    ~/agent-test-bench/platforms/macos/server/macos_gui_mcp.py
```

主要会卡在 pip 装依赖（pyautogui 在 Apple Silicon 偶尔有 wheel 问题）→ 看 venv 输出。

### 7.2 鼠标点击没反应

辅助功能权限没给。回到第 4 节。**注意**：venv 重建后路径若相同，授权多半保留；但如果路径变了（比如换了 brew prefix），需重新授权。

### 7.3 截图全黑

屏幕录制权限没给。回到第 4.2 节。

### 7.4 AppleScript 报错 "execution error: ... -1743 (errAEEventNotPermitted)"

`Automation` 权限里没勾选被控制的 App。例如要控制 Safari，需在 `python3 → Safari` 那行打勾。**首次运行 `tell application "Safari" to ...` 会自动弹出请求**，那时候点"好"即可永久生效。

### 7.5 macOS lock 屏 / sleep 后服务挂掉

你的部署形态是 "一直开着不关盖"，应该不会触发。如果真碰到：
- 系统设置 → 锁屏 → 关闭"睡眠时锁定屏幕" + "需要密码"延迟拉到 24 小时
- 系统设置 → 节能 → "防止 Mac 自动进入睡眠" 打开（USB-C 充电时该选项才出现）
- launchd KeepAlive 已经会自动重启进程，所以即使 wake 后挂了也会自动恢复

### 7.6 Tailscale ACL 加固

默认 tailnet 内全互通。如果 tailnet 还有其他人，建议在 [Tailscale Admin Console](https://login.tailscale.com/admin/acls) 加规则，限定只有 Agent 主机能访问 8767。

### 7.7 多 Agent 协作

参见 [`platforms/macos/skills/using-macbox/SKILL.md`](../../platforms/macos/skills/using-macbox/SKILL.md)。基本流程：

```
Agent A: get_mac_status                  # 看是否空闲
Agent A: acquire_mac(holder_name="...")  # 声明
Agent A: ... 干活 ...
Agent A: release_mac(holder_name="...")  # 显式释放
```

10 分钟无活动自动 release。

---

## 附录 · 工具列表

`macbox-gui` MCP（监听 `0.0.0.0:8767/sse`）暴露的工具：

| 类别 | 工具 |
|---|---|
| **使用状态** | `acquire_mac`, `release_mac`, `get_mac_status` |
| 屏幕 | `get_screen_size`, `take_screenshot` |
| 鼠标 | `click`, `move_mouse` |
| 键盘 | `type_text`, `paste_text`, `press_key` (cmd/option/shift/ctrl) |
| 进程（一次性） | `open_app`, `kill_process`, `list_processes` |
| 长时进程 | `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions` |
| 文件系统 | `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info` |
| 文件搜索 | `start_search`, `get_more_search_results`, `list_searches`, `stop_search` |
| Shell | `run_zsh`, `run_applescript` |

> v0.3.0 暂未实现 `list_windows` / `inspect_window` / `focus_window` —— 这些在 Windows 上靠 pywinauto；macOS 等价物需用 AppleScript 或 NSAccessibility 重写，下个版本补。当前可通过 `run_applescript` 调 `tell application "System Events" to get title of every window of every process` 实现。
