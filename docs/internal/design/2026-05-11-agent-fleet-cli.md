# Design · agent-fleet CLI（v0.5 wizard 化部署）

> _Internal development artifact — kept for historical record, not user-facing documentation. See [docs/internal/README.md](../README.md)._

**作者**: brainstorming 过程产物（Claude + 用户协同）
**日期**: 2026-05-11
**状态**: 待用户最终批准 → 转 writing-plans 出实施计划
**实施目标版本**: v0.5.0

---

## 0. 上下文与动机

当前 `agent-test-bench`（即将重命名为 `agent-fleet`）已支持 Windows / macOS / Android 三平台，覆盖 31+33+20 个 MCP 工具，并完成了 SSE→streamable-http 的稳定性迁移。但**部署体验复杂度**远高于实际工程量：

- 设备管理员需要读 docs/platforms/<plat>.md，按平台跑不同 setup 脚本，再按系统设置点 GUI 权限
- Agent 操作员需要手动改 `~/.claude.json` 或跑 `install-agent-side.py`
- AI Agent 通过 skill 了解使用方式（已稳定）
- 项目贡献者读 `install-pattern.md` 添加新平台（已稳定）

**重灾区是前两类用户**：从 0 到能用 4-6 步、跨多个 README，且 OEM 差异 + macOS 权限 + ADB 授权各种坑都靠用户自己踩。

**用户视野**（决定了产品定位）：

> 未来的 agent 应该像人类一样拥有自己的电脑、手机、pad 等等。`agent-fleet` 是给 agent **配齐物理身体**的工具——把"接入一台新设备"压成一行命令。

---

## 1. Goals / Non-goals

### Goals

| | 描述 |
|---|---|
| G1 | **单设备 wizard**：在被装机器跑 `uvx agent-fleet setup` 即完成 MCP server 安装 + 服务自启 + 健康检测 + 操作引导 + 配置片段生成 |
| G2 | **多角色支持**：每台机器可同时担当多种角色（如 Win11 上既装 winpc-gui，也装 android-bridge） |
| G3 | **3 host OS**：Windows、macOS、Linux（Linux 只可装 android-bridge） |
| G4 | **6 个 agent 框架配置生成**：Claude Code、Cursor、Cline、OpenClaw、Antigravity、Hermes |
| G5 | **设备变体感知**：Android 国行 ROM 各家路径不同 / macOS 版本 GUI 不同 / Windows 10 vs 11 差异，文案分变体处理 |
| G6 | **操作引导自动化**：装完不放手——交互式带用户开权限、授权 ADB，每步带 verification probe |
| G7 | **零前置依赖**：`install.sh` / `install.ps1` 一键脚本会先装 uv，再跑 wizard |
| G8 | **幂等**：重复跑 wizard 自动检测已有部署、安全 modify/reuse/uninstall |

### Non-Goals

| | 不做 |
|---|---|
| NG1 | **不做跨机器 SSH 编排**——每台机器各自跑一次 wizard，不试图从一台机管别的机 |
| NG2 | **不自动改 agent client 配置**——默认只打印 snippet，用户自己 paste（默认安全；很多 device host 上没装 Claude Code） |
| NG3 | **不自动装 Tailscale**——只检测 + 提示 + 给教程链接 |
| NG4 | **不做 Web UI**——v1 是 CLI/TUI 化 wizard，未来如有需要再加 |
| NG5 | **不做 v0.5 iOS bridge 的实际安装**——只在 wizard 中作为"v0.6+ planned"占位 |

---

## 2. 命名与分发

### 仓库 / 包 / 命令

| 维度 | 名称 |
|---|---|
| GitHub repo | `metahub-tech/agent-fleet`（**rename** from `agent-test-bench`，旧 URL 自动 redirect） |
| PyPI package | `agent-fleet` |
| Python module（import） | `fleet` |
| CLI 命令 | `agent-fleet`（标准）或 `fleet`（别名） |
| 一键执行 | `uvx agent-fleet setup` |

### 分发策略

| 阶段 | 分发 | 时间窗口 |
|---|---|---|
| v0.5.0-alpha | git URL install (`uvx --from git+https://github.com/metahub-tech/agent-fleet@v0.5.0-alpha agent-fleet setup`) | 内部团队 dogfood |
| v0.5.0-beta | private PyPI mirror（metahub 自建 index 或 GitHub Releases artifact） | 内部 + 受邀 beta |
| v0.5.0 GA | 公开 PyPI；维持 git URL fallback | 内部稳定后释放 |

**注意**：先 private 跑稳，公开发布以验证后的实际信号为前提（端到端跑过 3 host OS × 多框架）。

---

## 3. 总体架构

```
agent-fleet/                          # 仓库根
├── README.md
├── install.sh                        # 一键脚本（Linux/macOS）
├── install.ps1                       # 一键脚本（Windows）
├── pyproject.toml                    # agent-fleet CLI 包
├── cli/
│   └── src/fleet/                    # Python module
│       ├── cli.py                    # uvx 入口，命令分发
│       ├── wizard.py                 # 交互主流程
│       ├── detect.py                 # OS / 现有部署检测
│       ├── verify.py                 # 安装后健康检查
│       ├── installers/               # 每个 (OS, role) 一个 module
│       │   ├── base.py
│       │   ├── windows.py            # WindowsTestPC + WindowsAndroidBridge
│       │   ├── macos.py              # MacosDesktop + MacosAndroidBridge + MacosiOSBridge*
│       │   └── linux.py              # LinuxAndroidBridge
│       ├── frameworks/               # 6 个 agent 框架配置生成器
│       │   ├── base.py
│       │   ├── claude_code.py
│       │   ├── cursor.py
│       │   ├── cline.py
│       │   ├── openclaw.py
│       │   ├── antigravity.py
│       │   └── hermes.py
│       └── guidance/                 # YAML 文案 / variant tables
│           ├── android_dev_options.yaml
│           ├── android_usb_debug.yaml
│           ├── android_wireless_pair.yaml
│           ├── macos_accessibility.yaml
│           ├── macos_screen_recording.yaml
│           ├── macos_automation.yaml
│           ├── macos_full_disk_access.yaml
│           ├── windows_developer_mode.yaml
│           └── ...
│   └── tests/
├── platforms/                        # 保留现状；installer 通过 subprocess 调
└── docs/                             # 现有文档作为"高级用户参考"保留
```

**两层关系**：
- **wizard layer**：纯 Python；用户面向；只负责"问问题 + 调对的脚本 + 渲染配置"
- **platform layer**：现有的 `setup-{platform}.{ps1,sh}` 文件，作为 wizard 的 backend；老手仍可直接跑

---

## 4. Wizard 交互流程（端到端）

### [1] Banner + 现场探测

```
🚢  agent-fleet v0.5.0
    OS         : macOS 12.7.6 (Intel)
    uv         : 0.1.45 ok
    Tailscale  : logged in as <user>@<tailnet>
    已有部署    : (无)  /  (已有 macbox-gui v0.3.0 HTTP :8767)
```

### [2] 角色多选（仅显示当前 OS 可选）

```
? 这台机器要扮演哪些角色？（空格切换、回车确认）

macOS:
  [x] macbox-gui      作为可被 agent 驱动的 Mac 桌面（端口 8767）
  [x] android-bridge  通过 USB / Wireless ADB 桥接 Android 手机（端口 8768）
  [-] ios-bridge      iOS 设备桥（v0.6+ 计划中，暂不可选）

Windows:  [winpc-gui, android-bridge]
Linux:    [android-bridge]
```

### [3] 网络模式

```
? 这台机器的 agent client 在哪？
  ⦿ 同一 WiFi / 同一局域网  （直连）
  ⦿ 异网 / 已用 Tailscale   ← 推荐
```

选 Tailscale 时检测 `tailscale status`；缺则**只提示安装指令 + 文档链接**（不自动装）。

### [4] 顺序安装（流式输出）

```
[macbox-gui] 装 Python 3.12 …………………… ✓
[macbox-gui] venv + deps …………………… ✓
[macbox-gui] launchd plist ……………… ✓
[macbox-gui] 启动服务 ………………… ✓ (PID 5891)
[android-bridge] platform-tools ……… ✓
[android-bridge] 询问 ADB 模式：USB / Wireless / Hybrid
    → USB
[android-bridge] config.toml ………… ✓
...
```

任一步失败 → 暂停 + 显示 diagnostic + 询问 retry / skip / abort。

### [5] 健康检测

```
🔬 Verify
   macbox-gui   /mcp HTTP 400  ✓   list_tools = 31 ✓
   android-gui  /mcp HTTP 400  ✓   list_devices = 0  ⚠ (尚未授权)
```

未授权设备 → flag 不报错；操作引导阶段会引导用户授权后再验证。

### [6] 操作引导（critical UX）

按 OS / 角色组合，wizard 把所有"需要在物理设备上手动做的事"列成步骤，每步：

1. 清晰指令（默认文案 + variant 表）
2. **回车继续**（用户操作完了之后）
3. **自动 verification probe**（能验则验）
4. 失败 → 显示具体错误 + 重试 / 跳过

**示例 - macbox-gui 完整引导**：

```
🔓 操作引导（macbox-gui）

Step 1/4: 辅助功能（Accessibility）
  打开 System Settings → 隐私与安全性 → 辅助功能
  拖入 .app: /usr/local/opt/python@3.12/Frameworks/Python.framework/
                 Versions/3.12/Resources/Python.app
  ↩ 完成后回车继续

  → wizard 跑 pyautogui.position() …… ✓ pass

Step 2/4: 屏幕录制
  同样拖入 Python.app
  ↩

  → wizard 跑 ImageGrab.grab() …… ✓ pass (screen 2880x1800)

Step 3/4: 自动化
  这一步无需现在做。下次 agent 调 run_applescript 控制其他 app 时，
  macOS 会自动弹窗"允许 Python 控制 System Events"——点同意即可。
  ↩

Step 4/4: 完全磁盘访问 (可选)
  如果 agent 需要读 ~/Documents 或 ~/Library/Logs，
  在 System Settings → 完全磁盘访问 也加入 Python.app。
  ↩

🎉 macbox-gui 引导完毕
```

**示例 - android-bridge 引导（含 variant 表）**：

```
🔓 操作引导（android-bridge）

Step 1/4: 在手机上开启开发者选项
  默认路径：设置 → 关于手机 → 连按"版本号" 7 次
  各品牌差异：
    华为 / HarmonyOS / EMUI ……… 设置 → 关于手机 → 连按"版本号"
    小米 / MIUI / HyperOS …………… 设置 → 我的设备 → 全部参数 → 连按"MIUI 版本"
    Samsung / One UI ……………… Settings → About phone → Software info → tap Build number 7×
    OPPO / realme / ColorOS …… 设置 → 关于本机 → 连按"版本号"
    vivo / OriginOS / Funtouch  设置 → 我的设备 → 连按"软件版本"
    Pixel / 原生 AOSP …………… Settings → About phone → tap Build number 7×
    其他/找不到 ……………………… 找带"版本号"/"Build number"的字段连按 7 次
  ↩ 看到"已开启开发者选项"提示后回车

Step 2/4: 开发者选项中开 USB 调试
  ↩

Step 3/4: USB 插电脑，手机弹"是否允许 USB 调试"
  勾选"始终允许此电脑" + 点"确定"
  ↩

  → wizard 跑 adb devices …… ✓ 看到 MQS0219A10009471 (VOG-AL00)
  → wizard 跑 adb shell getprop ro.product.manufacturer …… HUAWEI
    （识别品牌，无需进一步引导）

Step 4/4: (可选) 切换到 Wireless Debugging
  ↩ 跳过 / 是

🎉 android-bridge 引导完毕
```

`guidance/*.yaml` 是这些变体表的数据源，社区可贡献新品牌 / 新 OS 版本。

### [7] 框架配置生成

```
? 你的 agent 用哪些框架？（多选）
  [x] Claude Code        (~/.claude.json)
  [x] Cursor             (~/.cursor/mcp.json)
  [ ] Cline (VSCode)     (settings.json → cline.mcpServers)
  [ ] OpenClaw           (~/.openclaw/ 或 CLI)
  [ ] Antigravity        (~/.gemini/antigravity/mcp_config.json)
  [ ] Hermes             (~/.hermes/config.yaml)
```

每个选中的框架：
- 渲染对应字段格式（type / transport / httpUrl 自动适配）
- 完整 snippet 带语法高亮显示
- **默认动作 = 打印**（用户复制 paste）
- 也可"写到 `./agent-fleet-config.<framework>.<ext>`"作为存盘选项
- **不做** auto-merge（因为很多 device host 上根本没装那个 agent）

**Claude Code snippet 示例**：

```json
{
  "mcpServers": {
    "macbox-gui": {
      "type": "http",
      "url": "http://test-macpro-12:8767/mcp"
    },
    "android-gui": {
      "type": "http",
      "url": "http://test-macpro-12:8768/mcp"
    }
  }
}
```

**OpenClaw snippet 示例**：

```json
{
  "mcp": {
    "servers": {
      "macbox-gui": {
        "transport": "streamable-http",
        "url": "http://test-macpro-12:8767/mcp"
      }
    }
  }
}
```

**Antigravity snippet 示例**（使用 `httpUrl` 字段）：

```json
{
  "mcpServers": {
    "macbox-gui": { "httpUrl": "http://test-macpro-12:8767/mcp" }
  }
}
```

**Hermes snippet 示例**（YAML）：

```yaml
mcp_servers:
  macbox-gui:
    url: http://test-macpro-12:8767/mcp
```

### [8] 总结面板

```
🎉 Done!

  This machine（设备端）
    Tailscale hostname : test-macpro-12
    Endpoints:
      macbox-gui   →  http://test-macpro-12:8767/mcp  (31 tools)
      android-gui  →  http://test-macpro-12:8768/mcp  (20 tools, no device yet)

  Agent client 配置（你刚生成的 snippet）
    Claude Code  💾 已保存到 ./agent-fleet-config.claude.json
                   (上面 ↑ 也打印了；拿到 agent 主机上 paste 到 ~/.claude.json)
    Cursor       💾 已保存到 ./agent-fleet-config.cursor.json

  服务管理
    launchctl list | grep cc.metahub
    launchctl kickstart -k gui/$(id -u)/cc.metahub.macbox-gui
    tail -f ~/.../platforms/macos/logs/macos-gui.log

  下次想改？再跑一次 uvx agent-fleet setup（幂等）
```

---

## 5. 内部抽象

### Installer ABC

```python
class BaseInstaller(ABC):
    role_id: str                  # "macbox-gui" / "android-bridge"
    display_name: str
    port: int

    @abstractmethod
    def is_supported_on(self, os_info: OSInfo) -> bool: ...

    @abstractmethod
    def preflight(self) -> list[str]:
        """返回缺失依赖列表"""

    @abstractmethod
    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        """实际 shell-out 调 setup-{platform}.{ps1,sh}；
           流式 yield 事件供 wizard 渲染"""

    @abstractmethod
    def verify(self) -> VerifyResult: ...

    @abstractmethod
    def guidance_steps(self) -> list[GuidanceStep]: ...
```

新平台 / 新角色加一个 file 即可。

### FrameworkConfig ABC

```python
class BaseFrameworkConfig(ABC):
    framework_id: str             # "claude-code" / "openclaw" / ...
    display_name: str
    config_format: Literal["json", "yaml"]
    config_path_template: str     # "~/.claude.json"

    @abstractmethod
    def render_entry(self, role: ServerRole) -> dict:
        """role = (name, url, transport='streamable-http')
        返回 framework-specific 的 entry dict"""

    @abstractmethod
    def render_full_snippet(self, entries: list[ServerRole]) -> str:
        """完整可粘贴的 snippet（含 mcpServers 包裹层）"""

    def cli_alternative(self) -> str | None:
        """如有 CLI 等价命令（openclaw mcp set / claude mcp add）则返回"""
```

### GuidanceStep ABC

```python
@dataclass
class GuidanceStep:
    title: str
    default_description: str
    variants: dict[str, str] = field(default_factory=dict)
    variant_label: str = ""           # "Android 品牌" / "macOS 版本"
    verify_fn: Callable | None = None
    verify_label: str = ""            # "wizard 跑 X，期望 Y"
```

变体表存 YAML，加载时映射到这个 dataclass。

---

## 6. 设备变体（variants）数据 schema

YAML 格式，举 `android_dev_options.yaml` 为例：

```yaml
step:
  title: "开启开发者选项"
  default_description: |
    设置 → 关于手机 → 连按"版本号" 7 次
  variant_label: "Android 品牌"
  variants:
    huawei_harmonyos:
      label: "华为 / HarmonyOS / EMUI"
      description: '设置 → 关于手机 → 连按"版本号" 7 次'
    xiaomi_miui:
      label: "小米 / MIUI / HyperOS"
      description: '设置 → 我的设备 → 全部参数 → 连按"MIUI 版本" 7 次'
    samsung_oneui:
      label: "Samsung / One UI"
      description: 'Settings → About phone → Software information → tap "Build number" 7×'
    oppo_coloros:
      label: "OPPO / realme / ColorOS"
      description: '设置 → 关于本机 → 连按"版本号"'
    vivo_originos:
      label: "vivo / OriginOS / Funtouch"
      description: '设置 → 我的设备 → 连按"软件版本"'
    pixel_aosp:
      label: "Pixel / 原生 AOSP"
      description: 'Settings → About phone → tap "Build number" 7×'
    fallback:
      label: "找不到 / 其他"
      description: '通用：找到带"版本号"或"Build number"字段连按 7 次'
```

加新品牌 / OS 版本只需扩这个 YAML，不动 Python。

---

## 7. 一键安装脚本

### `install.sh`（Linux / macOS）

```bash
#!/usr/bin/env bash
# 用法：curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash
set -e

if ! command -v uv >/dev/null 2>&1; then
    echo "uv 未装，正在装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

exec uv tool run agent-fleet setup
```

### `install.ps1`（Windows）

```powershell
# 用法：powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv 未装，正在装..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

uv tool run agent-fleet setup
```

两脚本只做"装 uv + 跑 wizard"，**不重复 wizard 逻辑**。

---

## 8. 迁移与向下兼容

| 项 | 处理 |
|---|---|
| GitHub repo rename | `agent-test-bench` → `agent-fleet`；GitHub 自动 redirect 旧 URL ≥ 12 个月 |
| `install-agent-side.py` | 保留 1 个 transition release，跑时打印 deprecation warning 指向 `uvx agent-fleet setup`；v0.6 删 |
| launchd / Task Scheduler labels | 不动（保持 `cc.metahub.macbox-gui` / `MCP-WindowsGui` / `MCP-AndroidGui`），避免破坏现有部署 |
| 现有 setup-{platform}.{ps1,sh} | 保留作为 wizard backend；老手仍可直接跑 |
| 老文档 docs/platforms/<>.md | 保留作为"高级用户手册"；README 增加"新手用 wizard"和"老手用脚本"两条入口 |
| 现有 ~/.claude.json `type=sse` | wizard 不主动改 agent 客户端配置；用户感知到老 SSE 端点 404 → 自己重跑 wizard 重新生成 snippet |

---

## 9. 测试策略

| 层 | 工具 | 内容 |
|---|---|---|
| 单元 | pytest | wizard.py 状态机；frameworks 渲染输出 string match；installers 的 preflight 逻辑 |
| 集成 | dry-run 模式 | `--dry-run` 标志：跑完整 wizard 但不真改文件 / 不调 setup 脚本，只输出 "would do X" |
| 端到端 | 手动 + 录屏 | 真实 Win11 + Mac + Linux + P30 Pro 各跑一遍 wizard 验收 |

dry-run mode 是关键——CI 里 lint + dry-run 跑 wizard 确保流程不崩；端到端验证靠人。

---

## 10. 开放问题（implementation 阶段决定）

| Q | 选项 | 倾向 |
|---|---|---|
| TUI 库选型 | `questionary` (prompt-toolkit based) / `rich.prompt` / 自写 | questionary，跨平台 prompt UI 最成熟 |
| 现有 setup 脚本如何 invoke | subprocess 流式读 stdout / 直接 import-as-module | subprocess + 流式 stdout（PowerShell 脚本无法 import） |
| 多角色冲突（如端口重叠） | 拒绝 / 自动改端口 | 拒绝并提示用户先卸老角色 |
| Wizard 启动时是否需要 sudo/admin？ | 总需要 / 仅在写 launchd plist 时需要 / 总不需要 | 总不需要——sudo 提权由具体 setup 脚本决定（macOS launchctl 不需，Windows New-NetFirewallRule 需）|
| 国际化（i18n） | 全双语 / 仅中文 / 跟系统语言切 | v0.5 文案中文为主（运维主体），关键技术词保留英文；i18n 框架 v1.0 再考虑 |

---

## 11. 实施里程碑

| 版本 | 范围 | 完成判据 |
|---|---|---|
| v0.5.0-alpha | wizard MVP：macOS + Windows installer；Claude Code + Cursor 配置生成 | Mac 上 `uvx --from git+... agent-fleet setup` 端到端跑完 |
| v0.5.0-beta | + Linux installer（android-bridge）+ Android 操作引导（含 variant 表）+ Hermes/Antigravity/OpenClaw/Cline 配置生成 | 三个 host OS 各跑过一次 |
| v0.5.0-rc | + 一键 install.sh/.ps1 + Tailscale 检测/提示 + dry-run + i18n（中文为主） | curl-pipe 一键完成在 fresh VM 上测试通过 |
| v0.5.0 GA | private PyPI 发布；GitHub repo rename；transition release of install-agent-side.py | 内部 ≥ 1 周稳定运行 |
| v0.5.1 | 公开 PyPI；变体 YAML 社区贡献模板；docs 重组（新手 wizard / 老手脚本两入口） | 公开仓库 README + uvx 命令在外部测试通过 |

---

## 12. 不影响范围（保证不破坏现有部署）

| 项 | 保持不变 |
|---|---|
| MCP server 端口 8766/8767/8768 | 不动 |
| MCP transport（streamable-http /mcp） | 不动（已在 v0.4.x 迁移完毕） |
| launchd label / Task Scheduler 任务名 | 不动 |
| `~/.atb-android/config.toml` | 不动 |
| skills 的 SKILL.md 内容 | 不动；wizard 不替代 skills 的作用（agent 仍读 skill 学使用方式） |
| `platforms/*/server/*.py` server 源码 | 不动；wizard 只是部署 wrapper |

---

## 13. 设计签名

- **决策汇总**：包名 `agent-fleet`、Python module `fleet`、CLI 命令 `agent-fleet`、PyPI 先 private 再公开、GitHub repo rename
- **首要受众**：设备管理员（一行命令 + 操作引导）
- **次要受众**：Agent 操作员（拿生成的 snippet 自己 paste）、AI Agent（skills 保持）、贡献者（加平台 = 加 1 文件 + 1 YAML）
- **设计核心 trade-off**：用 Python wizard 这一层把"散在 5 个文档 + 6 个框架配置格式"统一抽象，加 1 层间接换取 N 倍 UX 简化；现有 setup 脚本作为 backend 保留以让老手路径不失效
- **后续 spec**：iOS bridge v0.6+（macOS host，WebDriverAgent）、跨设备 agent 协调 v0.7+
