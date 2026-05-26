# ADR 0002 · Universal Tool Set（跨平台工具命名规范）

- **状态**：Accepted（2026-04 上线，2026-05-26 retrospective 写入 ADR）
- **决策人**：qin-jiangli
- **影响范围**：所有 `platforms/*/server/*_mcp.py`

## 上下文

四个平台桥（Windows / macOS / Android / iOS）都要暴露给 agent 一些常用能力：截屏、点击、输入文字、启动应用。问题：

- 同一语义的工具，是按平台习惯命名（`adb_screenshot` / `screencapture` / `screenshot`），还是统一名字？
- 工具签名（参数名 / 返回结构）跨平台要不要严格一致？

## 决定

采用 **统一命名 + 统一签名 + 平台特定扩展单列** 的"universal tool set"模式：

1. 跨平台同一语义的工具 → **同一个名字**：`take_screenshot` / `tap(x, y)` / `swipe(x1,y1,x2,y2)` / `launch_app(target)` / `dump_ui()` ...
2. 参数语义跨平台对齐：例如 `target` 在 4 个平台都接受应用标识（Win 是 exe 路径或 AppUserModelID；Android 是 package id；macOS 是 bundle id / app 名；iOS 是 bundle id）；agent 无须了解平台细节就能用
3. 返回结构对齐到统一形态（已建立 `dump_ui` 返回形契约——见 commit b3a441b）
4. 平台**特有**的工具放 `platforms/<name>/README.md` 的 "Platform-specific extensions" 段，**不**与 universal 名字冲突

## 理由

- **agent 跨设备零认知成本**：切设备 = 换 URL，工具调用语法不变
- **可生成的蓝图**：`scripts/gen-blueprint-interface.sh` 能简单 ast.parse 出所有 `@*.tool` 装饰的函数列表，跨平台一比就能发现命名偏离
- **测试组合爆炸可控**：一份"跨平台契约"测试套就能覆盖 4 平台
- **新平台加入的天然门槛**：必须实现 universal tool set 才能算"接进 fleet"，质量底线明确

## 拒掉的备选

- **按平台习惯命名**：agent 无法跨设备复用代码；蓝图无法对齐；测试爆炸
- **只规定参数而不规定名字**：agent 切设备时仍要查表，认知成本高

## 后果与约束

- 新增工具时**先看 universal tool set 里有没有同义名**——有则复用，没有再起新名（命名一旦上线就难改）
- universal 工具的签名/语义变更 = 破坏性改动 → 必须 ADR + 全平台同步
- 平台特定扩展工具必须在该平台 `README.md` 的 "Platform-specific extensions" 段登记，不写则视为非契约工具

## 相关引用

- `docs/architecture.md` Universal Tool Set 章节
- `CONTRIBUTING.md` "给现有平台加工具" 章节（含 universal vs platform-specific 的分类规则）
- `docs/internal/blueprint/INTERFACE.md` 自动生成的工具签名清单（横向对比平台间一致性的最准依据）
