---
name: project-init
description: 装载或刷新 agent-fleet 仓库认知：按「文件 → 生成物 → 运行时」重建项目地图、跑一遍体检命令、输出「现状 + 漂移 + 建议」报告。用于新会话接手、版本切换/长时间停滞后复核、或用户要求「先了解/初始化这个项目」时。
whenToUse: 用户说「了解这个项目 / 初始化 / 接手 / 现在什么状态 / 从哪里下手」；或你要做跨模块改动、此前没读过本仓库时。
---

# project-init · 项目装载与刷新

目标：**在动手之前，用可复现的步骤把「这个仓库现在是什么样」变成事实，而不是印象。**
本技能默认**只读**：只做勘察与报告，不改任何文件。发现漂移 → 报告，不顺手修（修不修、走哪条 PR，由人或下一次任务决定）。

---

## 0. 先确认前提

1. 工作目录是仓库根（含 `.git`）。DSH 会自动加载根目录 `AGENTS.md` —— 若它不在上下文里，先读它。
2. 判断这次要「全量装载」还是「主题化装载」：
   - 全量：用户刚接手 / 很久没碰 / 要做跨模块改动 → 走完 §1–§4。
   - 主题化：用户已点名范围（只改文档 / 只改某平台工具）→ 走 §1 的 1–3 步 + §3 中相关项即可。

---

## 1. 读的顺序（不要随机读文件）

按「结论 → 操作 → 结构 → 历史」四层，每层只读必要的：

| 层 | 读什么 | 目的 | 时间盒 |
|---|---|---|---|
| A 结论 | `AGENTS.md` | 硬约束、真源顺序、已知漂移 | 必读 |
| B 操作 | `docs/project-map.md` | 拓扑、命令、门禁、漂移登记、任务配方 | 必读 |
| C 结构 | `docs/internal/blueprint/MAP.md` → `INTERFACE.md`（按需）→ `platform.toml` | 模块在哪、工具签名是什么 | 按需 |
| D 为什么 | `docs/internal/blueprint/DECISIONS/` → `CHANGELOG.md [Unreleased]` | 设计取舍、近期在做什么 | 按需 |
| E 冷冻 | `docs/internal/{design,plans,specs}/`、`docs/superpowers/**` | **只用来理解「当时为什么」，不当作现状** | 极少 |

**`SNAPSHOT.md` 的用法**：它自称周更快照，但先看 `base_commit:` 与 `git log -1 --format=%H` 的差距；差得远就**跳过它的细节**，改用 `MAP.md` + 代码。别把过期快照当事实。

**不要读**：`CHANGELOG.md` 全文（597 行，只读 `[Unreleased]` 与最近两节）、四份 `docs/platforms/*.md` 全文（按主题挑一份）、`platforms/*/skills/`（那是产品给调用方 agent 的规范，只在改产品行为时读）。

---

## 2. 体检命令（能跑就跑，跑不了要明说）

在仓库根执行；每条都记录「命令 / 结果 / 是否为本机能力限制」。

```powershell
# 2.1 仓库状态与版本事实
git log -1 --format="%h %ad %s" --date=short
git rev-list --left-right --count main...$(git tag -l --sort=-v:refname | Select-Object -First 1)
git tag -l --sort=-v:refname | Select-Object -First 3

# 2.2 文档漂移（工具数 + 端口表）。预期在当前 main 上是 exit 1，不算你的锅
python3 scripts/gen_docs.py --check

# 2.3 代码契约与共享层（--basetemp 必带；仓库外目录，避免污染工作区）
python3 -m pytest platforms/tests -q --basetemp="$env:TEMP\af-init\pt"
python3 -m pytest platforms/common/tests -q --basetemp="$env:TEMP\af-init\ct"
#   Windows 上预期 ~10 个环境性失败（bash 硬编码 / GBK 解码 / 路径进 regex），不是回归

# 2.4 只有本机有 bash / pwsh 7 才做（Windows 裸机通常没有 → 记「交 CI」）
# ./scripts/gen-blueprint-map.sh --check
# ./scripts/gen-blueprint-interface.sh --check
# ./scripts/check-blueprint-refs.sh
# ./scripts/check-ps-syntax.sh

# 2.5 CLI（依赖未装会直接 collection error，先 uv sync 或 pip install -e ".[dev]"）
cd cli; $env:PYTHONPATH="src"; python3 -m pytest -q; cd ..
```

macOS / Linux 把 `--basetemp` 换成 `/tmp/af-init/...`、`$env:X` 换成 `X=` 即可；`bash` 门禁那边可以真跑。

---

## 3. 三个「真源」交叉核对（关键，别只读文档）

### 3.1 工具清单：静态 vs 运行时

```powershell
# 静态：每个平台的 core 工具（不含运行时注入的可选能力）
python3 -c "import sys; sys.path[:0]=['platforms','platforms/tests']; from _ast_tools import extract_mcp_tools as e; import glob; [print(p, len(e(p))) for p in glob.glob('platforms/*/server/*_mcp.py')]"
```

运行时（**唯一权威**）：如果本会话挂了设备 MCP，直接调该设备的 `list_capabilities()`，看每个能力模块的 `status / tools`。

要点：`core ≠ 总数`。总数 = core + `list_capabilities`(1) + 每个 `enabled` 可选能力的工具数；`human_dom` 是 opt-in（无 `~/.fleet/human-dom-ready` 即 0）。

### 3.2 生成物是否与代码同步

- `INTERFACE.md` 里每个平台的工具条数 vs 上面 3.1 的静态值；
- `MAP.md` 的平台/模块条目 vs `ls platforms/`；
- 若不齐 → 记一条漂移（**不要**在装载阶段跑生成器改文件）。

### 3.3 文档数字是否落后

- 根 `README.md` 的 `<role> N tools` 与 §3.1 静态值对比；
- 平台 `README.md`、`docs/platforms/*.md` 附录 A 的 core 数字对比；
- `ONBOARDING.md` 与 `docs/roadmap.md` 里的数字/日期：**默认不可信**，只在报告里指出，不引用为事实。

---

## 4. 输出：一份可交接的报告

按下面五段写，控制在一屏到两屏；每条结论带证据（`路径:行号` 或命令输出关键行）。

```markdown
## agent-fleet 装载报告 · <日期> · <commit>

**1. 一句话现状**：产品是什么、当前版本线（tag / main 领先几个 commit）、最近在做什么。

**2. 拓扑与入口**：四平台端口与 server 入口、共享层位置、能力框架与可选能力现状（哪些 enabled / 哪些 opt-in）。

**3. 门禁实况**：每条体检命令的结果（绿/红/本机跑不了），并说明「红的是存量还是本次引入」。

**4. 漂移清单**：文档 vs 代码的不一致（数字、命名、过期快照、版本钉死），每条给「位置 / 它说 / 实际 / 建议动作」。与 `docs/project-map.md` §9 对得上就写「已知」，对不上就标「新发现」。

**5. 下手建议**：按用户目标给 1–3 条具体路径（改哪个文件、跑哪个门禁、走哪种 PR 模板），并指出哪一步本机做不了、需要 CI 或真机。
```

若用户要的是持续维护而不是一次性报告：报告落地为更新 `docs/project-map.md` 的「核对记录 + 漂移登记」，走 `docs/` 分支 + `docs:` commit + docs PR 模板（见 `AGENTS.md` §3）。

---

## 5. 边界（这个技能不做的事）

- **不改代码、不跑生成器、不动 `docs/internal/blueprint/`**——那些是代码 PR 的职责。
- **不修文档漂移**：装载阶段只登记；修复要单独立项（一处一 PR）。
- **不引用过期快照/路线图当事实**，也不把 `docs/internal/**` 的旧结论说成「现在就是这样」。
- **不在本机对脚本类门禁下结论**：没有 bash / pwsh 7 就是「未验证，交 CI」。
