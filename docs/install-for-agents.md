# 面向 Agent 的安装手册（install-for-agents）

> **这份文档的读者是一个能执行命令的 agent，不是人。**
> 目标：把仓库（或这份文档）交给 agent 后，它能在**不需要人类读文档**的前提下完成 —— 装 MCP server → 装 skill → 打通 human_browser 的 DOM 感知（浏览器扩展）→ 只把「agent 物理上做不到的 4 件事」交还给人。
>
> 人类向的说明仍在 [`docs/install-pattern.md`](install-pattern.md) 与 [`docs/platforms/<name>.md`](platforms/)；本文件与它们冲突时，**以本文件 + 代码为准**。

---

## 0. 你手上是什么

| 情况 | 第一步 |
|---|---|
| 你拿到了**仓库目录** | 直接进 §2 |
| 你只拿到了**这份文档** | 先取仓库：`git clone https://github.com/metahub-tech/agent-fleet` 并 `cd agent-fleet` |

仓库根靠 `.git` 判定。**所有安装脚本都必须在仓库根目录执行**（`platforms/` 不在 wheel 里，CLI 靠相对路径定位）。

---

## 1. 三步决策（先想清楚再动手）

```
① 这台机器要扮演什么角色？
   只跑 agent、连别人的设备        → 只做 §4（装 skill）+ 写 ~/.claude.json / mcp 配置，跳过 §3
   既是 agent 又要当"手"（有 GUI） → 做 §3（本机装设备桥）+ §4
   要把另一台机器变成设备          → 到那台机器上做 §3

② 目标设备是什么 OS？
   Windows / macOS → 本机装，agent 可全自动（GUI 权限需人类点一次）
   Android         → 宿主可以是 Win/mac，手机侧必须人类授权 ADB
   iOS / iPadOS    → 宿主必须是 macOS，且必须人类完成 Xcode 签名 / 设备信任

③ 要不要 human_browser（真人身份操作浏览器）？
   要 → 额外做 §5（一次性 5 分钟，含重启 server）
   不要 → 装完 §4 即可交付
```

---

## 2. 步骤机总览

| 步骤 | 谁做 | 产物 | 成功判据 |
|---|---|---|---|
| S0 探测 | agent | 环境事实 | 四项探测全有明确结论 |
| S1 设备端安装 | agent（+人类授权） | 设备桥 MCP server 常驻 | 端口在听 + `/health` 返回 `ok` |
| S2 自检 | agent | 工具清单 | `list_capabilities()` 返回 `core` 且工具数符合平台 |
| S3 装 skill | agent | 技能目录里出现 2–4 个 skill | `--list` 与实际目录一致，agent 技能目录能看到 |
| S4 human_dom provisioning | agent（+重启） | 标记文件 + 扩展自动装入 profile | `list_capabilities` 里 human_dom = `enabled` |
| S5 人类协作 | **人类** | 权限 / 授权 / 签名 | 各自验证命令通过 |
| S6 交接 | agent | 一句话 + 下一步 | 人类知道「现在可以让我操作哪台设备」 |

---

## S0 · 探测（先跑，不要跳过）

```powershell
# Windows（PowerShell 5.1 可用）
[System.Environment]::OSVersion.VersionString; $env:PROCESSOR_ARCHITECTURE
(Get-Command python3,python,uv,git -ErrorAction SilentlyContinue | Select-Object Name,Source)
(Get-Command chrome -ErrorAction SilentlyContinue).Source
Get-NetTCPConnection -State Listen -LocalPort 8766,8767,8768,8769 -ErrorAction SilentlyContinue
```

```bash
# macOS / Linux
uname -srm; sw_vers 2>/dev/null | head -2
command -v python3 uv git; command -v brew
ls -d "/Applications/Google Chrome.app" 2>/dev/null
lsof -nP -iTCP:8766 -iTCP:8767 -iTCP:8768 -iTCP:8769 -sTCP:LISTEN
```

判定规则：

- **端口已在听** → 这台机器可能已经装过（进 S2 直接自检，别重装）。
- **缺 `uv`** → 先装：`curl -LsSf https://astral.sh/uv/install.sh | sh`（mac）或 `irm https://astral.sh/uv/install.ps1 | iex`（Win）。
- **缺 Python 3.10+** → Win 用 `winget install Python.Python.3.12`；mac 用 `brew install python@3.12`。
- **缺 Chrome** → 与 human_browser / human_dom / agent_browser 相关的能力会 `unavailable`，但 core 工具照常可用。装 Chrome 是**人类选择**（浏览器登录态属于人）。

---

## S1 · 装设备桥（选一种角色）

> 原则：**一个平台一个端口**（win 8766 / mac 8767 / android 8768 / ios 8769），同机多桥互不冲突。
> 所有 setup 脚本都幂等；重复跑只会修，不会破坏既有环境。

### Windows 主机 → `win-device`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File platforms\windows\scripts\setup-windows.ps1
```

- **不需要管理员**：只有防火墙规则需要 admin；失败只 WARN，代价是「别的机器连不进来」，本机不受影响。
- 脚本**没有 `param()` 块**，全程只有**一处** `Read-Host`（Tailscale 刚被脚本装上、需要人去登录时，`setup-windows.ps1:116`）——**Tailscale 已装且已登录 = 全程无人值守可重跑**。
- `$env:ATB_WIZARD_MANAGED="1"` 只作用于那一处：不等待回车，而是直接 `exit 1` 让上层（wizard）看到失败。**它不是静默模式开关。**
- 产物：`platforms/windows/server/.venv` + 计划任务 `MCP-WinDevice` + 8766 监听。

### macOS 主机 → `mac-device`

```bash
bash platforms/macos/scripts/setup-macos.sh
```

- **绝不要用 `sudo` 跑**（brew 会拒绝）；brew 自己需要时它会交互提示。
- 脚本**没有任何 `ATB_*` 开关、也没有 `read` 阻塞**：`set -euo pipefail` + ERR trap，任何步骤失败立即带行号退出；Tailscale 未登录时会打印「去菜单栏 Login 后重跑」并 exit 1。
- **TCC 权限必须人工**（见 S5）：要把 **`Python.app` bundle** 拖进「辅助功能」与「屏幕录制」，**不是** venv 里的 `python3` 符号链接（macOS 会拒绝 CLI 二进制）；Automation 是首次调用新 app 时点 Allow。
- 产物：`platforms/macos/server/.venv` + LaunchAgent `cc.metahub.mac-device` + 8767 监听。

### Android 设备（宿主是 Win 或 mac）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File platforms\android\scripts\setup-android.ps1
```
```bash
bash platforms/android/scripts/setup-android.sh
```

非交互开关（wizard 场景用，agent 也可直接用）：

| 环境变量 | 取值 | 作用 |
|---|---|---|
| `ATB_ANDROID_MODE` | `usb` / `wireless` / `hybrid` | 跳过模式选择 |
| `ATB_ANDROID_REUSE_CONFIG` | `1` | 复用已有 `~/.atb-android/config.toml`，跳过全部交互 |
| `ATB_ANDROID_ADB` | adb 绝对路径 | adb 不在 PATH 时指定 |

**手机侧必须人类做**（agent 做不到）：开发者选项 → USB 调试 → 插线后手机上点「允许 USB 调试」；无线模式还要在手机上读配对码并允许配对。

### iOS 设备（宿主必须是 macOS）

```bash
bash platforms/ios/scripts/setup-ios.sh
```

- 前置：完整 Xcode（不是只有 CLT）、设备已信任、开发者模式已开、UI Automation 已开 —— **这四项都要人类操作**，见 [`docs/platforms/ios.md`](platforms/ios.md)。
- 逐台设备引导：`bash platforms/ios/scripts/ios-device-prep.sh <UDID>`（它会一步步告诉你/用户该在手机上点什么；非交互场景加 `NONINTERACTIVE=1`，但**那只是跳过等待，不能代替人工操作**）。
- 免费 Apple ID 的 WDA 签名 **7 天过期**，仓库自带续签脚本（`refresh-wda-cert.sh`），但首次部署仍要人跑一次 `xcodebuild`。

---

## S2 · 自检（装完立刻验，别靠感觉）

```bash
# 1) 端口在听（mac/linux）
lsof -nP -iTCP:8766 -sTCP:LISTEN
# Windows
Get-NetTCPConnection -State Listen -LocalPort 8766
```

```
# 2) 健康探针（仅 win/mac 有 /health；android/ios 无）
GET http://127.0.0.1:8766/health      → {"status":"ok"}
```

```
# 3) MCP 工具清单（唯一权威）
list_capabilities()  → {"capabilities":[{id:"core", status:"enabled", tools:[...]}, ...]}
```

判据：

- `core` 的 `tools` 数量应为 **win 44 / mac 43 / android 31 / ios 30**（含 `list_capabilities` 自身）。对不上说明 venv 装错或跑的是旧代码。
- `agent_browser` / `human_browser` / `vision` 的 `status` 可能是 `unavailable`（缺 Chrome / Node / rapidocr）。**这是正常的渐进披露，不要为了它反复重装。**

---

### 共享设备：租约是强制的

- 多 agent 共用一台设备时，先 `acquire(holder_name="<你的名字>")`；租约**绑定你的 MCP session**。
- 拿不到就说明别人持有：返回 `{ok:false, reason:"device_leased", current_holder, auto_release_in_seconds}` —— 等它过期、或让对方 `release`、或换一台设备。
- 每次设备调用（**包括 browser / vision / human_dom**）都会自动续租；**10 分钟无设备调用**才释放。
- 断线重连后 session 变了：用同一个 `holder_name` 再 `acquire` 一次即可重绑。
- 没人持有时谁都能用（不会自动加锁）；`get_status` / `list_devices` / `list_capabilities` 永远可调用。

---

## S3 · 装 skill（让未来的你会用这台设备）

**如果你走的是 `agent-fleet setup` 向导**：装完 server、验完工具后，它**不猜你用的是哪个客户端**（harness 枚举不完），而是写一份交接物并在屏幕上提示：

- `~/.fleet/skills-handoff.md` / `.json`：列清要哪些 skill、每个的**绝对源路径**，以及一句指令 —— 「放进**你自己**加载技能的位置，然后重启会话」。落地由 agent 按自己的 harness 约定完成（Claude Code `~/.claude/skills/`、DeepSeek Harness `~/.dsh/skills/`，其它按各自文档或直接读 `SKILL.md`）。
- 想让它**代劳**：`agent-fleet setup --skills-target <dir>`。
- 不想生成交接物：`--no-skills`；只想看计划不写盘：`--dry-run`。


**手动或 agent 自主安装**（跨平台、幂等；`--platform` 决定装哪一套）：

```bash
python3 scripts/install_skills.py --platform win-device     # 或 mac-device / android-device / ios-device
```

它会安装（win/mac 是 4 个，android/ios 是 1 个）：

| skill | 作用 | 适用 |
|---|---|---|
| `using-win` / `using-mac` / `using-android` / `using-ios` | **设备使用规范**：坐标空间、权限、长任务、失败表 | 全部 |
| `using-human-browser` | 真人身份浏览器：什么时候用、怎么不留下自动化痕迹 | win/mac |
| `using-human-dom` | **DOM 扩展的启用两层模型 + 排错**（本手册 S4 的详细版） | win/mac |
| `using-vision` | 无障碍树失效时的 OCR/模板像素定位（human_dom 的兜底） | win/mac |

常用参数：

```bash
python3 scripts/install_skills.py --list                     # 看每个平台会装哪些 + 源目录
python3 scripts/install_skills.py --platform win-device --dry-run
python3 scripts/install_skills.py --platform win-device --target ~/.claude/skills   # 显式目标
python3 scripts/install_skills.py --platform win-device --with-agent-browser        # 加 Playwright 那套
```

目标目录自动探测顺序：`$FLEET_SKILLS_DIR` → `<repo>/.dsh/skills`（存在时）→ `~/.dsh/skills` → `~/.claude/skills`。
**Windows 没有开启开发者模式时，符号链接会失败并自动降级为复制**（复制后仓库更新不会自动生效，需 `--force` 重跑）。

验证：目标目录下应出现对应 `using-*` 子目录，每个含 `SKILL.md`；agent 重开会话后技能目录应能列出它们（Claude Code 重启会话；DSH 会自动热加载）。

---

## S4 · human_dom provisioning（human_browser 的 DOM 层）

### 先理解架构（决定你该装什么）

human_browser 是**三层递进**的操作架构，越往下越准、越省 token：

| 层 | 能力 | 谁来装 | 何时用 |
|---|---|---|---|
| ① DOM（最准、0 token） | `human_dom_locate/tap/fill/status/focused` | **需要一次性 provisioning（本步）** + 首次开 profile 时自动装扩展 | 标准表单、有文字/aria/placeholder 的元素 |
| ② OCR（~1px） | `vision_locate` / `vision_tap` | 装 rapidocr 依赖即可（`status` 自报） | canvas、自定义按钮、动态遮罩 |
| ③ LLM 目测（最贵） | `take_screenshot` + 自己看图 | 无需安装 | 前两层都失败 |

**找到元素的最优顺序永远是 DOM → OCR → LLM**；不要一上来就截图猜坐标。

### 一次性 provisioning（两条命令，跨平台通用）

```powershell
# Windows：建标记（host 级开关，决定 human_dom_* 工具注不注册）
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.fleet" | Out-Null
New-Item -ItemType File -Force -Path "$env:USERPROFILE\.fleet\human-dom-ready" | Out-Null
```

```bash
# macOS
mkdir -p ~/.fleet && touch ~/.fleet/human-dom-ready
```

然后**重启对应 server**（Win：`Restart-ScheduledTask -TaskName MCP-WinDevice` 或 `Stop-ScheduledTask`/`Start-ScheduledTask`；mac：`launchctl kickstart -k gui/$(id -u)/cc.metahub.mac-device`）。

> 为什么必须重启：能力框架在 **server 启动时**静态判定 marker，运行期不动态增删工具。
> 也可以跑仓库里的 `install-human-dom-extension.ps1` / `.sh`（它们顺带写 marker），但对 agent 来说 `touch` 最快、副作用最小。

### ⚠️ 两种 profile，命运完全不同（最容易踩的坑）

| profile 传什么 | 扩展怎么装 | 结果 |
|---|---|---|
| **专用持久 profile**（`~/.fleet/<account-id>`） | `human_browser_open(profile=…)` **自动**：auto-bake 副本 → 起 Chrome 带临时 debug 端口 → CDP `Extensions.loadUnpacked` → 写 `loaded.json` | 零 GUI 自动装好，返回 `human_dom.ok=true` |
| **留空 = 日常默认 Chrome** | **不会自动装**（代码对空 profile 直接短路，既不给 debug 端口也不调 CDP） | 要用默认浏览器 + DOM，只能人工 Load unpacked（见下） |

**所以：要 DOM 精度，就给一个专用 profile。** 真账号 operator 本来就该固定专用 profile（登录态跨 run 持久），两个目标一致。

> 全新专用 profile 首次连桥，Chrome 可能弹一次「本地网络访问」授权 —— 点「允许」即可。服务端已经用 `--disable-features=LocalNetworkAccessChecks` 尝试抑制这个 gate（多数 Chrome 版本不再弹），但**弹了就点允许**，这不是你的安装出错。

**只有「默认日常 Chrome 也要 DOM」时才需要人工**：跑 `platforms/windows/scripts/install-human-dom-extension.ps1 "<PROFILE>"`（或 mac 的 `.sh`），它做两件事 —— 生成 per-profile 扩展副本 + 写 marker，然后**打印** 6 步手动引导；按它说的在 `chrome://extensions` 开启开发者模式、Load unpacked 那个副本目录。这一步无法由 agent 代劳。

### 验证 + 首次自动装扩展

```
list_capabilities()                       → human_dom.status 应为 "enabled"，tools 里有 5 个 human_dom_*
human_browser_open(url="https://example.com", profile="~/.fleet/<account-id>")
                                          → 返回 human_dom.ok = true（server 已自动烤副本 + CDP 装扩展）
human_dom_status()                        → 该 profile installed=true, connected=true
human_dom_locate(query="Learn more", profile="~/.fleet/<account-id>")
```

**三条必须记住的事实**：

1. **扩展是 per-profile 的副本**，装进 `~/.fleet/human-dom-ext/<profile_id>/`；换 profile 要重新 `human_browser_open(profile=新串)`（幂等，自动装）。
2. **三处必须同一个 profile 串**：`human_browser_open(profile=X)`、`human_dom_*(profile=X)`。不传 = 操作日常默认 Chrome。
3. **不要再教用户开 `chrome://extensions` 手动 Load-unpacked**——Chrome 137+ 已禁用 `--load-extension`，v0.8.6 起由 server 侧 CDP `Extensions.loadUnpacked` 完成，零 GUI。

---

## S5 · 只有人类能做的 4 件事（明确交还，不要硬试）

| 场景 | 人类要做 | agent 的验证 |
|---|---|---|
| macOS GUI 权限 | 系统设置 → 隐私与安全性：辅助功能 / 屏幕录制 / 自动化，把 **Python 与 python3.12 两条都勾上** | `take_screenshot()` 返回非黑屏；`find_elements()` 有结果 |
| Android | 开发者选项 + USB 调试 + 手机弹窗点「允许」；无线模式读配对码 | `list_devices()` 里有设备且 `state=device` |
| iOS | 完整 Xcode、开发者模式、信任开发者证书、开 UI Automation、首次 `xcodebuild` 签 WDA | `pymobiledevice3 usbmux list` 有设备；`curl 127.0.0.1:18100/status` 返回 WDA 状态 |
| Tailscale / 跨机器访问 | 两台机器登录同一 tailnet，并允许 MagicDNS | `tailscale ping <device-host>` 出现 `via direct`/`via DERP` |

**不要**：用 `sudo` 跑 setup 脚本、替人类点系统弹窗、把密码/验证码写进日志、在非授权账号上跑 human_browser。

---

## S6 · 交接（给人类的一句话）

安装完成后，回答里应包含这四项，人类才知道下一步做什么：

```
1) 这台机器现在是：<win-device|mac-device|android-device|ios-device>，监听 <host>:<port>/mcp
2) 已装 skill：using-<x>（+ using-human-browser / using-human-dom / using-vision）
3) human_dom：enabled（5 个工具）｜或 unavailable（原因：缺 marker / 缺 Chrome）｜或未启用（你不需要真人浏览器）
4) 需要你做：<S5 里剩下的那一两件>；做完告诉我，我用 <验证命令> 复查
```

---

## S7 · 失败处理

| 症状 | 先查 | 处理 |
|---|---|---|
| 端口不在听 | venv 是否建成、计划任务/LaunchAgent 状态 | 重跑对应 setup 脚本（幂等）；Win 看 `Get-ScheduledTaskInfo -TaskName MCP-WinDevice` |
| `/health` 超时但端口在听 | 是否旧版 server（v0.8.5 前无 `/health`） | `python3 -m pytest platforms/tests -q` 确认仓库版本；重装 |
| `list_capabilities` 里 human_dom 一直 unavailable | marker 是否存在、server 是否重启过 | `Test-Path ~/.fleet/human-dom-ready` / `ls ~/.fleet/human-dom-ready`；重启后重查 |
| `human_browser_open` 返回 `human_dom.ok=false` | 是否缺 marker、Chrome 是否被其他进程锁住 | 先补 marker 重启；仍失败用 `take_screenshot` + `tap` 兜底，并在报告里写明 |
| `human_dom_status` 显示 `installed=true, connected=false` | 页面是否已导航、是否换了 profile | 重开 `human_browser_open(profile=…)`（幂等）或导航到目标页；**不要重装扩展** |
| `human_dom_locate` 返回 `suggest:"vision_locate"` | 元素在 canvas / 自定义控件 | 切 `vision_locate` + `tap`，不要反复 locate |
| 截图全黑 | macOS 屏幕录制权限 / Windows 锁屏 | 交人类（S5）；Windows 还需保持登录会话解锁 |
| `GET /health` 返回 404 | 你探的是 android / ios | 这两个平台是裸 `mcp.run()`，**没有 `/health`**，只能 TCP 探测 / 直接 `list_capabilities` |
| 自己写脚本连 MCP 报 `Server returned an error response` | 客户端 SDK 版本 | 用 `mcp<2`（仓库 `verify.py` 也是 1.x API）；`uv run --with "mcp<2"` |
| 自己写脚本连 `POST /mcp` 得到 502 | 本机系统代理拦截 | 设 `NO_PROXY` / `no_proxy` 排除设备主机与 `100.64.0.0/10,127.0.0.1,localhost` |
| 工具数与本手册不符 | `agent_browser` 的工具由**实际安装的 `@playwright/mcp` 版本**决定（实测某机 29 个，静态清单 27 个） | 只信 `list_capabilities()`；静态常量仅用于文档口径 |
| skill 装完 agent 看不到 | 目标目录不是该 agent 的技能根、会话缓存 | 用 `--target` 指到正确目录；重启会话 |

---

## 附：最小成功路径（复制即可）

```bash
# 在仓库根；假设目标：把这台 Windows 变成 win-device，并让 agent 能用真人浏览器
powershell -NoProfile -ExecutionPolicy Bypass -File platforms\windows\scripts\setup-windows.ps1
python3 scripts/install_skills.py --platform win-device
# 建 human_dom marker（PowerShell）
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.fleet" | Out-Null
New-Item -ItemType File -Force -Path "$env:USERPROFILE\.fleet\human-dom-ready" | Out-Null
# 重启 server 服务
Restart-ScheduledTask -TaskName MCP-WinDevice -ErrorAction SilentlyContinue
# 验证
#   list_capabilities()  → core 44 + human_dom enabled(5 tools)
#   human_browser_open(url="https://example.com", profile="~/.fleet/demo") → human_dom.ok=true
#   human_dom_status()   → installed=true / connected=true
```
