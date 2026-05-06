# Contributing to agent-test-bench

> **当前状态**：私有 alpha。MetaHub Tech 内部维护。开源发布以 v1.0.0 为目标，预计在四大平台桥（Windows / macOS / Android / iOS）全部稳定且工具公约冻结后发起。
>
> **Status**: private alpha. Maintained internally by MetaHub Tech. Public open-source release is targeted at v1.0.0, after all four platform bridges (Windows / macOS / Android / iOS) stabilize and the tool contract is frozen.

## 本仓库的迭代约定

下列规则同时适用于私有阶段与开源后。早期就照着开源标准写，开源时无需重构。

### 添加新平台 (`platforms/<name>/`)

新平台目录必须自包含，子结构与 `platforms/windows/` 对齐：

```
platforms/<name>/
├── README.md          # 平台快速上手 + 工具速查
├── server/            # MCP server 源码 + requirements.txt + pyproject.toml
├── scripts/           # 安装脚本（setup-<platform>.<ext>）
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
- 任何 destructive 操作前打印确认信息
- 脚本支持 idempotent 执行（重跑不破坏现有环境）

### 文档
- 中文为主（项目主要使用者是中文母语开发者）
- 路径、命令、变量名保持英文原文
- 操作手册按"占位符约定 → 步骤 → 验证清单"结构

## Versioning

遵循 [Semantic Versioning](https://semver.org/)：

- **Major** (`X.0.0`): Universal Tool Set 公约破坏性变更（工具改名 / 删除 / 参数语义改变）
- **Minor** (`x.Y.0`): 新增平台 / 新增非破坏性工具 / 新增重要文档
- **Patch** (`x.y.Z`): bug 修复 / 文档勘误 / 依赖小版本升级

## 发起变更

### 私有阶段（MetaHub 内部）
- 直接在 main 分支提 PR；至少一名 reviewer approval 后合并
- 大变更（新平台 / 工具公约修改）开 issue 讨论后再动手

### 开源后
TBD —— v1.0.0 发布前会更新此节，包括：
- DCO / CLA 政策
- Issue / PR 模板
- 行为准则 (Code of Conduct)
- Maintainer 列表与决策机制
