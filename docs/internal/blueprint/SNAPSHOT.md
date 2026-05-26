# Project SNAPSHOT · 项目全貌快照

> 给任何 agent 装载用——读完这一份就拿到 agent-fleet 当下的鸟瞰全貌。
>
> **每周一由 Atlas 更新一次**（人工或 cron）；当前是 **2026-05-26** 修订（Phase 1 工程地基落地 + blueprint-drift 一次修订）。

**base_commit**: `448e957af93ca91ab899c3a026a9e19bdaaa9db7`
（将来由 gen-blueprint-snapshot.sh（待建）自动注入；当前手工填——Iris 装载时按这个 SHA 校验，比日期更可靠。）

## 项目一句话

agent-fleet 是一套**让 LLM agent 操作真实物理设备的 MCP 基座**——四个平台（Windows / macOS / Android / iOS）各有一个设备桥 MCP server，agent 通过统一工具集（`take_screenshot` / `tap` / `launch_app` / …）跨设备操作，切设备只是换一个 URL。

详见 `docs/architecture.md`。

## 模块鸟瞰

完整地图见 `docs/internal/blueprint/MAP.md`（自动生成）。一句话：

- 四个平台桥（自包含 6 件套）：`platforms/{windows,macos,android,ios}/`
- 跨平台共享：`platforms/common/`
- 编排 CLI：`cli/src/fleet/`
- 运维脚本：`scripts/`
- 文档：`docs/{architecture,install-pattern,roadmap}.md` + `docs/platforms/<name>.md`

## 工具集（universal tool set）

完整签名清单见 `docs/internal/blueprint/INTERFACE.md`（自动生成）。

四平台目前都提供的工具组（语义跨平台一致）：

| 组 | 工具 | 用途 |
|---|---|---|
| device-lifecycle | `acquire` / `release` / `get_status` / `list_devices` / `set_default_device` / `get_default_device` | 设备资源租约 |
| screen | `take_screenshot` / `get_screen_size` | 屏幕状态 |
| input | `tap` / `swipe` / `press_key` / `type_text` | 模拟用户输入（跨四平台一致） |
| input (mobile-only) | `long_press` | 仅 Android / iOS；桌面平台暂未对齐（可用 `tap` + sleep 间接） |
| app | `launch_app` / `terminate_app` / `current_app` | 应用生命周期 |
| ui-tree | `dump_ui` / `find_elements` / `tap_element` | 无障碍树（OS 级 UI 探查） |

平台特定扩展（如 macOS / Win 的 `browser_*` 系列 + `human_browser_open`）由**能力框架运行时动态注入**——它们不是 `@mcp.tool` 静态装饰函数，因此**不在 `INTERFACE.md` 静态清单内**。取真实运行时清单的两条路：
1. 装载时调 `list_capabilities()`（框架统一注入，每平台都有）
2. 读各平台 README 的 `### 浏览器能力（可选）/ Platform-specific extensions` 节

## 决策史（ADR）

完整 ADR 见 `docs/internal/blueprint/DECISIONS/`。当前在册：

- `DECISIONS/0001-platform-self-contained-structure.md` —— 平台目录 6 件套约定（Accepted）
- `DECISIONS/0002-universal-tool-set.md` —— 跨平台工具命名规范（Accepted）

下一批待写：iOS WDA 集成方式、端口段位分配、blueprint 蓝图机制本身（这条要补一条 0003 retrospective）

## 工程地基（Phase 1 · 2026-05-26 落地）

- **License**：Apache 2.0（canonical 文本，GitHub 已识别徽章）
- **CI**：`shell-syntax` + `powershell-syntax` + `blueprint-check` 三个 required；`python-tests` 非 required（待 cli 稳定）
- **分支保护**：main 必经 ≥1 真人审批 + 三个 required status check + `CODEOWNERS` 钉敏感路径
- **DCO**：CONTRIBUTING 已要求 Signed-off-by；DCO App 安装见 `metahub-tech/ops:docs/ACTIVATION.md`
- **蓝图生成器**：`scripts/gen-blueprint-{map,interface}.sh` + `scripts/check-blueprint-refs.sh`

## 当前活跃的关键 issue / PR

_暂无（项目早期 alpha，0 外部 contributor）。当有真实进展时这里由 Atlas 维护一份 ≤10 条的"本周热点"清单。_

## 待补 / 已知漂移

- iOS WDA 客户端实现细节未进 ADR
- `platforms/common/` 共享代码作用范围未文档化
- `human_browser` 能力仅 win / mac 实现，android / iOS 无可对应能力（运行时通过 `list_capabilities` 自报，文档侧待统一注明）
- gen-blueprint-snapshot.sh 尚未实现——SNAPSHOT 周更目前手工跑（见 BLUEPRINT-SPEC §二.5、blueprint-maintenance SOP §Step 5）；该脚本到位后 `base_commit:` 行将由它自动写入

---

_快照基线 = 上面的 `base_commit:`；偏差 > 7 天即视为过期，Iris 装载前会校验并 stop cc Atlas。日期是辅助字段，SHA 才是权威。_
