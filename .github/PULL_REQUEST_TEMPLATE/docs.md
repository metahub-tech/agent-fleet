<!-- 文档类 PR 模板。用法：gh pr create 时按本结构填 body，或网页 PR URL 后加 ?template=docs.md -->

## 摘要 / Summary

<!-- 这个 PR 改了哪些文档、为什么，1-3 句 -->

## 改动 / Changes

<!-- 逐条列出改了哪些文件 / 章节 -->

-

## 文档自查 / Docs checklist

- [ ] 工具数 / 工具名来自 `list_capabilities` 或 `extract_mcp_tools`（非手抄）
- [ ] `python3 scripts/gen_docs.py --check` 通过（若涉及工具数）
- [ ] 中文为主、路径 / 命令 / 标识符保留英文；按「占位符 → 步骤 → 验证」结构
- [ ] 连带项已同步：平台 `README.md` 速查表、`CHANGELOG.md` `[Unreleased]`
- [ ] 9 语 README：改了 `README.md` 则已同步 `zh-CN`（其余未同步语言在下方列出）
- [ ] 未夹带代码 / 契约改动（如需，已另开 Issue 链接在此）

## 待同步语言 / Locales pending（如有）

<!-- 列出本 PR 暂未同步的 README 语言版本，便于 reviewer 安排 -->

---

> 开 PR 后请打 **`needs-review`** 标签并 @ reviewer。纯文档 PR 不需要跑 pytest。详见 [`ONBOARDING.md`](../../ONBOARDING.md)。
