# AGENTS.md · agent-fleet 工作指令

> 这份文件是**每个 agent 会话开始时自动加载的常驻指令**（DSH 读取根目录 `AGENTS.md` / `CLAUDE.md`；项目根由 `.git` 标记，预算 64 KiB）。
> 它只放「做任何事都不能忘的东西」。细节看 [`docs/project-map.md`](docs/project-map.md)（操作层地图：拓扑 / 命令 / 门禁 / 漂移登记 / 任务配方）。
>
> 维护约定：**改坏了它比没有它更糟**。新增一行前先问「换个任务这句话还成立吗」；只写稳定的、可验证的事实，并给证据位置。

---

## 0. 三十秒上手

```powershell
# 1) 我现在在哪、仓库什么状态
git log -1 --format="%h %ad %s" --date=short   # main 最后一次提交 2026-11-23 e0815b9
git tag -l --sort=-v:refname | Select-Object -First 3   # 最新 tag v0.8.14-alpha

# 2) 改东西前先跑「现状体检」（2026-11-21 对齐后已转绿；再变红说明文档又落后于代码）
python3 scripts/gen_docs.py --check

# 3) 只改文档？只改平台代码？先看 §3 的分流表，别在同一 PR 里混。
```

**事实真源顺序**（永远按这个顺序取真相，越靠前越权威）：

1. **代码**：`platforms/*/server/*_mcp.py` + `platforms/common/**`
2. **运行时**：让接了设备的 agent 调 `list_capabilities()`（唯一能反映「这台机器现在真的有什么」的口径）
3. **自动生成物**：`docs/internal/blueprint/INTERFACE.md`（工具签名）、`MAP.md`（模块地图）
4. 平台 `README.md` / `docs/platforms/<name>.md`（手工，最容易漂移）
5. `ONBOARDING.md`、`docs/roadmap.md`、`docs/internal/{design,plans,specs}/`、`docs/superpowers/**`（**叙事与历史，不当作现状**）

---

## 1. 这是什么项目

agent-fleet 让 LLM agent **通过 MCP 操作真实的 Windows / macOS / Android / iOS 设备**：四个平台各有一个 FastMCP 设备桥（streamable-http），agent 用统一工具集（`take_screenshot` / `tap` / `launch_app` / …）跨设备操作，换设备只是换一个 URL。产品定位在「agent 驱动的跨平台测试与验证」与「agent 在物理世界的手和眼」之间。

- 当前是 **alpha**（`CHANGELOG [Unreleased]` 已走到 v0.8.13 之后），接口未冻结，允许破坏性变更。
- **改动这个仓库，等于改「我自己和队友 agent 的手」**：本会话挂载的 `win-device`（`http://test-win11:8766/mcp`）与 `win-device-qjl`（`http://win-personal-qjl:8766/mcp`）就是本项目的产物。改 server 行为前先想到「真机上有操作员在跑」。
- 近期工作主线：`human_dom` / `human_browser` / `vision` 的**精度与零自动化痕迹**（配合外部 AgentHub #100 的真账号发文 E2E）。

---

## 2. 仓库地图（一行一项，详解见 project-map §3）

| 路径 | 是什么 | 能改吗 |
|---|---|---|
| `platforms/<p>/server/*_mcp.py` | 平台 MCP server 主入口，**core 工具内联在这里** | 代码改动，需 CODEOWNERS 真人审 |
| `platforms/common/` | 共享运行时 / 租约 / 别名 / 上传 / 能力框架 | 同上（win/mac/android/ios 全受影响） |
| `platforms/common/capabilities/` | core / agent_browser / human_browser / human_dom / vision | 同上；改完要同步 `platform.toml` 与 `list_capabilities` 分桶 |
| `platforms/<p>/scripts/` | 设备端安装 / 启动 / 排错脚本 | 安装脚本（高敏感） |
| `platforms/<p>/skills/using-*/SKILL.md` | **给调用方 agent 用的**平台操作规范（产品资产） | 文档可改，但属产品契约 |
| `cli/src/fleet/` | `agent-fleet setup` 向导（installers / frameworks / guidance；收尾写 skills 交接物，**不枚举客户端**） | 代码；改完跑 `cli/tests` |
| `scripts/` | 生成器与门禁（`gen_docs.py` 是活的，`gen-docs.py` 是 shim） | 蓝图脚本被 CODEOWNERS 钉住 |
| `scripts/install_skills.py` | 把 `using-*` skill 装进 agent 自己的技能目录（跨平台、幂等、**不写任何 config**） | 代码；改动跑 `scripts/tests` |
| `docs/install-for-agents.md` | **面向 agent 的安装 playbook**：装 MCP → 装 skill → human_dom provisioning → 只把 4 件人类步骤交还 | 文档，随安装链路更新 |
| `docs/internal/blueprint/` | `MAP.md`/`INTERFACE.md`（**自动生成，必须随代码再生**）+ ADR + GLOSSARY + SNAPSHOT | **不是只读留档**，是 CI 门禁对象 |
| `docs/internal/{design,plans,specs}/`、`docs/superpowers/` | 历史设计/计划留档（两代，各自冻结） | 只读，不追现状 |
| `docs/project-map.md` | 操作层地图（本文件的展开） | 手写，随事实更新 |

---

## 3. 硬约束（违反会被 CI / reviewer 打回）

| # | 约束 | 依据 |
|---|---|---|
| 1 | **一个 commit 一件事**，`type(scope): 描述`；纯文档用 `docs:` 前缀 | `CONTRIBUTING.md:42-46` |
| 2 | **每个 commit 必须 `git commit -s`**（DCO `Signed-off-by:`）；AI 大量参与再加 `Co-Authored-By:` | `CONTRIBUTING.md:113-143`（实测历史只有 19/40 合规——别学历史） |
| 3 | **PR 分流**：文档 PR 用 `.github/PULL_REQUEST_TEMPLATE/docs.md`（`?template=docs.md`），代码 PR 用默认模板；两者自查项不同，**别套错** | 见 `docs/project-map.md` §8 |
| 4 | **三件套同步**：改平台工具/步骤 → 平台 `README.md` + `docs/platforms/<p>.md` + `CHANGELOG.md [Unreleased]` | `CONTRIBUTING.md:34-40` |
| 5 | **工具数/工具名只能取事实源**，禁止手抄旧文档（`list_capabilities` 或 `extract_mcp_tools`） | `ONBOARDING.md:42-55` |
| 6 | **改 `platforms/` 或 `cli/` 代码 → 同一 PR 内重跑** `gen-blueprint-map.sh` 与 `gen-blueprint-interface.sh`，否则 `blueprint-check`（required）红 | `.github/workflows/ci.yml:50-63` |
| 7 | **`.ps1` / `.sh` 里绝不写中文**（Win PowerShell 5.1 按系统代码页解析无 BOM 脚本，会乱码 + 解析失败）；`$ErrorActionPreference="Stop"`；脚本幂等 | `CONTRIBUTING.md:56-62` |
| 8 | **文档中文为主**，路径/命令/变量名/API 名/日志原文保留英文 | `CONTRIBUTING.md:64-67` |
| 9 | **9 语 README 同步**：`README.md`(en) 是源，改结构/内容须同 PR 同步 `zh-CN`，其余语言在 PR 里显式列出待同步 | `ONBOARDING.md:76` |
| 10 | **别动需要真人审的路径**：`server/*_mcp.py`、`platforms/*/scripts/`、`platform.toml`、`install.sh/.ps1`、`.github/`、`LICENSE`/`SECURITY.md`/`CODE_OF_CONDUCT.md`、`docs/internal/blueprint/`（CODEOWNERS `@qin-jiangli`）。文档与代码不符 → **开 Issue**，不在文档 PR 里顺手改代码 | `.github/CODEOWNERS`、`ONBOARDING.md:93-97` |
| 11 | **不改冻结历史**：老 ADR 永不修改（新决策开 `DECISIONS/000N-<slug>.md` 并 `Supersedes #N`）；`docs/internal/{design,plans,specs}`、`docs/superpowers/**` 只读 | `docs/internal/blueprint/README.md:13` |
| 12 | **SNAPSHOT 是周更资产**：引用它前先比对 `base_commit`，不符以代码为准并上报漂移 | `SNAPSHOT.md:75` |

---

## 4. 验证：先看清「我这台机器能跑什么」

本机（Windows 10/11）实测：PowerShell **5.1**（无 `pwsh` 7）、**Git Bash 可用**（`E:\Program Files\Git\bin\bash.exe`；`C:\Windows\System32\bash.exe` 是 WSL 桩，别用）、`python3` 3.12、`pytest` 9.1、`uv` 可用。

| 门禁 | 命令 | 本机 |
|---|---|---|
| 文档漂移（工具数 + 端口表） | `python3 scripts/gen_docs.py --check` | ✅ **当前 exit 0**（2026-11-21 对齐后） |
| 跨平台静态契约 | `python3 -m pytest platforms/tests -q --basetemp=<仓库外目录>` | ✅ 28 passed |
| 共享层单测 | `python3 -m pytest platforms/common/tests -q --basetemp=<仓库外目录>` | ⚠️ 约 10 个 Windows 环境性失败（bash 硬编码 / GBK 解码 / 路径进 regex），**不是回归** |
| CLI 单测 | `cd cli; $env:PYTHONPATH="src"; python3 -m pytest` | ⚠️ 先 `uv sync`（或 `pip install -e ".[dev]"`），否则缺 `questionary`/`mcp` 直接 collection error |
| 蓝图三步 | `& 'E:\Program Files\Git\bin\bash.exe' -lc "cd /e/workspace/.../agent-fleet && PYTHONUTF8=1 ./scripts/gen-blueprint-map.sh --check"`（interface / refs 同理） | ✅ 需 **Git Bash + `PYTHONUTF8=1`**（脚本内嵌 Python 未指定 encoding） |
| PS 语法 | `./scripts/check-ps-syntax.sh`（需 pwsh 7） | ❌ 本机无 pwsh 7 → 用 PS 5.1 `Parser::ParseFile` 近似验证，正式门禁交 CI |

`--basetemp` 必带：本机 `%TEMP%` 权限被拒会让 `tmp_path` 直接报错。**CI 绿 ≠ 全绿**：`python-tests` 是 `continue-on-error`，`gen_docs.py --check` 根本不在 CI 里，`platforms/**` 测试也没进 CI。

---

## 5. 常见任务的分流

| 我要做 | 先读 | 改完必跑 |
|---|---|---|
| 加/改某平台工具 | `docs/architecture.md` Universal Tool Set + 平台 `README.md` | `platforms/tests`、`gen-blueprint-interface.sh`、`gen_docs.py --check` |
| 改可选能力（browser/vision/human_dom） | `platforms/common/capabilities/_base.py` + 该能力目录 | `platforms/common/tests`、`gen-blueprint-*` |
| 改安装脚本 / CLI | `docs/install-pattern.md`、`cli/README.md` | `check-ps-syntax.sh`、`cd cli && pytest`、`CHANGELOG` |
| 把项目装到一台机器 / 交给别的 agent 装 | `docs/install-for-agents.md` | `python3 scripts/install_skills.py --list`、`scripts/tests`、`CHANGELOG` |
| 让 human_browser 拿到 DOM 精度 | `platforms/common/skills/using-human-dom/SKILL.md`（两层启用模型） | 建 marker → 重启 → `human_browser_open(profile=专用)` → `human_dom_status` |
| 改用户文档 | `ONBOARDING.md`、`docs.md` 模板 | `gen_docs.py --check`、9 语同步、`CHANGELOG` |
| 验证租约隔离（多 agent） | `scripts/smoke_lease.py` 的 docstring | `python scripts/smoke_lease.py --url http://<host>:<port>/mcp`（只读，12 项） |
| 排查真机连不上 | `docs/agent-host-setup.md` §4 | — |
| 想知道「这台设备现在能干什么」 | 别读文档，调 `list_capabilities()` | — |

更细的步骤（含文件路径与坑）见 [`docs/project-map.md`](docs/project-map.md) §10。

---

## 6. 对齐状态（2026-11-21 修一轮，2026-11-23 发布 v0.8.14-alpha；明细见 project-map §9）

**已修复**（`gen_docs.py --check`、三个蓝图 `--check`、`platforms/tests` 均绿）：

1. 版本串：安装脚本/badge/`uvx` 命令从 `v0.8.4-alpha` → **`v0.8.13-alpha`**；`__version__` 与 5 个 `pyproject.toml` 从 `0.8.4a1` → **`0.8.13a1`**（含 `test_smoke` 断言）。
2. 工具数：README/平台 README/`docs/platforms/*` 附录/`ONBOARDING.md` 统一到**默认满配 75 / 74 / 31 / 30**；`human_dom` 明确为 opt-in（+5 → 80 / 79）。
3. `hover_preview` 进 `INTERFACE.md`（重生成）、两平台 README / setup guide、`docs/architecture.md`、`SNAPSHOT.md`。
4. `docs/architecture.md` 的 Auth 表述改为「已实现，默认关闭」（win/mac `--token`）。
5. `gen_docs.py` 增加 `OPT_IN_CAPABILITIES` 与 `human_dom` 计数分支：默认总数不含 opt-in，运行时以 `list_capabilities()` 为准。
6. `docs/roadmap.md` 补齐 0.8.3–0.8.13；`SNAPSHOT.md` 回填 `base_commit` / 日期。
7. `docs/install-pattern.md` 的旧命名（`*_gui_mcp.py`、`android`/`iphone`）与「iOS v0.7 计划 TBD」按现行目录契约重写，并补上 `platform.toml` 与 `platforms/common/` 说明。

**仍待处理**（不要顺手改，按 project-map §9.2 分流）：

1. `docs/internal/README.md` 索引缺 `blueprint/`，也没承认 `docs/superpowers/`。
2. `scripts/gen-blueprint-*.sh` 内嵌 Python 未显式 `encoding="utf-8"`，非 UTF-8 locale 需 `PYTHONUTF8=1`。
3. 历史 DCO 合规率仅 19/40（只影响新提交的自我要求）。
4. `platforms/android/skills/using-android/SKILL.md` 的 "30 tools" 是 core 口径（运行时 31，含 `list_capabilities`）。
5. README 状态表的 Version 列（`0.2.0` / `0.3.0` / `0.7.0-alpha` / `0.8.0-alpha`）是「各桥首次发布版本」，与当前统一版本串 `0.8.14a1` 不同口径——**要不要改成发布线，需负责人拍板**。

---

## 7. 最容易踩的坑

1. **用 AST 数工具总数必错**：`extract_mcp_tools` 只扫 server 文件，漏掉 `agent_browser`（运行时生成 27+4）、`vision`（3）、`human_dom`（5，注册在 `_human_dom.py` 的 `register()` 内）。要准数只有 `list_capabilities()`。
2. **`[capabilities].enabled` 写了不一定生效**：优先级 `.fleet/config.toml` > `platform.toml` > `["core"]`；registry 里没 `add()` 的模块写也白写（android/ios 只 add 了 core）；**改完必须重启 server**（导入期静态注册）。
3. **`human_dom` 是 opt-in**：没有 `~/.fleet/human-dom-ready` → `unavailable`、工具根本不存在；`installed=true / connected=false` 不是「没装」，别重装。
4. **四个 server 启动方式不一样**：只有 win/mac 走 `_server_runtime`（有 `--host/--port/--token` 与 `/health`），android/ios 是裸 `mcp.run(host=..., port=<字面量>)`。
5. **运行时状态三个家，放错不报错只静默失效**：租约与 session default 在**内存**（重启即丢）；设备别名在 `~/.agent-fleet/`；human_dom / 浏览器 profile 在 `~/.fleet/`；上传暂存在 `~/.agent-fleet/uploads`。
6. **`agent_browser` 与 `human_browser` 共享 profile 租约**：同 profile 字符串 = 同一 Chrome user-data-dir = 同一份登录；跨引擎互斥会**真的拒绝**。真账号 operator 全程只用 `human_browser`(+`human_dom`)，且三处 profile 必须同串。
7. **CLI 必须在仓库根内运行**（`platforms/` 不进 wheel），且 wizard **不写任何 agent 配置**（frameworks 只渲染片段）；真正改文件的是 `scripts/install-agent-side.py`（且不含 `ios-device`）。
8. **不要用 `--write` 之外的想像修 README 数字**：`gen_docs.py --write` 只重写 `docs/architecture.md` 的端口表区段；README 里的数字要人改，改完再 `--check`。
9. **`docs/internal/` 不是整体只读**：`design/plans/specs` 冻结，但 `blueprint/{MAP,INTERFACE}.md` 必须随代码再生。
10. **设备租约是强制的（绑定 MCP session）**：`acquire` 后只有**该 session** 能调用设备工具；其它 session 拿到 `{ok:false, reason:"device_leased", current_holder, auto_release_in_seconds}`。任何设备调用（含 browser / vision / human_dom）自动续租，**10 分钟无设备调用**才释放；断线重连后用同一个 `holder_name` 再 `acquire` 重绑。无主时谁都能用（不会自动加锁）。
11. **MCP session 只活在服务进程内存里**：进程一换，所有客户端 404（`Invalid or expired session ID`），与 `acquire`/租约无关。设备端稳定性三件套：任务计划 `ExecutionTimeLimit=PT0S`、重复触发器只做 6 小时兜底、launcher 单实例互斥（`Local\agent-fleet-win-device-launcher`）。排查用 `~/.agent-fleet/session-audit.log`（`created/reused/expired_or_unknown/bad_request`）。
12. **版本号有历史坑**：v0.8.5–v0.8.13 这 9 个 tag 当时都没 bump `__version__`，所以那 9 个 release 装上后 `agent-fleet --version` 都自称 `0.8.4a1`（tag 不可改写，已在 `docs/roadmap.md` 注明）。main 已统一到 `0.8.14a1`（v0.8.14-alpha 起每次 tag 同步 bump）——**每次发 tag 必须同时 bump 6 处（`cli/src/fleet/__init__.py`、`cli/pyproject.toml`、4 个 server `pyproject.toml`）+ `cli/tests/test_smoke.py` 的断言**。

---

## 8. 项目级技能与自检

本仓库自带一个 DSH 技能：

- `.dsh/skills/project-init/SKILL.md` —— **项目装载/刷新**：按「文件 → 生成物 → 运行时」的顺序重建认知，跑一遍体检命令，并输出「现状 + 漂移 + 建议」报告。新会话不确定从哪下手时先加载它。

技能根路径（DSH）：项目级 `<repo>/.dsh/skills`（本次用）与 `<repo>/.agents/skills`，用户级 `~/.dsh/skills`。技能只认一层：`<root>/<name>/SKILL.md` 或 `<root>/<name>.md`。

---

## 9. 我这个会话里的现实约束

- 挂载的 live 设备：`win-device` → `test-win11:8766`，`win-device-qjl` → `win-personal-qjl:8766`（都是本项目产物，跑着操作员的真账号任务）。
- 真机操作优先 `element-first`（`tap_element` / `find_elements` / `human_dom_locate`），坐标点击只作兜底；不可逆动作前用 `hover_preview` 验证落点。
- 本机有 Git Bash（`E:\Program Files\Git\bin\bash.exe`，可跑蓝图三件套与 `bash -n`）但没有 `pwsh` 7：PS 语法门禁只能用 PS 5.1 解析器近似验证，正式门禁交 CI。

---

_本文件是手写稳定层。事实变更（版本、门禁、目录契约）时请同步更新，并保持与 `docs/project-map.md` 一致；两者冲突时以 `docs/project-map.md` 的核对记录为准。_

## 10. 🔴 chat 与 task 的分工（硬约束）➔ 手册：`.agents/skills/starflow-comm-sop/SKILL.md`

> **一句话**：**`task` 管「事」，`chat` 管「人」。两者不得混用。**
> 本节由 `devops/scripts/onboard-agent.sh` 自动注入，**不要手改**（改源文件后重新注入）。

### 10.1 分工表

| 维度 | **`task`（事）** | **`chat`（人）** |
|---|---|---|
| 对象 | 工单 = 可验收的工作单元 | Agent / 人 = 沟通对象 |
| 存储 | **工单 timeline**（只存） | **thread**（会话） |
| 是否唤醒 | **不唤醒**（`@` 除外） | **会投递**给对方 |
| 有无"回包" | 无。只有**状态流转**（submit） | 有。回原 thread |
| 谁该看 | 主动 `starflow task timeline --task <id>` | 被动收 |

### 10.2 五条铁律

1. **工单不是聊天群**：`chat send --to topic:task:*` 或 `--topic topic:task:*` 都会被**拒绝**。
   留言用 `starflow task comment --task <id>`；要提醒某人来看用 `--at <who>`（只发"去读"通知，不含正文）。
2. **认领前不要提交**：`submit` 要求 `claimed_by = 你`。先 `starflow task claim --task <id>`。
   报错 `409 not_claimed` 就是这个原因。
3. **只在 chat 说过 = 没说过**：需求、决策、验收结论必须 `flow submit` 或 `task comment` 落到工单。
4. **与工单相关的求证必须回流**：`chat send --to <人> --relate-task <id> "..."`，
   否则结论只在会话里，处理那张单的会话看不到。
5. **阻塞必须显式登记**：`starflow team block --task <id> --reason "..." --kind human_decision`
   —— 会自动写库 + 推人类飞书。**只在聊天里说"我在等"不算**（历史事故：这样卡了 22.5 小时）。

### 10.3 常用命令速查

```bash
# 事（工单）
starflow flow pull                        # 按订阅批量认领
starflow task claim    --task <id>        # 直接认领（校验 owner_role）
starflow task comment  --task <id> [--at <who>] "内容"
starflow task timeline --task <id> [--limit 20]
starflow task progress --task <id> [--eta 120m] [--beat]
starflow flow submit   --task <id> --action pass|reject|observe --note "..."

# 人（沟通）
starflow chat send --to agent:<x> [--relate-task <id>] "内容"
starflow chat inbox --peek | --pop
starflow chat send --to agent:<x> --channel primary "..."   # 显式投前台（原 connect 已取消）
starflow chat exit

# 阻塞
starflow team block   --task <id> --reason "..." --kind human_decision|peer_dependency|external
starflow team unblock --task <id>
starflow team status

# 自检
starflow brief show
```

### 10.4 三个真实踩坑（前车之鉴）

| 坑 | 后果 | 正确做法 |
|---|---|---|
| `chat send --to topic:task:X` | 被守卫拒绝（工单不是投递通道） | `task comment --task X` |
| 没 `claim` 就 `submit` | `409 not_claimed`，工单卡住 | 先 `task claim` |
| 阻塞只在聊天里说 | 卡 22.5 小时无人知 | `team block` 写库 + 飞书 |

### 10.5 长任务

预计超过 30 分钟的任务（构建/CI/部署），**开工时声明一次**：
```bash
starflow task progress --task <id> --eta 120m --note "全量构建，预计 2 小时"
```
系统会把该会话的判活阈值延长到 ETA；不声明则连续 30 分钟无输出会被判死。
任务进行中可 `--beat` 刷新进度。
## 11. 🔴 通道唯一性（硬约束）

> **一句话**：**Agent 之间的通信只能走 StarFlow。** 任何绕过 StarFlow 的"消息获取"都视为越权。

### 11.1 允许的通道（仅此两类）

1. **StarFlow 推送**：`chat.message` 事件注入到你的端点；
2. **StarFlow 读取 API**：`GET /api/v1/chat/topics/<id>/messages`（需要成员资格）。
   注意：**你只能读到"投递给你的"消息**（以及你自己发的、系统告警）；
   别人会话里没投递给你的消息，看不到 —— 这是有意为之，不是缺陷。

### 11.2 禁止的通道（一律视为越权）

| 禁止行为 | 为什么 |
|---|---|
| `tmux capture-pane` 读别人的窗格 | 同机同用户就能读屏，但那是 **OS 旁路**，不经任何授权 |
| 读对端工作区文件、日志、数据库 | 同上，绕过成员校验与审计 |
| 直接写库改消息/投递状态 | 绕过状态机与投递语义 |
| 用其它 IM/邮件等外部通道代替 chat | 会话不可审计、不可归档 |

**唯一例外**：人类显式授权（例如运维排障时明确要求你去看某台机器的屏幕）。

### 11.3 为什么必须这样

- 消息**只属于一个地址**：降级/旁路会让"我发的消息他到底收没收到"变成不可判定；
- 会话**要可归档、可审计**：旁路读到的内容不在会话里，归档后就丢了；
- 排障**要能追**：通道外的信息无法在 `wf_chat_delivery` / `wf_chat_read_cursor` 留痕。

### 11.4 收到消息后的动作

见 `.agents/skills/starflow-comm-sop/SKILL.md` §0.0：用**同一个 topic** 回复，
不要自己加 `--channel`（服务端按"从哪来回哪去"寻址）。

