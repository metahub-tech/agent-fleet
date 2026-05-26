# ADR 0001 · 平台目录采用自包含 6 件套结构

- **状态**：Accepted（2026-04 上线，2026-05-26 retrospective 写入 ADR）
- **决策人**：qin-jiangli
- **影响范围**：`platforms/` 下所有平台目录

## 上下文

agent-fleet 要支持多平台（Windows / macOS / Linux / Android / iOS），需要决定：每平台的代码 / 文档 / 安装脚本应该如何在仓库里组织？

候选有三：

1. **按层划分**（`server/`、`scripts/`、`docs/`、`examples/` 各自分平台子目录）
2. **按平台划分 · 自包含**（`platforms/<name>/` 下放所有该平台需要的东西）
3. **混合**（共享代码层 + 平台桥层）

## 决定

采用 **2 · 按平台自包含**。每个 `platforms/<name>/` 必须含 6 件套：

```
platforms/<name>/
├── platform.toml      # manifest（id/port/host_os/启用能力）
├── README.md          # 平台速查
├── server/            # MCP server 源码
├── scripts/           # 安装脚本（setup-<name>.<ext>）
├── skills/            # agent 用的 skill 文档
└── examples/          # 参考配置
```

## 理由

- **降低跨平台心智负担**：贡献者改 Windows 时不需要跳到三个分散位置（按层划分会让你同时碰 docs / scripts / server 各自的 windows 子项）——一个 platforms/windows/ 全在
- **削减"找不到"的报错**：新平台加入只需 `cp -r platforms/windows platforms/<new>` 改文件名，模式可复用
- **CI 友好**：platforms/\* glob 就能跑全平台并行测试
- **隔离失败爆炸半径**：单平台编译/测试出错不污染共享层
- **强一致 = 可生成性**：MAP/INTERFACE 这类蓝图能用 platforms/\* 通配自动扫，不需要维护清单

## 拒掉的备选

- **按层划分**：会让新人在多个目录间反复跳；新平台加入要改 5+ 处
- **混合（共享 + 平台桥）**：共享层会迅速变成"什么都往里塞"的垃圾桶；后期拆分代价高

## 后果与约束

- 一些跨平台共享代码不可避免——专门放 `platforms/common/`（小、严格约束）
- 平台桥之间**不互相 import**——任何跨平台共享都必须经过 `common/`
- 新增平台的 PR 必须满足 6 件套完整（见 `CONTRIBUTING.md` "添加新平台" 章节）
- 4 个平台桥结构一致，**以 `platforms/windows/` 为参考实现**

## 相关引用

- `CONTRIBUTING.md` 节"添加新平台 (`platforms/<name>/`)"
- `docs/install-pattern.md` 平台安装的通用模式
- `docs/internal/blueprint/MAP.md` 自动生成的模块地图（基于这个结构）
