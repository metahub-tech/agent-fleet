# 扩展基座设计：让 agent-fleet 接入"所有设备"且易维护、强隔离

> 状态：设计稿（待评审）· 2026-05-21
> 目标读者：核心维护者 + 未来贡献者

## 一、目标与背景

愿景：**agent 经"电脑做跳板"接入任意人能管理的设备**（已落地 Windows/macOS/Android/iOS，下一个 HarmonyOS）。本设计为"接入更多设备/能力"打地基，满足三条硬约束：

1. **可扩展**：加一个平台桥是低摩擦、可预测的流程。
2. **易维护**：更多贡献者加入后，逻辑只存一份、契约清晰。
3. **强隔离**：新增设备**不波及现有平台**（加平台只做加法，错误被隔离 + 测试门禁兜底）。

决策前提（已与负责人确认 2026-05-21）：
- **工具命名可 breaking**：当前仅内部使用，统一后重装重连即可，无需向后兼容/弃用期。
- 范围：完整基座 P0–P4。
- 共享核心继续放 `platforms/common/`（android/ios 已 import），不另起独立包。

## 二、现状复盘（证据，2026-05-21 代码勘察）

| 维度 | 现状 | 问题 |
|---|---|---|
| 服务端复用 | win/mac server **~74% 复制粘贴**（holder、长任务 session、文件操作、搜索各抄一遍）；仅 android/ios 共用 `common/` | holder **双实现**：win/mac 旧单 `_Holder`，android/ios 新 `DeviceStateRegistry` → 一处逻辑改 3+ 处 |
| Universal Tool Set | **仅文档约定，零代码强制** | 真发散：`click`/`tap`、`launch_app`/`open_app`/`start_app`、`press_key`/`press_button`、`inspect_window`/`list_ui_elements`/`dump_ui_hierarchy`、`run_powershell`/`run_zsh`/`adb_shell`/无；文档与代码对不上；无一致性测试 |
| CLI 接入 | 有 `BaseInstaller` ABC + `INSTALLER_REGISTRY`（好），但手工列表 + `cli.py`/`_env.py`/`types.py` 有 android 专属硬编码 | 注册表测试 expected 集**已漏 MacosIosBridge**（手工同步已出错）|
| 加平台成本 | **~14 新建 + 18–22 修改**，含 **9 个 README 状态表**手工同步；端口/版本散在 3+ 处手抄 | 无单一事实源 |
| 测试 | iOS/win/mac server **零单测**；无跨平台契约/端口冲突测试 | "新设备不破坏老能力"**无任何自动保障** |

## 三、目标架构：5 根支柱 + canonical 契约

### 支柱 1 — 平台清单 = 单一事实源（SSOT）

每平台一份 `platforms/<id>/platform.toml`：

```toml
[platform]
id            = "harmony-device"     # MCP server 名 = role_id
display_name  = "HarmonyOS"
port          = 8770
status        = "planned"            # released | beta | planned
multi_device  = true
host_os       = ["windows", "macos", "linux"]   # 哪些 host 能跑这个桥
[server]
module = "harmony_device_mcp"        # platforms/<id>/server/<module>.py
[install]
setup_script = "scripts/setup-harmony.sh"
guidance     = ["harmony_usb_debug.yaml"]
[install.options]                    # 取代 android 专属硬编码：通用 setup 选项声明
mode = { prompt = "ADB/连接模式", choices = ["usb","wireless","hybrid"], env = "ATB_HARMONY_MODE" }
```

SSOT 驱动：CLI 自动发现 · README 状态表/架构端口表**生成** · 端口唯一性校验 · 版本同步。**端口、版本、工具数、状态只写一处。**

### 支柱 2 — Canonical Universal Tool Set（代码契约）

三层：

- **CORE（每平台必须，同名同签名；多设备平台带可选 `device`/`ctx`）**
  `get_screen_size` · `take_screenshot(region?)` · `tap(x,y)` · `swipe(x1,y1,x2,y2,duration_ms?)` · `type_text(text)` · `press_key(key)` · `launch_app(target)` · `terminate_app(target)` · `current_app()` · `dump_ui(max_depth?)` · `find_elements(query)` · `tap_element(query)` · `list_devices()` · `set_default_device(device)` · `get_default_device()` · `acquire(holder_name?)` · `release()` · `get_status()`
  - `target` = 各平台 app 标识（win 路径 / mac 名 / android package / ios·harmony bundle id），**同名不同实参语义在工具 docstring 写明**。
  - 单设备平台（win/mac）`list_devices()` 返回 `[本机]`，`acquire/release/get_status` 走统一 holder。
- **CANONICAL-OPTIONAL（平台支持该能力时，用此规范名+签名）**
  `run_shell(script, timeout?)`（win→PowerShell / mac→zsh / android→adb shell / harmony→hdc shell；iOS 无 → 不实现）· `long_press` · `install_app(path)` · `uninstall_app(target)`
- **PLATFORM-EXTENSION（平台特有，自由命名，README 登记）**
  桌面：`click(button,clicks)` · `move_mouse` · `paste_text` · `list_windows`/`inspect_window`/`focus_window` · 进程 session（`start_process`/`read_process_output`/`interact_with_process`/`force_terminate`/`list_sessions`/`kill_process`）· 文件操作 · 搜索
  移动：`press_button`（iOS 物理键）· `adb_shell` 等

**收敛动作（P3，breaking）**：`click→tap`、`open_app`/`start_app→launch_app`、`kill_app`/`terminate_app→terminate_app`、`acquire_winpc`/`acquire_mac`/…→`acquire`、`inspect_window`/`list_ui_elements`/`dump_ui_hierarchy→dump_ui`、`run_powershell`/`run_zsh`/`adb_shell→run_shell`(+保留平台别名为 EXTENSION，可选)。

### 支柱 3 — 共享 bridge 核心（`platforms/common/`）

逻辑只存一份，所有 server import：

| 模块 | 内容 | 现状 |
|---|---|---|
| `_device_state.py` | `DeviceStateRegistry`（holder/acquire/release/idle） | 已有；**win/mac 改为复用**（单设备 = 单条目注册表） |
| `_aliases.py` | 别名引擎 | 已有 |
| `_bridge.py`（新） | FastMCP 引导（name/instructions/resource）· `_resolve_device` · `MultipleDevicesError` · 25s `_FASTMCP_DEADLINE_SAFE_SECONDS` clamp · 截图编码 | 现散在 4 server |
| `_proc.py`（新） | 长任务 session（start/read/interact/terminate/list；shell 参数化） | win/mac 各抄一份 |
| `_fsops.py`（新） | 文件操作（read/write/edit_block/list_dir/...） | win/mac 各抄一份 |
| `_search.py`（新） | 异步文件内容搜索 | win/mac 各抄一份 |
| `_manifest.py`（新） | 读 `platform.toml` | 无 |

### 支柱 4 — Conformance / 测试地基（合并门禁）

- `platforms/tests/test_conformance.py`：遍历每个 `platform.toml` → import 其 server → 内省 `@mcp.tool` 注册表，断言 **CORE 工具齐全 + 签名匹配 canonical 规范**；CANONICAL-OPTIONAL 若实现则签名须匹配。
- 端口唯一性测试（从 manifests 校验，取代运行时撞端口）。
- 版本一致性测试（manifest 版本 == repo 版本）。
- 补 **win/mac/ios server 单测**（holder/state、核心工具用 mock 驱动）。
- 与项目「review gate」联动：以上为合并门禁。

### 支柱 5 — CLI 自动发现 + 去硬编码 + 文档生成

- `installers/__init__.py`：`INSTALLER_REGISTRY` 改为**扫描 `platforms/*/platform.toml` 自动构建**；默认走通用 `ManifestInstaller(BaseInstaller)`（从 manifest 读 port/setup_script/guidance/host_os/options），特殊平台仍可子类覆写。
- 去 android 硬编码：`cli.py`/`_env.py`/`types.py` 的 android 专属分支 → 通用 `[install.options]`（manifest 声明 prompt/choices/env，wizard 通用收集并注入 env）。
- `scripts/gen-docs.py`：从 manifests **生成** 9 语 README 状态表 + `docs/architecture.md` 端口表（CI/pre-commit 校验"已生成且最新"）。

## 四、加平台的新体验（payoff）

加 HarmonyOS（或任意平台）= **几乎全是加法**：
1. 新建 `platforms/harmony/`：`platform.toml` + `server/harmony_device_mcp.py`（import 共享核心、实现 CORE 契约）+ `scripts/setup-harmony.sh` + `guidance/*.yaml` + `README.md` + `server/tests/`。
2. 跑 `gen-docs.py` 自动刷 README 状态表/端口表。
3. conformance + 端口 + 版本测试自动门禁。
- **不手改** `INSTALLER_REGISTRY`、不手抄 9 语 README、不碰其他平台 server。隔离即"加法 + 门禁"。

## 五、分阶段（每阶段独立交付 + 过 review gate）

| 阶段 | 内容 | 蓝图/风险 |
|---|---|---|
| **P0 地基** | 4 平台补 `platform.toml`（SSOT）+ canonical 契约声明（一份 spec 模块）+ conformance/端口/版本测试 + 补 win/mac/ios server 单测 | 纯加法，零回归风险；为后续当安全网 |
| **P1 共享核心** | 抽 `_bridge`/`_proc`/`_fsops`/`_search`；win/mac holder 迁到 `DeviceStateRegistry` | 触 4 server，靠 P0 测试兜底；逐平台迁移 |
| **P2 CLI 自动发现 + 去硬编码 + 文档生成** | manifest 驱动 registry + 通用 options + `gen-docs.py` | 改共享 CLI，靠现有 cli/tests + 新测兜底 |
| **P3 工具名对齐 canonical**（breaking） | 按收敛表改名；同步各平台 SKILL.md/examples（从 canonical 生成或核对） | 机械但面广；conformance 测试保证一致 |
| **P4 验证** | 用新基座接入 **HarmonyOS**（hdc + uitest），作为基座的第一个验证平台 | 真机验证（呼应 iOS 的可行性验证流程）|

## 六、隔离风险点与对策

- 旧的"危险共享变更点"（手工 `INSTALLER_REGISTRY`、9 语 README 手抄、端口/版本散落）→ **被 SSOT + 自动发现 + 生成消除**。
- P1 触 4 server 是本设计**唯一**高回归区 → 用 P0 测试兜底 + 逐平台迁移 + 每步过 review gate。
- 共享核心成为新的"关键共享点" → 由 `common/tests/` + conformance 强约束；改它必跑全平台测试。

## 七、非目标 / YAGNI

- 不做独立 PyPI 包（共享核心留 `platforms/common/`）。
- 不做插件热加载/动态注册（manifest 静态扫描足够）。
- 不在本基座内做跨设备协同（那是 v0.10.0 独立工作）。
- 不重写已工作的驱动逻辑，只搬运 + 统一接口。

## 八、成功标准

- 加一个平台：**0 处手改共享列表 / README**，跑 `gen-docs.py` + 实现契约即可。
- 任一平台缺 CORE 工具 / 签名不符 / 端口撞 / 版本不一致 → **CI 红**。
- holder/session/file/search 逻辑**各只存一份**。
- HarmonyOS 在新基座上接入并真机验证通过。
