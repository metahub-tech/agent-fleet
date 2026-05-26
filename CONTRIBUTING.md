# Contributing to agent-fleet

> **Early-stage alpha — expect breaking changes.**
> All four platform bridges (Windows / macOS / Android / iOS) are still stabilizing and the tool contract is not yet frozen. Contributions are welcome; just be aware that things may shift under you while we iterate toward v1.0.
>
> 项目处于早期 alpha 阶段，接口尚未冻结，预期有破坏性变更。欢迎贡献——请留意 v1.0 之前可能还有较大重构。

## 本仓库的迭代约定

下列规则是仓库的工程基线，所有改动都应遵循。

### 添加新平台 (`platforms/<name>/`)

新平台目录必须自包含，子结构与 `platforms/windows/` 对齐：

```
platforms/<name>/
├── platform.toml      # manifest：id / port / host_os / [capabilities].enabled / 安装入口
├── README.md          # 平台快速上手 + 工具速查
├── server/            # MCP server 源码 + requirements.txt + pyproject.toml
├── scripts/           # 安装脚本（setup-<platform>.<ext>）
├── skills/            # 给 agent 用的 skill 文档（using-<platform>/SKILL.md 等）
└── examples/          # claude-settings.json 等参考配置
```

并满足：

1. 实现 [`docs/architecture.md`](docs/architecture.md) 的 **Universal Tool Set** —— 通用工具名与语义保持一致，平台扩展工具单独命名
2. 在 `docs/platforms/<name>.md` 写完整 setup guide（参考 `windows.md` 的章节结构）
3. 在 `docs/roadmap.md` 把对应版本状态从 📋 / 🚧 改为 ✅
4. 在 `CHANGELOG.md` `[Unreleased]` 段加 `### Added` 条目
5. 端口分配遵循 [`docs/architecture.md#segment-3`](docs/architecture.md) 的预留表（避免多桥共主机时冲突）

### 给现有平台加工具

1. 在 `server/` 下加工具实现
2. 在该平台的 `README.md` 工具速查表里登记
3. 如果属于 Universal Tool Set 范围，工具名必须与其他平台一致；否则放在 "Platform-specific extensions" 段
4. `CHANGELOG.md` `[Unreleased]` 段加条目
5. 修改 setup-guide 中的工具列表

### 修 bug / 重构

- 提交粒度小：一个 commit 一件事
- commit message 用动词开头："fix: ...", "refactor: ...", "docs: ..."
- 不在一次提交里同时改实现和重排目录结构

## 编码约定

### Python (各平台 server/)
- 类型标注：所有 MCP tool 函数必须有 `Annotated` 参数标注与返回类型
- 格式化：Black 兼容 (line-length 100)
- 不写 docstring 解释"做什么"——工具名+参数标注已经说清楚；只在有非显然约束时写一行 `"""..."""`
- 错误处理：MCP tool 内部捕获预期异常并返回结构化错误（`{"ok": False, "error": "..."}`），不要让 server 因单个 tool 调用崩溃

### PowerShell / Shell scripts
- PowerShell 脚本头加 `$ErrorActionPreference = "Stop"`
- **PowerShell 脚本必须保持纯 ASCII / 英文**（含注释和 Write-Host 字符串）。Windows PowerShell 5.1 在中文/日文等非 UTF-8 默认 locale 下，会用系统代码页（如 GBK）解析无 BOM 的 .ps1 文件，导致中文乱码 + 解析失败。本地化文案放进 docs/，不放进脚本
- **改完任何 .ps1 后跑 `./scripts/check-ps-syntax.sh`** 做 AST 校验（需要 pwsh 7+，安装命令在脚本头部注释里）。这能在 push 前抓到 `foreach { } | Format-Table` 之类只在运行时才暴露的语法问题
- 处理外部命令的 stdout 时，脚本顶部加 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，避免 Win PS 5.1 用 OEM 代码页误读 UTF-8 输出
- 任何 destructive 操作前打印确认信息
- 脚本支持 idempotent 执行（重跑不破坏现有环境）

### 文档
- 中文为主（项目主要使用者是中文母语开发者）
- 路径、命令、变量名保持英文原文
- 操作手册按"占位符约定 → 步骤 → 验证清单"结构

## 贡献文档（运营 / 内容团队）

运营 / 内容团队的完整上手见 [`ONBOARDING.md`](ONBOARDING.md)。核心规则：

- **主战场**：`docs/platforms/<name>.md`、`platforms/<name>/README.md`、`platforms/<name>/skills/`、9 语 `README*.md`。**不动** `server/` / `scripts/` / `platform.toml` / `docs/internal/`（这些属代码改动，需先开 Issue）。
- **工具数 / 工具名以代码为准**：用 `list_capabilities`（运行时）或 `extract_mcp_tools`（静态）取真实清单，别手抄；改工具数后跑 `python3 scripts/gen_docs.py --check`。
- **9 语同步**：`README.md`（英文）为源，改其结构 / 内容须在同一 PR 同步各语言版本（至少 `zh-CN`），未同步的语言在 PR 里显式列出。
- **流程**：从 `main` 切 `docs/...` 分支 → `docs:` 前缀 commit → 套用 [docs PR 模板](.github/PULL_REQUEST_TEMPLATE/docs.md) → 打 `needs-review` 标签 + @ reviewer → reviewer 审核后合并（纯文档 PR 免跑 pytest）。

## Versioning

遵循 [Semantic Versioning](https://semver.org/)：

- **Major** (`X.0.0`): Universal Tool Set 公约破坏性变更（工具改名 / 删除 / 参数语义改变）
- **Minor** (`x.Y.0`): 新增平台 / 新增非破坏性工具 / 新增重要文档
- **Patch** (`x.y.Z`): bug 修复 / 文档勘误 / 依赖小版本升级

## 发起变更

### Contribution flow

1. **Fork** the repo and create a branch from `main`:
   ```bash
   git checkout -b fix/short-description
   ```
2. **Make your change.** Keep commits small (one logical change per commit).
   Commit messages: `fix: ...`, `feat: ...`, `docs: ...`, `refactor: ...`
3. **Run the tests** before pushing:
   ```bash
   # Python (CLI package)
   cd cli && PYTHONPATH=src python3 -m pytest

   # Shell scripts — syntax check only (no execution needed)
   bash -n scripts/install-agent-side.py  # python, skip
   find platforms/ scripts/ -name '*.sh' -exec bash -n {} \;

   # PowerShell syntax (requires pwsh 7+)
   ./scripts/check-ps-syntax.sh
   ```
4. **Open a Pull Request** against `main`. Fill in the PR template.
   - For large changes (new platform, tool-contract modifications) open an
     **Issue first** to discuss before writing code.
   - At least one maintainer approval is required before merge.

### 提问 / Questions

有疑问请在 [GitHub Issues](https://github.com/metahub-tech/agent-fleet/issues) 或
[GitHub Discussions](https://github.com/metahub-tech/agent-fleet/discussions) 提出。
Questions and discussion → GitHub Issues or Discussions.

### 行为准则 / Code of Conduct

本项目遵循 [Contributor Covenant v2.1](CODE_OF_CONDUCT.md)，参与即表示同意该准则。
