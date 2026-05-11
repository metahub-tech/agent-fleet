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
| 4/5 | 装 launchd plist 到 `~/Library/LaunchAgents/cc.metahub.mac-device.plist` |
| 5/5 | 启动并验证端口 8767 监听 |

脚本结束时会打印：
- 你的 Tailscale 主机名
- mac-device 的 SSE URL
- **GUI 权限授权清单**（必须手动做）

## 4. GUI 权限授权（必须，一次性）

macOS 强制：除非用户在系统设置中显式授权，否则脚本控制鼠标、键盘、屏幕、其他 App 都会被静默拒绝。

> **关键陷阱**：辅助功能 / 屏幕录制面板**拒绝符号链接和 CLI 可执行文件**。venv 里的 `bin/python3` 是符号链接，往面板里拖会显示灰色不可选。**必须拖 `.app` 包**——brew 装的 framework Python 自带一个：
>
> ```
> Intel:  /usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
> ARM:    /opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
> ```
>
> v0.3.1+ 的 `setup-macos.sh` 在结束时会直接打印你这台机器上的实际路径。
>
> 找不到时可用：
> ```bash
> find $(brew --prefix python@3.12) -name 'Python.app' -type d
> ```

打开 **苹果菜单 → 系统设置 → 隐私与安全性**，依次进入：

### 4.1 辅助功能 (Accessibility)
点 +，把上面那个 `Python.app` 拖进去，确保开关 ON。
（控制鼠标 / 键盘 / `pyautogui` 一切都需要这个）

### 4.2 屏幕录制 (Screen Recording)
同样把 `Python.app` 拖进去。
（`take_screenshot` 需要这个；macOS 13+ 新增的限制；macOS 12 上仍需要）

### 4.3 自动化 (Automation)
展开 `python3` 这一行——会列出它请求控制的所有 App（如 System Events / Finder / Safari）。**给每个想脚本控制的 App 打勾**。
（`run_applescript` 控制其他 App 时需要；首次运行 AppleScript 控制某 App 会自动弹出请求，**点允许**即生效，但你也可以提前一次性批量授权）

> ⚠️ 这些列表里的 entry 是按**完整可执行路径**记录的。如果你删了 venv 重建，新 venv 的 python3 路径相同，但 hash 可能变，macOS 通常会让你重新授权。

### 4.3.5 同一个 Python 在不同面板显示成不同的名字（不是 bug，是 macOS 设计）

授权完成后，你会发现：

| 面板 | 看到的条目名 | 图标 |
|---|---|---|
| 辅助功能 (Accessibility) | **Python** | Python.app 的火箭图标 |
| 屏幕录制 (Screen Recording) | **python3.12** | 通用二进制图标 |
| 自动化 (Automation) | **Python** | 同辅助功能 |

它们指向的是**同一个二进制**（`Python.framework/.../MacOS/Python`），只是 TCC 在屏幕录制面板用 binary basename 命名、其他面板用 `.app` 的 bundle name。**两个条目都勾上即可，不需要担心是不是漏了一项**。

这是 macOS 12+ 加严屏幕录制权限校验留下的历史包袱，所有调用 `pyautogui` / `Pillow.ImageGrab` 的非签名 Python 程序都会遇到。

### 4.3.8 用户数据类弹窗（文稿 / 桌面 / 照片 / 日历 / 提醒事项）—— 一招制敌：完全磁盘访问

除了能力权限（辅助功能 / 屏幕录制 / 自动化），macOS 还把若干"用户数据"目录单独列出权限：

| 目录类别 | 触发条件 | 测试 agent 是否需要 |
|---|---|---|
| 文稿 / 桌面 / 下载 | `~/Documents`、`~/Desktop`、`~/Downloads` 任何读写 | **通常需要**（项目代码可能放这里）|
| 网络宗卷 | 访问 SMB / AFP 共享 | 偶尔需要 |
| 照片 (Photos Library) | 访问 `~/Pictures/Photos Library.photoslibrary` | ❌ 不需要 |
| 日历 / 提醒事项 / 通讯录 | 访问 `~/Library/Calendars` 等 | ❌ 不需要 |

**统一解法：给 Python.app 一次"完全磁盘访问"授权**。

```
System Settings → Privacy & Security → Full Disk Access (完全磁盘访问)
→ 解锁 → + → 拖入 Python.framework/.../Resources/Python.app
```

完全磁盘访问覆盖：文稿 / 桌面 / 下载 / ~/Library/* 全部子目录 / Time Machine / Mail / Cookies。授权后 `find ~`、读取应用日志、读项目代码全部不再弹窗。

**永远不要授权**照片 / 日历 / 提醒事项 / 通讯录给 Python——agent 自动化测试用不到，授权徒增个人数据暴露面。这些类别的弹窗一律点"不允许"。

> 有时 Python 用 `find ~` 触发的弹窗是"想访问您的桌面 / 文稿"——授了 Full Disk Access 之后这种就不再出现。已经误授权过的可以在对应面板把那条 entry 删掉，FDA 接管之。

### 4.3.7 你会看到 `Python` 和 `python3.12` 两个条目——两个都要勾

部署完成后，辅助功能 / 屏幕录制 / 自动化 面板里会**各自出现两条 entry**：

| 条目 | TCC key（解析路径） |
|---|---|
| `Python` | `/usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app` （brew 符号链接） |
| `python3.12` | `/usr/local/Cellar/python@3.12/<ver>/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python` （真实路径）|

它们指向**同一个二进制**，但 macOS TCC 用解析后的绝对路径做 key。第一次你从 Privacy 面板手动拖 `.app` 进去时，记的是 brew 符号链接路径；运行时内核报告 Cellar 真实路径，TCC 不匹配，**会再弹一次 prompt 让你授权"python3.12"**。点 Allow 后，第二个 entry 就会出现。

**两个 entry 都勾上才是完整授权**——只勾一个就漏了某些代码路径。

`brew upgrade python@3.12` 升级到新次要版本（如 3.12.13 → 3.12.14）后，Cellar 路径会变，但 brew opt 符号链接保持不变。届时**只有 `python3.12` 那条 entry 失效，需要重新授权**；`Python` 那条仍然有效但实际匹配不到运行时进程。

### 4.3.6 一次同意 = 永久生效（除非...）

权限第一次弹窗、点 Allow 后**永久持久**，重启 / 重 launchd / git pull / 重新连接 SSE 都不会再问。会重新触发弹窗的情况：

- macOS 大版本升级（12 → 13 → 14），TCC 数据库迁移偶尔失败
- `brew upgrade python@3.12` 把 binary 换成新的（次要版本变化）
- 升级 Python 主版本（3.12 → 3.13），路径整个变了
- 手动 reset：`tccutil reset Accessibility / ScreenCapture / AppleEvents`
- 删除 .venv 重建——bin/python3 符号链接的 inode 哈希变了

### 4.4 验证授权生效

回到 Terminal（请把 `<repo>` 换成你 clone 的实际路径，setup 脚本结束时也会打印这两条命令）：

```bash
VENV_PY=<repo>/platforms/macos/server/.venv/bin/python3

$VENV_PY -c "import pyautogui; print('mouse pos:', pyautogui.position())"
```

输出鼠标坐标 → 辅助功能 OK。报 `OSError` 或 hang → 没给权限。

```bash
$VENV_PY -c "from PIL import ImageGrab; print('screen:', ImageGrab.grab().size)"
```

输出尺寸（如 `(2880, 1800)`，物理像素）→ 屏幕录制 OK。报错或全黑 → 没给权限。

> 注意输出的尺寸是**物理像素**（Retina 上 2x），但 `take_screenshot` 工具会把图缩到**逻辑像素**（与 `click(x,y)` 同坐标系），所以 agent 看到的截图直接 `click(x,y)` 即可，不用再做 2x 换算。

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

> ⚠️ **`launchctl bootout` 必须带 plist 路径**，单独写 `launchctl bootout "gui/$(id -u)"` 会卸载该用户域下**所有** LaunchAgent，触发立刻注销 + 黑屏 + 重新登录界面。重登录可恢复所有 agent，但当前会话的未保存工作会丢。**整条命令必须单行**，不要在 `gui/$(id -u)` 后断行。

```bash
# 卸载 launchd 服务（注意：整条命令一行）
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/cc.metahub.mac-device.plist
rm ~/Library/LaunchAgents/cc.metahub.mac-device.plist

# 删仓库目录（venv、所有依赖一起删干净）
rm -rf ~/agent-test-bench

# 收回 GUI 授权（可选）：系统设置 → 隐私与安全性 → 辅助功能 / 屏幕录制 / 自动化
# 把列表里的 python3 entry 删掉
```

---

## 7. 排错

### 7.0 setup-macos.sh 静默退出 / 退到 brew 那一步

**症状**：脚本跑到 `[2/5] Python 3.10+` 然后输出一段 brew 警告或安装信息，回到 shell 提示符，没有 `[3/5]` 出现。

**常见根因**：

1. **brew 目录权限被 root 抢走**（最常见，macOS 12 多年使用后的副产品）
   ```
   Error: The following directories are not writable by your user:
   /usr/local/share/man/man8
   ```
   修复（**不要用 sudo 跑脚本** —— brew 拒绝以 root 运行）：
   ```bash
   sudo chown -R $(whoami) /usr/local/share /usr/local/lib /usr/local/Cellar /usr/local/var/homebrew
   bash platforms/macos/scripts/setup-macos.sh        # 重跑
   ```
   v0.3.1+ 的 setup 脚本会在 `[0/5]` 预检并打印精确的 chown 命令。

2. **brew install 在 macOS 12 (Tier 3) exit 非 0 但其实装好了**：v0.3.1+ 的脚本对此有容错，并直接验证 `python3.12` 二进制是否存在；老版本会 `set -e` 静默死亡。重跑脚本第二次通常就过 —— 因为这次 for-loop 直接探测到已装好的 `python3.12`，跳过 brew 步骤。

3. **anaconda `(base)` 抢了 PATH**：脚本对 brew 装的 python 用绝对路径，不受影响；但如果你卡在 `python3 -c '...'` 的版本探测且 anaconda 是 3.9，for-loop 不会选中它，然后会进 brew install 分支（正常行为，不是 bug）。

### 7.0.5 重启 mac-device 服务的正确姿势

```bash
# 优先方案：kickstart 重启（保持 plist 不变）
launchctl kickstart -k "gui/$(id -u)/cc.metahub.mac-device"

# 如果 plist 内容改了（重跑了 setup-macos.sh），先 bootout 再 bootstrap：
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/cc.metahub.mac-device.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/cc.metahub.mac-device.plist
```

> ⚠️ 上面每条命令都**必须单行**，特别是 `bootout`：缺了 plist 路径会卸掉整个用户 GUI 域（注销级灾难）。复制粘贴时如果终端把行折断了，先在终端里 `Cmd+A` 全选确认是单行再回车。

### 7.1 8767 没在监听

```bash
# 看 launchd 服务状态（最后一列是 last exit code，0=ok）
launchctl print "gui/$(id -u)/cc.metahub.mac-device" | head -30

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

参见 [`platforms/macos/skills/using-mac/SKILL.md`](../../platforms/macos/skills/using-mac/SKILL.md)。基本流程：

```
Agent A: get_mac_status                  # 看是否空闲
Agent A: acquire_mac(holder_name="...")  # 声明
Agent A: ... 干活 ...
Agent A: release_mac(holder_name="...")  # 显式释放
```

10 分钟无活动自动 release。

---

## 附录 · 工具列表

`mac-device` MCP（监听 `0.0.0.0:8767/sse`）暴露的工具：

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
