# Install Pattern · 开发者基准

新接手仓库的人**先读这一页**，搞清楚装什么、装到哪、为什么这么分。再去看任何 platform-specific 的文档前，掌握这个心智模型能避开 90% 的混乱。

---

## 1. 一个项目，两个角色，两条安装路径

`agent-test-bench` 总是涉及**两个机器**：

```
┌──────────────────────┐                             ┌──────────────────────┐
│  Agent Host          │ ──── Tailscale / Internet ──> │  Device Host        │
│  Linux/Mac/Win 开发机 │                             │  Win/Mac/Android/iOS │
│                      │                             │                      │
│  跑 Claude Code 等    │   MCP streamable-http       │  跑 MCP server      │
│  MCP client          │   ──────────────>           │  (FastMCP / 自写)   │
└──────────────────────┘                             └──────────────────────┘
        ↑                                                       ↑
   Agent 端安装：                                         设备端安装：
   ~/.claude.json + skill 软链                          setup-{platform}.{sh,ps1}
```

| 角色 | 装在哪 | 用什么 |
|---|---|---|
| **设备管理员** | 设备本机 | `platforms/<name>/scripts/setup-<name>.{sh,ps1}` |
| **Agent 操作员** | Agent 主机 | `scripts/install-agent-side.py --platform <name> --hostname <host>` |

> **同一个人扮演两个角色是最常见情况**——你自己又有测试机又有开发机，按"先设备 → 再 Agent"顺序走两遍。

---

## 2. 设备端：一行命令

跨进设备，clone 仓库，跑对应平台的 setup 脚本：

| 平台 | 命令 |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File platforms\windows\scripts\setup-windows.ps1` |
| macOS | `bash platforms/macos/scripts/setup-macos.sh` |
| Android (v0.4 计划) | `bash platforms/android/scripts/setup-android.sh` |
| iOS (v0.5 计划) | TBD（host 必须是 macOS）|

setup 脚本做的事大同小异：

1. 检查 / 安装 Tailscale
2. 检查 / 安装 Python（macOS 通过 brew，Windows 通过 winget）
3. 在 `platforms/<name>/server/.venv` 建虚拟环境装依赖
4. 注册自启服务（Windows Task Scheduler / macOS launchd LaunchAgent）
5. 验证端口监听 + 打印**操作员需要在系统设置里点的权限清单**（macOS GUI 测试机绕不过这一步）

详细每平台的细则见 [`docs/platforms/<name>.md`](platforms/)。

---

## 3. Agent 端：一行命令

在跑 Claude Code（或其他 MCP client）的开发机上：

```bash
# 进 agent-test-bench 仓库目录
cd ~/code/agent-test-bench    # 或你 clone 的位置

# 把一台设备的 MCP + skill 一起装好
python3 scripts/install-agent-side.py --platform mac-device --hostname mac-test
```

脚本会原子地做三件事：

1. **备份** `~/.claude.json` → `~/.claude.json.bak-<timestamp>`
2. **merge MCP 条目**到 `mcpServers` 段（不影响其他已存在的 MCP server）：
   ```json
   {
     "mcpServers": {
       "mac-device": { "type": "http", "url": "http://mac-test:8767/mcp" }
     }
   }
   ```
3. **建 skill 符号链接**：`~/.claude/skills/using-mac` → `platforms/macos/skills/using-mac`

幂等：同一命令重跑只报 "ok already exists"，不会破坏现有配置。

跑完之后：

```bash
# 重启 Claude Code 让 MCP 重新加载
/exit
# 然后再启动 Claude Code

# 验证
/mcp           # 应看到 mac-device [sse] connected
```

> **多设备**：每台设备跑一次 install-agent-side.py，`~/.claude.json` 会逐步累加 server 条目。

---

## 4. 目录契约

每个平台的 codebase 都是**自包含**的，落在 `platforms/<name>/` 下，子结构对所有平台一致：

```
platforms/<name>/
├── README.md                          # 平台速览：差异、工具表、目录布局
├── server/
│   ├── <name>_gui_mcp.py              # MCP server 主文件（FastMCP-based）
│   ├── requirements.txt               # Python 依赖
│   └── pyproject.toml                 # 包元信息
├── scripts/
│   ├── setup-<name>.{sh,ps1}          # 设备端一键安装
│   ├── _launch-<name>-gui.{sh,ps1}    # 自启脚本（被 launchd / Task Scheduler 调用）
│   └── diagnose.{sh,ps1}              # 排错脚本（可选；Windows 有，macOS v0.3 暂未补）
├── skills/
│   └── using-<shortname>/
│       └── SKILL.md                   # Agent 调用规范（坐标系、权限、长任务、failure 表）
└── examples/
    └── claude-settings.json           # MCP 客户端配置片段
```

**强约束**：

- 所有平台的工具命名共享 [Universal Tool Set](architecture.md) 公约：`take_screenshot`、`click`、`run_shell` 等同名跨平台
- 平台相关的工具命名带平台前缀或采用平台原生名：`run_powershell`（Windows）/ `run_zsh` + `run_applescript`（macOS）
- Agent 操作员 `~/.claude.json` 里的 server 名约定为 `<role>-<surface>`：`win-device`、`mac-device`、`android`、`iphone`

---

## 5. 添加新平台 · 范式

按这八步从零起手一个新平台桥（以未来要加的 `linux-gui` 为虚构示例）：

1. **建骨架**：`mkdir -p platforms/linux/{server,scripts,skills/using-linuxbox,examples}`
2. **port server**：从最近的平台（macOS 最近）port `<name>_gui_mcp.py`，把平台特定 API 替换掉（pyautogui 在 X11 也能用；shell 由 `run_zsh` 改 `run_bash`；`run_applescript` 替换为 `run_dbus` / 删除）
3. **port setup script**：从 setup-macos.sh 改造，brew 改 apt，launchd 改 systemd
4. **port skill**：从 using-mac 复制，把 macOS 特定坑（TCC 双 entry / FDA / `osascript` 责任链）替换为 Linux 等价物（X11 vs Wayland 的差异）
5. **port examples**：claude-settings.json 改 hostname + 端口
6. **写 README**：列工具差异表（与 macOS 比少了什么、多了什么）
7. **加 PLATFORMS dict**：在 `scripts/install-agent-side.py` 顶部 `PLATFORMS` 加一行
8. **更新顶层 docs**：`README.md` 状态表 + `docs/roadmap.md` 加版本节 + `docs/install-pattern.md` § 2 加命令行

完成后跑：

```bash
# 设备端
bash platforms/linux/scripts/setup-linux.sh

# Agent 端
python3 scripts/install-agent-side.py --platform linux-gui --hostname linux-test
```

应该和现有平台行为完全对称。

### 多模式接入：让 setup 脚本问，不要 hardcode

某些平台**接入路径不止一种**——典型是 Android 的 USB / Wireless / Hybrid 三模式。原则：

- setup 脚本**显式询问**模式，把选择权交给设备管理员
- MCP server 内部应当**模式无关**——只关心"设备已连接"，不关心通过什么协议连的
- 文档为每种模式给一段独立 walkthrough，不要让用户从一个模式的步骤里推导另一种

错误做法：在 setup-android.sh 第一行就 `adb push`，假设 USB 已插。
正确做法：先 `read -p "Mode? (wireless/usb/hybrid): "`，再分支。

这条原则也适用于：iOS（模拟器 vs 真机 + WebDriverAgent）、Linux（X11 vs Wayland），凡是接入方式有真实分歧的地方。

---

## 6. 不要做的事

| ❌ 反模式 | 为什么 |
|---|---|
| 改 `~/.claude/settings.json` 期望 MCP 生效 | Claude Code 只读 `~/.claude.json` 做 MCP；`settings.json` 里的 mcpServers 段会被静默忽略 |
| 把 skill 文件直接拷贝到 `~/.claude/skills/` | 改了就得手动同步；用 install-agent-side.py 建符号链接，仓库 pull 自动反映新版本 |
| 在 setup-macos.sh 里加 Windows-only 逻辑 | 平台 silo，每个 setup 只动自己平台的东西 |
| 给 setup 脚本加 sudo / Administrator 跑 | brew 拒绝 root；Windows Task Scheduler 装在用户级；MCP server 必须以登录用户身份跑 |
| 多个平台共用同一端口 | 8766/8767/8768/8769 各占一个，跨平台同时监听才能并行用 |
| 用 SSE 跑长任务（>60s） | v0.4.x 已迁到 streamable-http；新部署不要再选 sse 路径。原 SSE 长连接被 Tailscale DERP / NAT 中间盒切断后会留下 stale session_id，所有调用 `-32602` 直至重启 client。streamable-http 是 per-request stream，自动续连。 |

---

## 7. 推荐阅读顺序

新人按这个顺序读，1 小时内能完整掌握项目：

1. [`README.md`](../README.md) — 一页总览
2. **本页**（install-pattern.md） — 心智模型
3. [`docs/architecture.md`](architecture.md) — 三段式架构 + Universal Tool Set 设计哲学
4. [`docs/agent-host-setup.md`](agent-host-setup.md) — Agent 端配置细节（如果你只装 client）
5. [`docs/platforms/<你要装的平台>.md`](platforms/) — 设备端配置细节
6. [`platforms/<name>/skills/using-<name>/SKILL.md`](../platforms/) — agent 调用模式（如果你要写 prompts）
7. [`docs/roadmap.md`](roadmap.md) — 路线图（决定要不要为下一版贡献）

---

## 8. 故障定位

| 症状 | 第一步检查 |
|---|---|
| `/mcp` 显示 `failed` | URL 协议是 `http://` 不是 `https://`；hostname 拼写；防火墙是否开放对应端口 |
| `/mcp` 显示 connected 但调工具 hang | 设备端权限没批（macOS 辅助功能 / 屏幕录制；Windows 桌面会话锁屏）|
| Tool 返回 "schema not loaded" | 重启 Claude Code；新加的 MCP server 必须在启动时被加载 |
| Tool 都好，agent 不知道怎么用 | skill 没装上；运行 `ls -la ~/.claude/skills/`，应看到 `using-<name>` 软链 |
| 看不到当前 holder 是谁 | `acquire_<role>(holder_name="...")` 是 advisory 模型，工具仍能调用；用 `get_<role>_status` 查谁占着 |

平台特定排错见对应 `docs/platforms/<name>.md § 7`。
