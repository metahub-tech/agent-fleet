# Project Map · agent-fleet 运行地图（给 agent 用的操作层索引）

> **这份文件回答「我要动手时该去哪、跑什么、信谁」**，不重复结构清单。
> 结构清单见自动生成的 [`docs/internal/blueprint/MAP.md`](internal/blueprint/MAP.md)（模块）与 [`INTERFACE.md`](internal/blueprint/INTERFACE.md)（工具签名）；决策史见 [`DECISIONS/`](internal/blueprint/DECISIONS/)。
>
> **装载顺序**：根目录 [`AGENTS.md`](../AGENTS.md)（常驻指令）→ 本文件（操作层）→ blueprint `SNAPSHOT.md`（全貌快照）→ 按需深入。
>
> 维护约定：本文件是**手写**的稳定层（拓扑 / 命令 / 门禁 / 漂移登记），与代码结构解耦；结构性内容一律交给生成器，不在这里抄。最后核对基线见文末「核对记录」。

---

## 1. 这是什么、现在什么状态

agent-fleet 是**让 LLM agent 操作真实物理设备的 MCP 基座**：四个平台各有一个设备桥 MCP server，agent 通过统一工具集（`take_screenshot` / `tap` / `launch_app` / …）跨设备操作，切设备只是换一个 URL。定位介于「自动化测试基础设施」与「agent 的物理世界手和眼」之间。

| 事实 | 值 | 证据 |
|---|---|---|
| 最新 tag | `v0.8.13-alpha`（2026-07-07，指向 `52b23ba`） | `git tag -l --sort=-v:refname`、`git show -s v0.8.13-alpha` |
| main 相对 tag | **领先 9 个 commit**，最后一次提交 `aa6628b`（2026-08-01），此后未发版 | `git rev-list --left-right --count main...v0.8.13-alpha`、`git log -1` |
| 版本线性质 | alpha，接口未冻结，允许破坏性变更 | `README.md:4`、`CHANGELOG.md:58` |
| 平台 | Windows 10/11 · macOS 12+ · Android · iOS/iPadOS | `platforms/*/platform.toml` |
| 下一个版本节点 | `0.9.0` HarmonyOS（规划中，端口预留 8770） | `docs/roadmap.md:29`、`scripts/gen_docs.py:37-39` |
| 运行时形态 | 每平台一个 FastMCP（streamable-http），常驻服务 | `platforms/*/server/*_mcp.py` |
| 通信 | MCP over Tailscale（WireGuard mesh），本机/局域网可退化 | `docs/architecture.md:44-54` |
| 近期工作主题 | `human_dom` / `human_browser` / `vision` 的精度与零自动化痕迹；配套外部 AgentHub #100 的真机 E2E（公众号发文操作员场景） | `CHANGELOG.md:8-54`、`git log --oneline -10` |

> **这个仓库同时是自己的工具来源**：当前 DSH 会话里挂着的 `win-device` / `win-device-qjl` 两个 MCP，就是本项目的产物在本机/队友机器上的实例（`http://<host>:8766/mcp`）。改这里的 server 行为，会直接改变「我自己的手」的行为。

---

## 2. 运行时拓扑

```
┌──────────────────────┐        Tailscale / LAN        ┌────────────────────────────────────┐
│ Agent Host           │ ──── MCP streamable-http ───> │ Device Host                        │
│ (Linux/macOS/Windows)│      http://host:8766/mcp     │  ┌──────────────────────────────┐  │
│ Claude Code / Cursor │                               │  │ <platform>_device_mcp.py     │  │
│ DSH / Cline / …      │                               │  │  ├─ core（内联 @mcp.tool）    │  │
└──────────────────────┘                               │  ├─ capability 模块（可选）    │  │
                                                       │  └─ list_capabilities()        │  │
                                                       └──┬───────────────┬─────────────┘  │
                                                          │ USB/adb       │ USB/WDA        │
                                                     ┌────▼────┐    ┌─────▼─────┐          │
                                                     │ Android │    │ iOS/iPad  │          │
                                                     └─────────┘    └───────────┘          │
                                                       └────────────────────────────────────┘
```

**端口分配**（避开同机多桥冲突；8765 是 desktop-commander 社区惯例端口，可复用）：

| 平台 | 桥 id | 端口 | 设备主机 OS | 自启方式 |
|---|---|---|---|---|
| Windows 10/11 | `win-device` | 8766 | Windows | Task Scheduler |
| macOS 12+ | `mac-device` | 8767 | macOS | launchd（KeepAlive） |
| Android | `android-device` | 8768 | Windows / macOS / Linux | 宿主自启 |
| iOS / iPadOS | `ios-device` | 8769 | macOS（必须） | 宿主自启 + WDA daemon |
| HarmonyOS | `harmony-device`（规划） | 8770 | 任意 | — |

端口真源是各 `platforms/*/platform.toml` 的 `port`，`docs/architecture.md` 的端口表由 `scripts/gen_docs.py --write` 生成，**不要手改那段**。

---

## 3. 代码地图（谁负责什么）

| 位置 | 角色 | 关键点 |
|---|---|---|
| `platforms/<name>/server/*_mcp.py` | 该平台 MCP server 主入口 | core 工具**内联**在这个文件里；启动用 `platforms/common/_server_runtime.py` |
| `platforms/common/` | 四平台共享的运行时/状态/工具基建 | `_server_runtime.py`（host/port/token/`/health`）、`_device_state.py`（租约）、`_aliases.py`、`_upload_common.py`、`_manifest.py`（读 `platform.toml`）、`capabilities/`（能力框架） |
| `platforms/common/capabilities/` | **能力模块框架**（core / agent_browser / human_browser / human_dom / vision） | `_base.py` 定义注册与启用优先级；`setup()` 先激活模块再注册 `list_capabilities()` |
| `platforms/<name>/scripts/` | 设备端安装/启动/排错脚本 | `setup-*.{ps1,sh}`、`_launch-*`、`diagnose.ps1`（仅 Windows） |
| `platforms/<name>/skills/using-*/SKILL.md` | **给调用方 agent 用的**平台操作规范 | 这些是产品资产，不是 DSH 会话技能；措辞/坐标/失败表都在这里 |
| `cli/src/fleet/` | `agent-fleet setup` 向导 | `wizard.py` 流程、`installers/`（按 manifest 装）、`frameworks/`（6 种 agent 配置输出）、`guidance/*.yaml`（权限引导剧本）、`verify.py`/`smoke.py` |
| `scripts/` | 仓库级生成器与门禁 | `gen_docs.py`（活的，`--check`/`--write`）、`gen-docs.py`（同名旧物，别动）、`gen-blueprint-{map,interface}.sh`、`check-blueprint-refs.sh`、`check-ps-syntax.sh`、`install-agent-side.py`（老的 agent 端安装路径） |
| `docs/internal/blueprint/` | 自动生成 + ADR 的全貌册 | **只读**；改动由生成器和人共同维护，CODEOWNERS 钉住 |
| `docs/internal/{design,plans,specs}/` | 内部设计留档 | append-only 历史，**不做同步维护**，与新代码不一致属正常 |
| `docs/superpowers/{specs,plans}/` | 近年用 superpowers 方法论产出的设计/计划 | 同上，历史留档 |

**四平台目录是 6 件套**：`platform.toml` + `README.md` + `server/` + `scripts/` + `skills/` + `examples/`，以 `platforms/windows/` 为基准参照。

---

## 4. 工具清单：真源顺序（重要）

写文档、改 README、算「工具数」时按这个顺序取事实，**永远不要手抄、不要凭印象**：

1. **运行时真源**：调用该设备的 `list_capabilities()` —— 返回每个能力模块的 `id / status(enabled|disabled|unavailable) / tools / skill / usage_hint`。这是唯一能反映「这台机器此刻真的注册了什么」的口径。
2. **静态真源**：`platforms/tests/_ast_tools.extract_mcp_tools(<server.py>)`，数 `@mcp.tool` 装饰的函数（不含运行时注入的能力工具）。
3. **生成物**：`docs/internal/blueprint/INTERFACE.md`（静态签名清单）、`MAP.md`（模块地图）。
4. **文档**：各平台 `README.md` / `docs/platforms/<name>.md` —— 数字最容易漂移，改前先对照 1/2。

**计数口径的三个坑**（会让人写出错误数字）：

- `list_capabilities` 由框架统一注册，**不在** server 的 `@mcp.tool` 里，但运行时一定多这 1 个。
- 可选能力工具（`browser_*` 27 个、`human_browser_open` 1 个、`vision_*` 3 个、`human_dom_*` 5 个）由能力框架**运行时注入**，静态清单里没有。`scripts/gen_docs.py:75-85` 的 `capability_tool_count()` 只写了 `agent_browser` / `human_browser` / `vision` 三个分支，**没有 `human_dom` 分支**（函数 docstring 自己写着 "unknown optionals contribute 0 (add a branch)"），所以对它无条件返回 0 —— 而 AST 本身数得到那 5 个（`_human_dom.py:160-205` 的 5 个 `async @mcp.tool`，`extract_mcp_tools` 能递归到）。→ 启用了 human_dom 的 win/mac，`gen_docs` 报的数会**少 5**。
- `human_dom` 是 **opt-in**：没有 `~/.fleet/human-dom-ready` 标记时 `status=unavailable`、运行时工具为 0；装了才 +5。所以「工具总数」说到底只有一个权威口径：**运行时 `list_capabilities()`**。

---

## 5. 三条关键数据流

### 5.1 一次工具调用

`client → POST http://<host>:8766/mcp（streamable-http）→（可选）Bearer gate → FastMCP 路由 → core 内联工具 or 能力模块工具 → 平台原生驱动（pywinauto/UIA · AppleScript · adb · WDA）→ 结构化返回`

- **只有 win/mac 走 `platforms/common/_server_runtime.py`**：`--host`（默认 `0.0.0.0`，可退 `127.0.0.1` 免防火墙）、`--port`、`--token`、`--dom-bridge-port`，环境变量 `FLEET_HOST` / `FLEET_PORT` / `FLEET_AUTH_TOKEN`，健康探针 `GET /health`（免鉴权）。
- **android / ios 是裸 `mcp.run(host="0.0.0.0", port=<字面量>)`**（`android_device_mcp.py:1555`、`ios_device_mcp.py:1132`）：没有 `/health`、没有 bearer、端口不能从命令行改（改端口要改 `__main__` + `platform.toml`）。给这两家加参数能力属于代码改动，别只改 toml。
- Bearer gate 是**纯 ASGI 中间件**（不用 `BaseHTTPMiddleware`，避免缓冲 body 破坏流式长任务），`hmac.compare_digest` 常量时间比较；token 为空即完全不鉴权。

### 5.2 agent 自带字节传设备（上传通道）

Android / iOS 各有一条 HTTP `POST /upload` + MCP 工具组合；主机侧暂存目录统一是 `~/.agent-fleet/uploads`，URL 下载硬上限 200MB，`validate_url` 拒 loopback/私网（SSRF），下载后还做 DNS-rebinding 对端复验。

- **Android**：`stage_upload`（分片 base64）→ `deliver_staged`（收尾，后台 job，带 pidfile 可回收孤儿）→ `adb push` → 可选 `pm install` / MediaStore 扫描确认相册可见。`POST /upload` 走**流式落盘**，绕开 25s adb 钳制。
- **iOS**：`target=photos` 走自家 WDA 扩展 `/wda/photos/import`（JSON+base64 → PHPhotoLibrary）；`target=app` 走 pymobiledevice3 **AFC / house_arrest** 推到 app 沙箱（要求 `UIFileSharingEnabled` 或 dev-signed）。**没有分片路径**，且 `POST /upload` 是整包读进内存（大文件有内存峰值）。
- 两者都靠 `get_upload_endpoint` 告诉 agent 往哪 POST。Android 的 `device_path` 必须在 `/sdcard/` 或 `/storage/emulated/0/` 下。

### 5.3 human_dom（零痕迹 DOM 定位）桥

`Chrome 扩展 content script（per-profile 副本，烤入 bridge_port + profile_id）⟷ ws://127.0.0.1:<mcp_port+13> ⟷ server ⟷ human_dom_locate/tap/fill/status/focused`

- 桥端口 = `mcp_port + 13`（可用 `--dom-bridge-port` 覆盖；实际算法：覆盖值 > 已持久化值（仍空闲则复用）> `mcp_port+13` 起找空闲），持久化到 `~/.fleet/dom-bridge-<mcp_port>.port`；桥只绑 `127.0.0.1`，在守护线程里单独跑 uvicorn。扩展副本在 `~/.fleet/human-dom-ext/<profile_id>/`（**目录不能移动**，扩展 ID 由路径决定）。
- **两个就绪维度别混**：`~/.fleet/human-dom-ready` 标记决定「本 host 要不要 human_dom」（没有它 → `status=unavailable`、**工具根本不存在**）；`installed` 是纯盘扫 `loaded.json`（跨 server 重启仍 true），`connected` 才是「连在本 server 的桥」。看到 `installed=true, connected=false` 不要重装，重开 `human_browser_open(profile=…)` 或导航到 http 页面即可。
- 扩展只读 DOM、不点不改；动作仍由 OS 级 `tap` / 剪贴板粘贴完成 ⇒ `navigator.webdriver` 仍为 false。
- 省略 `profile` 时解析到「当前活跃 operator profile」，不是硬默认 `default`（`CHANGELOG.md:12-16`）；真账号场景必须三处同串：`human_browser_open(profile=…)` / 装扩展的 PROFILE / `human_dom_*(profile=…)`。

---

## 6. 三条安装路径（别混）

| 场景 | 命令 | 产物 |
|---|---|---|
| 设备端（把一台机器变成设备桥） | `powershell -ExecutionPolicy Bypass -File platforms\windows\scripts\setup-windows.ps1`（或 `bash platforms/<p>/scripts/setup-<p>.sh`） | `platforms/<p>/server/.venv` + 自启服务 + 端口监听 |
| 一键向导（推荐新用户） | `uvx --from "git+https://github.com/metahub-tech/agent-fleet@v0.8.4-alpha#subdirectory=cli" agent-fleet setup` | 同上，外加权限引导 + 健康检查 + 6 框架配置片段 |
| Agent 端（把设备挂到 agent） | `python3 scripts/install-agent-side.py --platform mac-device --hostname <host>`（老路径）或手工写 `~/.claude.json` 的 `mcpServers` | `mcpServers[<role>-device] = {type:http, url:…/mcp}` + `skills/using-*` 软链 |

**反模式**（`docs/install-pattern.md:168-178`）：改 `~/.claude/settings.json` 期望 MCP 生效、把 skill 拷进 `~/.claude/skills`（要软链）、多平台共用端口、用 SSE 跑长任务（v0.6.0 起一律 streamable-http）。

**三条容易误解的事实**（`cli/` 实测）：

- **CLI 必须在仓库根目录内运行**：`cli/pyproject.toml` 只打包 `src/fleet`，`platforms/` 不进 wheel；`installers/__init__.py:22-35` 靠「`__file__` 上溯 4 层」或「cwd 向上找 `platforms/common/_manifest.py`」定位，找不到即 `ModuleNotFoundError`。这也是引导脚本先 clone 再 `cd` 的原因。
- **wizard 不写任何 agent 配置**：`frameworks/*.py` 只渲染字符串（`render_entry` / `render_full_snippet`），「把片段贴进 `~/.claude.json`」仍要人手做；真正会改文件的只有 `scripts/install-agent-side.py`（备份 + merge + skill 软链，且**不含 `ios-device`**）。
- **`--dry-run` 不是全静默**：它只跳过 setup 脚本执行 / verify / guidance / smoke，`collect_options()` 仍会交互提问（Android 会问「复用配置？」「ADB 模式」）。

---

## 7. 本地开发与验证（先看能跑什么）

**本机实测环境**（Windows 10/11，2026-11-20）：PowerShell **5.1**（无 `pwsh` 7）、**无 WSL / 无 Git Bash**、`python3` 3.12.10、`pytest` 9.1.0、`uv` 可用、`node` 22。

| 想验证 | 命令 | 在本机能跑吗 |
|---|---|---|
| 文档工具数/端口表漂移 | `python3 scripts/gen_docs.py --check` | ✅（**当前失败**，见 §9） |
| 端口表重生成 | `python3 scripts/gen_docs.py --write` | ✅ |
| CLI 单元测试 | `cd cli && PYTHONPATH=src python3 -m pytest`（PowerShell: `$env:PYTHONPATH="src"; python3 -m pytest`） | ⚠️ 需先装依赖（`uv sync` 或 `pip install -e ".[dev]"`）；裸跑会因缺 `questionary` / `mcp` 有 2 个 collection error，且必须在 `cli/` 下跑（无 `conftest.py`，`testpaths=["tests"]`） |
| 平台共享层测试 | `python3 -m pytest platforms/common/tests -q --basetemp=.tmp-pytest/ct` | ✅ 可跑但**预期约 10 个 Windows 环境性失败**（bash 硬编码、`read_text()` 无 encoding 撞 GBK、路径进 regex）；`--basetemp` 必带，否则 `tmp_path` 撞 `%TEMP%` 权限 |
| 跨平台静态契约 | `python3 -m pytest platforms/tests -q --basetemp=.tmp-pytest/pt` | ✅ 快（实测 28 passed）；改 `platform.toml` / 工具名后必跑 |
| 单平台 server 冒烟 | `platforms\windows\server\.venv\Scripts\python.exe -m pytest platforms/windows/server/tests -q` | ⚠️ 必须用该平台自己的 venv（server 会 import pyautogui/psutil 等）；iOS 只在 macOS 上跑 |
| 蓝图门禁 | `./scripts/gen-blueprint-map.sh --check`、`gen-blueprint-interface.sh --check`、`check-blueprint-refs.sh` | ❌ 需要 bash（本机无），靠 CI（ubuntu） |
| PS 语法门禁 | `./scripts/check-ps-syntax.sh`（需 pwsh 7+ 与 bash） | ❌ 本机无 pwsh 7；替代：用 PS 5.1 解析器近似检查 |
| shell 语法门禁 | `bash -n <file>` / `find … -exec bash -n {} \;` | ❌ 本机无 bash，靠 CI |

> 结论：**Windows 单机上只能跑「Python 侧」门禁**；bash / PowerShell-7 门禁必须在 CI 或 macOS/Linux 上跑。改脚本后请在 PR 里说明「本地无法验证，已交 CI」。

---

## 8. 文档生成与 CI 门禁

**自动生成（改代码后必须跑，否则 PR 红）**：

| 生成器 | 产物 | 门禁 |
|---|---|---|
| `scripts/gen-blueprint-map.sh` | `docs/internal/blueprint/MAP.md` | CI `blueprint-check`：`--check` |
| `scripts/gen-blueprint-interface.sh` | `docs/internal/blueprint/INTERFACE.md` | CI `blueprint-check`：`--check` |
| `scripts/check-blueprint-refs.sh` | 校验 `GLOSSARY.md` 等引用路径真实存在 | CI `blueprint-check` |
| `scripts/gen_docs.py` | `docs/architecture.md` 端口表（`<!-- gen:port-table -->` 区段） | **不在 CI 里**，只在 `ONBOARDING.md` 要求人手跑 |

**CI 四个 job**（`.github/workflows/ci.yml`）：

| job | 干什么 | 是否分支保护 required |
|---|---|---|
| `shell-syntax` | 对 `platforms/ scripts/ install.sh` 下所有 `.sh` 跑 `bash -n` | ✅ required |
| `powershell-syntax` | ubuntu 装 pwsh 7 后跑 `./scripts/check-ps-syntax.sh` | ✅ required |
| `blueprint-check` | 三个蓝图脚本的 `--check` / 校验 | ✅ required |
| `python-tests` | `cd cli && pytest -x` | ❌ 非 required（`continue-on-error`） |

> **CI 绿 ≠ 全绿**：`python-tests` 永远不算失败；`gen_docs.py --check` 根本不在 CI 里；`scripts/tests/` 也不在 `python-tests` 的执行范围（它只 `cd cli`）。所以「PR 全绿」只保证 shell / pwsh 语法与蓝图三步。

**另有人类门禁**：main 分支保护要求 ≥1 真人审批 + `CODEOWNERS`（`@qin-jiangli` 钉住 install 脚本、四个 server 主入口、`platform.toml`、`.github/`、`LICENSE`/`SECURITY.md`/`CODE_OF_CONDUCT.md`、`docs/internal/blueprint/`、蓝图脚本）；**每个 commit 必须 `Signed-off-by:`（DCO）**。

---

## 9. 漂移登记（文档说的 ≠ 代码实际）

> 这是初始化时**实测**出来的不一致，不是猜的。修一个划掉一个；修完把「核对记录」的 commit 更新。

| # | 位置 | 它现在说 | 实际（证据） | 影响 |
|---|---|---|---|---|
| 1 | `README.md:45-46` | win **74** tools / mac **73** tools | AST 口径（core + `list_capabilities` + 静态可选能力）为 **75 / 74**；若再算上 `gen_docs` 漏掉的 human_dom 5 个，满配约 **80 / 79** | `python3 scripts/gen_docs.py --check` 在 main 上就 **exit 1**；新人抄数字必错 |
| 2 | `platforms/windows/README.md:60`、`platforms/macos/README.md:66`、`docs/platforms/{windows,macos}.md` 附录 A | core **42 / 41** 个工具 | AST core 为 **43 / 42**；差的都是 `hover_preview`（`win_device_mcp.py:552`、`mac_device_mcp.py:281`） | 这个工具 2026-07 起就存在，**从未进入任何工具表** |
| 3 | `docs/internal/blueprint/INTERFACE.md`（win/mac 节） | 无 `hover_preview` | 与生成器逻辑等价复现的结果：win 少 1、mac 少 1 → `gen-blueprint-interface.sh --check` 会 diff 并 `exit 1`，即 CI `blueprint-check` 第二步**应当红**（本机无 bash，未真跑，`set -e` 会连带第 3 步跑不到） | required check 事实性失效；接手先修这一处 |
| 4 | `scripts/gen_docs.py:75-85` | 工具数覆盖所有启用能力 | `capability_tool_count()` **没有 `human_dom` 分支**（docstring 自认 "unknown optionals contribute 0"），而 AST 能数到那 5 个（`_human_dom.py:160-205` 的 5 个 `async @mcp.tool`） | 属于**代码缺陷**，按流程先开 Issue，别夹带进文档 PR |
| 5 | `ONBOARDING.md:55` | win 71 / mac 70 / **android 26 / ios 27** | android/ios 的 AST 是 **31 / 30**（根 README 也写 31/30）→ 这两条是**硬错**；win/mac 则等于平台 README 的旧值 | 全仓最不可信的数字来源，却自称事实源（同页 `:44` 还要求「不要照抄旧文档」） |
| 6 | `docs/internal/blueprint/SNAPSHOT.md:5,7` | 2026-05-26 修订，`base_commit 448e957` | HEAD `aa6628b`（2026-08-01）：落后 **35 commit / 142 个文件**；该文件自己定「偏差 >7 天即过期」 | 装载顺序要求先读它 → 读到的是三个月前的快照 |
| 7 | `docs/architecture.md:164-177` | Auth「规划中，当前未实现」 | `platforms/common/_server_runtime.py:12-24` 已实现 `--token` Bearer 网关（纯 ASGI，`/health` 豁免） | 安全模型描述偏旧；默认不开 token 是事实，但「没这个能力」不成立 |
| 8 | `docs/install-pattern.md:42,106-124` | `*_gui_mcp.py`、server 名 `android`/`iphone`、"iOS v0.7 计划 TBD" | 实际是 `*_device_mcp.py`、`android-device`/`ios-device`、iOS 已发布（0.8.0 起） | 新人按目录契约找文件会找不到 |
| 9 | `docs/roadmap.md:5,26-27` | *Last updated: 2026-05-21*；表内只到 0.8.2 | 最新 tag `v0.8.13-alpha`；0.8.3–0.8.13 只在 CHANGELOG/tag 里 | 版本历史两个事实源，且 roadmap 更旧 |
| 10 | `README.md:4`、`install.sh:27`、`install.ps1:19`、`cli/pyproject.toml:7` | 版本 `v0.8.4-alpha` / `0.8.4a1` | 最新 tag `v0.8.13-alpha`（2026-07-07）；main 又比 tag 多 9 个 commit（2026-08-01，未发版） | 一键安装装到的是两个月前的版本；要装新的需显式 `AGENT_FLEET_VERSION=v0.8.13-alpha` |
| 11 | `docs/internal/README.md:11-15` | 内部文档索引只列 `design/ plans/ specs/` | 漏了 `blueprint/`（全貌册），也没有任何文档承认 `docs/superpowers/`（2026-07 起的 11 份 spec/plan）存在 | 找「为什么这么设计」的人会漏掉两代资产 |
| 12 | `CONTRIBUTING.md:113-127` | 每个 commit 必须 `Signed-off-by:`（DCO 硬要求） | 最近 40 个 commit 只有 **19** 个带 Signed-off-by | 契约与实践 47.5%；agent 不该学历史，要自己 `-s` |
| 13 | 本机环境（非仓库问题） | — | PowerShell 仅 5.1（无 `pwsh` 7）、无 WSL/Git Bash、`cli/` 依赖未装 → 三类脚本门禁本地跑不了，`cli` pytest 有 2 个 collection error | 改脚本的人容易误以为「本地过了」 |

**处置原则**：文档类（1、2、5、6、7、8、9、10、11）→ `docs/` 分支 + docs PR 模板，一处一 PR；代码类（3 的生成器产出重新生成、4 的分支缺失）→ 先开 Issue 或按 code PR 走，**不要夹带进文档 PR**（`ONBOARDING.md:93-97`）；12 是纪律问题，新提交自己 `git commit -s`；13 只需知道，不用改仓库。

---

## 10. 常见任务配方

| 我要做的事 | 步骤（含门禁） |
|---|---|
| 给某平台加一个工具 | 改 `platforms/<p>/server/*_mcp.py` → 在平台 `README.md` 工具表登记 → 若属 Universal Tool Set，名字必须跨平台一致（`docs/architecture.md:72-115`）→ 跑 `gen-blueprint-interface.sh`、`gen_docs.py --check` → `CHANGELOG [Unreleased]` |
| 改可选能力（browser/vision/human_dom） | 改 `platforms/common/capabilities/<cap>/` → 检查 `availability()` 与 `register()` 返回值（工具名列表用于 `list_capabilities` 分桶）→ 同步 win/mac 两个 `platform.toml` 的 `[capabilities].enabled` → 跑共享层 pytest |
| 加一个新平台 | 按 `docs/install-pattern.md:128-152` 八步：建 6 件套 → port server/setup/skill/examples → 写 `docs/platforms/<name>.md` → 更新 `README.md` 状态表/`roadmap.md` → `PLATFORMS` dict（`scripts/install-agent-side.py`）→ 端口取预留表 |
| 改安装脚本（.ps1/.sh） | **纯 ASCII/英文**（PS 5.1 在非 UTF-8 locale 会乱码解析失败）→ `$ErrorActionPreference="Stop"` → 幂等 → 跑 `check-ps-syntax.sh` / `bash -n`（本地跑不了就交 CI）→ `CHANGELOG` |
| 改用户可见文档 | 分支 `docs/…`、commit `docs:` → 同步 `docs/platforms/<p>.md` + `platforms/<p>/README.md` → `CHANGELOG [Unreleased]` → 9 语 README 同步（至少 `zh-CN`）→ 套 `PULL_REQUEST_TEMPLATE/docs.md` + `needs-review` |
| 改 CLI 向导 | `cli/src/fleet/` → 同步 `cli/tests/` → `uv sync` 后 `PYTHONPATH=src pytest` → 影响安装行为时更新 `docs/install-pattern.md` |
| 查「这台设备现在能干什么」 | 调该设备 `list_capabilities()`（别读文档）；接线方式见 §6 |
| 排查设备连不上 | `/mcp` 状态 → `http://` 非 `https://` → `tailscale status`/`ping` → `curl -sI http://host:8766/mcp` → 设备端 `Get-NetTCPConnection -LocalPort 8766`（`docs/agent-host-setup.md:149-197`） |

---

## 11. 继续阅读

| 需要 | 读 |
|---|---|
| 常驻工作纪律（每次会话都会加载） | [`AGENTS.md`](../AGENTS.md) |
| 工程基线、编码约定、DCO、版本语义 | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| 心智模型：两个角色 / 两条安装路径 / 目录契约 | [`docs/install-pattern.md`](install-pattern.md) |
| 三段式架构 + Universal Tool Set 设计契约 | [`docs/architecture.md`](architecture.md) |
| agent 端配置与排错 | [`docs/agent-host-setup.md`](agent-host-setup.md) |
| 平台 setup 细节 | [`docs/platforms/<name>.md`](platforms/) |
| 文档团队（只写文档的角色） | [`ONBOARDING.md`](../ONBOARDING.md) |
| 全貌快照 / 模块地图 / 工具签名 / ADR | [`docs/internal/blueprint/`](internal/blueprint/) |
| 术语 | [`GLOSSARY.md`](internal/blueprint/GLOSSARY.md) |

---

## 核对记录

| 日期 | commit | 核对方式 |
|---|---|---|
| 2026-11-20 | `aa6628b`（`docs/agent-init` 分支起点） | 人工通读 + `python3 scripts/gen_docs.py --check`（exit 1，见 §9 #1）+ `_ast_tools` 实测四平台工具数 + 本机工具链探测 |
