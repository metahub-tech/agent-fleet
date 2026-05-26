# agent-fleet 运营/内容团队 · 上手指南（ONBOARDING）

> 给加入 agent-fleet 运营团队、负责撰写各平台文档的 **Claude Code agent**。读完本文你应能：看懂项目、知道自己该动哪些文件、按 PR 流程提交文档并交由 reviewer 审核合并。**遇到本文未覆盖的方向性问题，问人类负责人，不要自行扩大改动范围。**

---

## 1. 一句话定位

agent-fleet 是一套**让 agent 操作真实物理设备的 MCP 基座**：四个平台（Windows / macOS / Android / iOS）各有一个设备桥 MCP server，agent 通过统一工具集（`take_screenshot` / `tap` / `launch_app` / …）跨设备操作，切设备只是换一个 URL。详见 [`docs/architecture.md`](docs/architecture.md)。

你的角色：**写文档**——平台 setup 指南、工具速查、skill 文档、多语 README。

---

## 2. 仓库导览 · 你该动哪些、别动哪些

```
agent-fleet/
├── README.md + README.<lang>.md   # 9 语版本（en 为源，其余 8 语跟随）
├── CONTRIBUTING.md                 # 工程基线 + 文档贡献规范（务必先读）
├── docs/
│   ├── architecture.md / install-pattern.md / roadmap.md  # 共享设计文档
│   ├── platforms/<name>.md         # ★ 各平台 setup 指南（你的主战场之一）
│   └── internal/                   # ✗ 内部设计留档，只读勿改
├── platforms/<name>/               # 每平台一个自包含 bay（6 件套）
│   ├── platform.toml               # manifest：id/port/host_os/启用的能力
│   ├── README.md                   # ★ 平台速查（工具表等，你会改）
│   ├── server/                     # ✗ MCP server 源码（改它属于代码改动，见 §7 边界）
│   ├── scripts/                    # ✗ 安装脚本
│   ├── skills/using-<name>/        # ★ 给 agent 用的 skill 文档（你会改）
│   └── examples/                   # 参考配置
└── CHANGELOG.md                    # 改文档也要在 [Unreleased] 记一笔
```

**★ = 你的主战场**：`docs/platforms/<name>.md`、`platforms/<name>/README.md`、`platforms/<name>/skills/`、9 语 `README*.md`。
**✗ = 别动**：`server/`、`scripts/`、`docs/internal/`、`platform.toml`、任何代码。需要它们变动 → 见 §7。

平台目录是 **6 件套**（`platform.toml` + `README.md` + `server/` + `scripts/` + `skills/` + `examples/`），四平台结构一致，以 `platforms/windows/` 为基准参照。

---

## 3. 工具数 / 工具名：以代码为准，别手数

文档里写工具数量或工具清单时，**不要照抄旧文档，也不要凭印象**——用仓库自带的事实源：

- 看某平台**运行时真实暴露**了哪些能力与工具：让接了该设备的 agent 调 `list_capabilities`（返回每个能力模块的 id / status / tools）。
- 看某 server 的工具与数量（静态、本地可跑）：
  ```bash
  python3 - <<'PY'
  import sys; sys.path.insert(0,"platforms"); sys.path.insert(0,"platforms/tests")
  from _ast_tools import extract_mcp_tools
  print(sorted(extract_mcp_tools("platforms/windows/server/win_device_mcp.py")))
  PY
  ```
- 工具总数口径（重要）：`server 的 @mcp.tool` **不含** `list_capabilities`（它由框架统一注册，每个平台运行时都额外有这 1 个）；win/mac 还额外有可选 browser 能力，**android/ios 当前只有 `list_capabilities`、无可选能力**。当前总数：**win 71 / mac 70 / android 26 / ios 27**。改 README 工具数后跑 `python3 scripts/gen_docs.py --check`（drift 会让它非零退出）。

---

## 4. 文档风格指南

- **中文为主**（主要使用者是中文母语开发者）；**路径、命令、文件名、变量名、API/工具名、日志原文保留英文**。
- 操作手册按「**占位符约定 → 步骤 → 验证清单**」结构组织。
- 与同目录现有文档的章节风格、表格格式保持一致；不要自创排版。
- 术语统一（部分约定）：`<os>-device`（角色名，如 `win-device`）、jump host / 跳板、Universal Tool Set（通用工具集）、capability（能力模块）、proxied / self-built（能力来源）。新术语拿不准 → 问负责人，别各处各译。
- **不要把中文写进 `.ps1`/shell 脚本**（Win PowerShell 5.1 在非 UTF-8 locale 会乱码）；本地化文案放 docs/。

---

## 5. 改一处，要连带改哪些

文档之间有耦合，改一个点别漏了下游：

- 改某平台的工具/步骤 → 同步 `docs/platforms/<name>.md`（setup 指南）**和** `platforms/<name>/README.md`（速查表）。
- 改工具数/工具名 → 跑 `gen_docs.py --check`；涉及 README.md 数字时确认通过。
- 任何用户可见的文档变化 → 在 `CHANGELOG.md` 的 `[Unreleased]` 加一条。
- **9 语同步规则**：`README.md`（英文）是**源**。改了它的结构/内容 → 在**同一个 PR** 里同步更新 `README.de/es/fr/ja/ko/pt-BR/ru/zh-CN.md` 的对应处（至少 `zh-CN`；其余语言若你不具备能力，在 PR 里显式列出"待同步的语言"，便于 reviewer 安排）。不要让英文与各语言版本结构漂移。

---

## 6. 提交流程：PR → reviewer 审核 → 合并

我们走**异步 PR 门禁**，由 reviewer（主 Claude）审核后合并。

1. 从 `main` 切分支：`git checkout -b docs/<platform>-<短描述>`（如 `docs/windows-browser-section`）。
2. 改文档，commit 粒度小、message 用 `docs:` 前缀（如 `docs: 补 windows browser 能力章节`）。
3. 本地自检：`python3 scripts/gen_docs.py --check`（涉及工具数时）；**纯文档 PR 不需要跑 pytest**。
4. 开 PR 指向 `main`，**套用 docs PR 模板**（`gh pr create` 时按 `.github/PULL_REQUEST_TEMPLATE/docs.md` 的结构填 body，或在网页 PR URL 后加 `?template=docs.md`）。
5. 给 PR 打 **`needs-review`** 标签、在描述里 @ reviewer。
6. reviewer 审核（对照真实代码核准确性、术语一致、本地化质量）→ 留评论或 approve → **由 reviewer 合并**。请按评论修订后回复，不要自行合并。

---

## 7. 边界：哪些不能塞进文档 PR

- **不改代码/契约**：`server/`、`scripts/`、`platform.toml`、工具签名/返回形等属于代码改动。文档发现与代码不符时，**开一个 Issue** 说明，不要在文档 PR 里顺手改代码。
- **新平台 / 工具契约变更**：先开 Issue 讨论，不夹带进文档 PR。
- 一个 PR 只做一件事；不要同时改文档又重排目录。

---

## 8. 审核标准（占位）

详细的文档审核章程由人类负责人后续同步。在此之前，reviewer 以通用基线把关：**准确（与代码/能力一致）、术语统一、结构清晰、本地化质量过关、无未声明的代码改动**。

---

## 9. 快速校验清单（提交前自查）

- [ ] 只动了 §2 标 ★ 的文件，没碰 ✗ 区域。
- [ ] 工具数/工具名来自 `list_capabilities` 或 `extract_mcp_tools`，非手抄。
- [ ] `python3 scripts/gen_docs.py --check` 通过（若涉及工具数）。
- [ ] 中文为主、英文标识符保留；按「占位符→步骤→验证」结构。
- [ ] 连带项已处理：平台 README 速查、`CHANGELOG.md [Unreleased]`、9 语同步（或在 PR 列出待同步语言）。
- [ ] 分支 `docs/...`、commit `docs:` 前缀、套 docs PR 模板、打 `needs-review`、@reviewer。
