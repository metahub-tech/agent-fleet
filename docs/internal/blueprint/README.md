# Project Blueprint · agent-fleet 项目全貌册子

> 给任何 agent / contributor 装载用——读完这份目录里的文件，你应该对项目有完整的"鸟瞰"：模块在哪里、对外暴露什么工具、为什么这么设计、还有哪些待办。
>
> **不是给人类一次性读完的文档**——而是给 LLM agent（如 Iris 审文档、Aria 写技术博客）"装载即获全貌"用的结构化资产。

## 五块结构

| 文件 | 性质 | 维护方式 |
|---|---|---|
| `MAP.md` | 模块地图 | **自动生成**——`scripts/gen-blueprint-map.sh` 扫 `platforms/` + `cli/` + `scripts/` + `docs/` 顶层，CI 用 `--check` 把门 |
| `INTERFACE.md` | MCP 工具签名清单（universal tool set） | **自动生成**——`scripts/gen-blueprint-interface.sh` 用 `ast` 模块从 `platforms/*/server/*_mcp.py` 反射所有 `@*.tool` 装饰的函数 |
| `DECISIONS/` | ADR 序列（架构决策史） | **一次写入** append-only：每个重要决定一个文件 `<编号>-<slug>.md`，状态 Proposed / Accepted / Superseded；老 ADR 永不修改，推翻就开新 ADR 用 `Supersedes #N` 引用 |
| `GLOSSARY.md` | 术语表 | **半自动**——手写术语 + 关联代码路径；`scripts/check-blueprint-refs.sh` 校验里头引用的路径都真实存在 |
| `SNAPSHOT.md` | 项目全貌快照 | **自动生成 + 手写编辑**——每周一由 `Atlas` 跑生成器拼装最新 MAP/INTERFACE/ADR/active issues |

## 为什么这样设计

老式手维护"全貌文档"必然漂移——本仓库的 `docs/internal/README.md` 自己都写过 "may be out of date with the current codebase"。本结构解决方式：

- 会脱节的部分（模块地图、接口签名）**从代码自动再生 + CI 把门**——改代码不更新 = CI 红 = PR 合不了
- 不脱节的部分（决策史）用 ADR **一次写入不需同步**——老决定永远准确
- 半结构化的部分（术语）**用 CI 校验路径有效性**作为最低保证

详细规范见 `metahub-tech/ops:docs/BLUEPRINT-SPEC.md`。

## 装载顺序

任何 agent 想拿"全貌"时按这个顺序读：

1. `SNAPSHOT.md` —— 一份最新综合快照
2. 按需深入：`MAP.md`（要找模块）、`INTERFACE.md`（要查工具签名）、`DECISIONS/`（要懂为什么这么做）、`GLOSSARY.md`（要明白术语指代）

## 谁负责

- **Atlas** 在 `metahub-tech/ops:agents/atlas/persona.md` 写明：每动 `platforms/` 或 `cli/` 就跑生成器同步；每做重大决定写 ADR；每周一更新 SNAPSHOT
- **Iris** 在 `metahub-tech/ops:agents/iris/persona.md` 写明：装载蓝图做异源审阅，发现蓝图与代码不符时**只派回 Atlas 修，自己不改**

## 维护操作

```bash
# 改完代码同步蓝图
./scripts/gen-blueprint-map.sh
./scripts/gen-blueprint-interface.sh

# 校验
./scripts/check-blueprint-refs.sh

# 写新 ADR
ls docs/internal/blueprint/DECISIONS/  # 看最大编号
$EDITOR docs/internal/blueprint/DECISIONS/000N-<slug>.md
```
