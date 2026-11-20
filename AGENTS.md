# AGENTS.md · agent-fleet 工作指令

> 这份文件是**每个 agent 会话开始时自动加载的常驻指令**（DSH 读取根目录 `AGENTS.md` / `CLAUDE.md`；项目根由 `.git` 标记，预算 64 KiB）。
> 它只放「做任何事都不能忘的东西」。细节看 [`docs/project-map.md`](docs/project-map.md)（操作层地图：拓扑 / 命令 / 门禁 / 漂移登记 / 任务配方）。
>
> 维护约定：**改坏了它比没有它更糟**。新增一行前先问「换个任务这句话还成立吗」；只写稳定的、可验证的事实，并给证据位置。

---

## 0. 三十秒上手

```powershell
# 1) 我现在在哪、仓库什么状态
git log -1 --format="%h %ad %s" --date=short   # main 最后一次提交 2026-08-01 aa6628b
git tag -l --sort=-v:refname | Select-Object -First 3   # 最新 tag v0.8.13-alpha

# 2) 改东西前先跑「现状体检」（结果见 §6，当前就是红的，不要以为是你的锅）
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
| `cli/src/fleet/` | `agent-fleet setup` 向导（installers / frameworks / guidance） | 代码；改完跑 `cli/tests` |
| `scripts/` | 生成器与门禁（`gen_docs.py` 是活的，`gen-docs.py` 是 shim） | 蓝图脚本被 CODEOWNERS 钉住 |
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

本机（Windows 10/11）实测：PowerShell **5.1**（无 `pwsh` 7）、**无 WSL / 无 Git Bash**、`python3` 3.12、`pytest` 9.1、`uv` 可用。

| 门禁 | 命令 | 本机 |
|---|---|---|
| 文档漂移（工具数 + 端口表） | `python3 scripts/gen_docs.py --check` | ✅ 能跑；**当前 exit 1**（见 §6） |
| 跨平台静态契约 | `python3 -m pytest platforms/tests -q --basetemp=<仓库外目录>` | ✅ 28 passed |
| 共享层单测 | `python3 -m pytest platforms/common/tests -q --basetemp=<仓库外目录>` | ⚠️ 约 10 个 Windows 环境性失败（bash 硬编码 / GBK 解码 / 路径进 regex），**不是回归** |
| CLI 单测 | `cd cli; $env:PYTHONPATH="src"; python3 -m pytest` | ⚠️ 先 `uv sync`（或 `pip install -e ".[dev]"`），否则缺 `questionary`/`mcp` 直接 collection error |
| 蓝图三步 | `gen-blueprint-{map,interface}.sh --check`、`check-blueprint-refs.sh` | ❌ 需要 bash → 靠 CI（ubuntu） |
| PS 语法 | `./scripts/check-ps-syntax.sh`（需 pwsh 7 + bash） | ❌ 本机无 pwsh 7 → 靠 CI |

`--basetemp` 必带：本机 `%TEMP%` 权限被拒会让 `tmp_path` 直接报错。**CI 绿 ≠ 全绿**：`python-tests` 是 `continue-on-error`，`gen_docs.py --check` 根本不在 CI 里，`platforms/**` 测试也没进 CI。

---

## 5. 常见任务的分流

| 我要做 | 先读 | 改完必跑 |
|---|---|---|
| 加/改某平台工具 | `docs/architecture.md` Universal Tool Set + 平台 `README.md` | `platforms/tests`、`gen-blueprint-interface.sh`、`gen_docs.py --check` |
| 改可选能力（browser/vision/human_dom） | `platforms/common/capabilities/_base.py` + 该能力目录 | `platforms/common/tests`、`gen-blueprint-*` |
| 改安装脚本 / CLI | `docs/install-pattern.md`、`cli/README.md` | `check-ps-syntax.sh`、`cd cli && pytest`、`CHANGELOG` |
| 改用户文档 | `ONBOARDING.md`、`docs.md` 模板 | `gen_docs.py --check`、9 语同步、`CHANGELOG` |
| 排查真机连不上 | `docs/agent-host-setup.md` §4 | — |
| 想知道「这台设备现在能干什么」 | 别读文档，调 `list_capabilities()` | — |

更细的步骤（含文件路径与坑）见 [`docs/project-map.md`](docs/project-map.md) §10。

---

## 6. 已知漂移（初始化时实测，别当成自己造成的）

完整 13 条见 [`docs/project-map.md`](docs/project-map.md) §9。最要紧的四条：

1. **`python3 scripts/gen_docs.py --check` 在 main 上就是红的**：README 写 win 74 / mac 73，AST 口径是 75 / 74（`--write` 只修端口表，**修不了 README 数字**）。
2. **`hover_preview` 从未进入任何工具表**：代码有（`win_device_mcp.py:552`、`mac_device_mcp.py:281`），`README*`、平台 `README`、`docs/platforms/*.md`、`INTERFACE.md` 都没有 → `gen-blueprint-interface.sh --check` 应当红（CI `blueprint-check` 第二步）。
3. **`gen_docs.py:75-85` 的 `capability_tool_count()` 没有 `human_dom` 分支**，恒算 0（AST 本身能数到那 5 个）→ 真机满配比脚本数多 5。这属**代码缺陷**，先开 Issue。
4. **`ONBOARDING.md:55` 的四个数字全错**，其中 android 26 / ios 27 是硬错（实际 31 / 30）；`SNAPSHOT.md` 的 `base_commit` 落后 35 个 commit（超自定 7 天红线 14 倍）。

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
10. **别信版本号**：README / 引导脚本 / `cli/pyproject.toml` 都停在 `v0.8.4-alpha` / `0.8.4a1`，实际最新 tag 是 `v0.8.13-alpha`，main 又领先 9 个 commit（未发版）。

---

## 8. 项目级技能与自检

本仓库自带一个 DSH 技能：

- `.dsh/skills/project-init/SKILL.md` —— **项目装载/刷新**：按「文件 → 生成物 → 运行时」的顺序重建认知，跑一遍体检命令，并输出「现状 + 漂移 + 建议」报告。新会话不确定从哪下手时先加载它。

技能根路径（DSH）：项目级 `<repo>/.dsh/skills`（本次用）与 `<repo>/.agents/skills`，用户级 `~/.dsh/skills`。技能只认一层：`<root>/<name>/SKILL.md` 或 `<root>/<name>.md`。

---

## 9. 我这个会话里的现实约束

- 挂载的 live 设备：`win-device` → `test-win11:8766`，`win-device-qjl` → `win-personal-qjl:8766`（都是本项目产物，跑着操作员的真账号任务）。
- 真机操作优先 `element-first`（`tap_element` / `find_elements` / `human_dom_locate`），坐标点击只作兜底；不可逆动作前用 `hover_preview` 验证落点。
- 本机没有 bash / pwsh 7，**任何脚本类门禁都不能在本机下结论**；需要时明说「已交 CI 验证」。

---

_本文件是手写稳定层。事实变更（版本、门禁、目录契约）时请同步更新，并保持与 `docs/project-map.md` 一致；两者冲突时以 `docs/project-map.md` 的核对记录为准。_
