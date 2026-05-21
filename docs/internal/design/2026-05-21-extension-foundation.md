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
host_os       = ["windows", "macos"] # 哪些 host 能跑这个桥（HarmonyOS hdc 在 Linux 上稳定性待 P4 确认，先保守）
[server]
module = "harmony_device_mcp"        # platforms/<id>/server/<module>.py
[install]
setup_script = "scripts/setup-harmony.sh"
guidance     = ["harmony_usb_debug.yaml"]
# 通用 setup 选项（取代 android 专属硬编码）：
#  - options：线性 prompt→env 映射
#  - config_reuse：声明式描述"检查已有配置文件→问是否复用"的条件分支（替代 android 的 _select_android_config）
[install.options]
mode = { prompt = "连接模式", choices = ["usb","wireless","hybrid"], env = "ATB_HARMONY_MODE" }
[install.config_reuse]
check_path = "~/.atb-harmony/config.toml"
env        = "ATB_HARMONY_REUSE_CONFIG"
```

**版本策略**：单仓库**单一版本号**（manifest 不写死版本，运行时从 `cli/pyproject.toml` 的 repo 版本读取；版本一致性测试校验各平台未漂移）。
SSOT 驱动：CLI 自动发现 · README 状态表/架构端口表**生成** · 端口唯一性校验 · 版本一致性。**端口、状态、host_os、setup 选项只写一处。**

### 支柱 2 — Canonical Universal Tool Set（代码契约）

三层：

- **CORE（每平台必须，同名同签名；多设备平台带可选 `device`/`ctx`）**
  `get_screen_size()` · `take_screenshot(region?)` · `tap(x,y)` · `swipe(x1,y1,x2,y2,duration_ms?)` · `type_text(text)` · `press_key(key)` · `dump_ui(max_depth?)` · `current_app()` · `terminate_app(target)` · `list_devices()` · `set_default_device(device)` · `get_default_device()` · `acquire(holder_name?)` · `release()` · `get_status()`
  - **单设备平台（win/mac）**：`list_devices()` 返回**单元素**列表 `[{"device":"host","model":<hostname>,...}]`（不返回神秘的"本机"）；`acquire(holder_name?)`/`release()`/`get_status()` **不带 device 参数**，底层用 `DeviceStateRegistry` 注入固定 serial `"host"`。即 agent 面对单设备平台无需传 device。
  - iOS 的 `take_screenshot` 当前缺 `region` 参数，P0 补上 `region=None`（签名先对齐，裁剪实现可后置）。
- **CANONICAL-OPTIONAL（平台支持该能力时，用此规范名+签名；签名分歧大的工具放这里而非强塞 CORE）**
  - `launch_app(target)` —— `target` 各平台语义不同（win 路径 / mac 名 / android package / ios·harmony bundle），属 **leaky abstraction**，故不进 CORE；docstring 写明"target 为平台相关 app 标识"。
  - `find_elements(query: str)` / `tap_element(query: str)` —— canonical 签名为"自由文本/可达性 id 模糊匹配"；iOS 的 `(using,value)` 富 locator 作为该平台 EXTENSION 保留。
  - `run_shell(script, timeout?)`（win→PowerShell / mac→zsh / android→adb shell / harmony→hdc shell；iOS 无 → 不实现）· `long_press` · `install_app(path)` · `uninstall_app(target)`
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

落地两个前置约束：
- **`platforms/common/` 加 `__init__.py` 变本地包**（仍 sys.path 注入，不发 PyPI），改为 `from common.xxx import ...`，避免模块从 2 个增到 7 个后 `_bridge.py`/`_proc.py` 等无 namespace 名字在 CI/测试里冲突；conftest 统一插一次 path。
- **抽取前先做 win vs mac 差异 audit**（`tools/audit_win_mac_diff.py` 或文档）：逐函数列差异，区分"bug"（win 缺 `expanduser`）与"平台合理差异"（默认 shell zsh vs powershell、`shlex` posix 与否、shell 映射表）。**先修 bug，再用参数化（`ShellSpec`/`PathOptions` 注入）抽取**，否则共享代码隐含静默平台 bug，违背"逻辑只存一份"。

### 支柱 4 — Conformance / 测试地基（合并门禁）

- canonical 契约声明为一份代码事实源 `platforms/common/_canonical_tools.py`（`{"tap": ["x","y","device?","ctx?"], ...}`）。
- `platforms/tests/test_conformance.py`：**用 `ast` 静态解析**每个 `platform.toml` 指向的 server `.py`，提取 `@mcp.tool` 修饰函数名 + 参数列表，与 `_canonical_tools.py` 比对，断言 **CORE 齐全 + 签名匹配**；OPTIONAL 若实现则签名须匹配。
  - **关键：不 import server**——win/mac 依赖 pyautogui/pywinauto/pyobjc、android 顶层调 `_resolve_adb()`，在 Linux CI 上根本 import 不了，且挖 FastMCP 私有 `_tool_manager` 脆弱。AST 静态分析无依赖、可在 Linux CI 全平台跑、不碰私有结构（现 `test_tool_signatures.py` 的 import+inspect 仅 android 可行，故弃用该路径）。
- 端口唯一性测试（从 manifests 校验，取代运行时撞端口）。
- 版本一致性测试（manifest 版本 == repo 版本）。
- 补 **win/mac/ios server 单测**（holder/state、核心工具用 mock 驱动）。
- 与项目「review gate」联动：以上为合并门禁。

### 支柱 5 — CLI 自动发现 + 去硬编码 + 文档生成

- `installers/__init__.py`：`INSTALLER_REGISTRY` 改为**扫描 `platforms/*/platform.toml` 自动构建**；默认走通用 `ManifestInstaller(BaseInstaller)`（从 manifest 读 port/setup_script/guidance/host_os/options），特殊平台仍可子类覆写。
- 去 android 硬编码：`cli.py`/`_env.py`/`types.py` 的 android 专属分支 → 通用机制：
  - `InstallContext` 的 `android_mode`/`android_reuse_config` 字段 → 替换为通用 `platform_options: dict[str,str]`，由 manifest `[install.options]` 驱动 wizard 通用收集。
  - android 的"检查 `~/.atb-android/config.toml` → 问是否复用"条件分支（现 `_select_android_config()`）→ 由 manifest `[install.config_reuse]` 声明，`ManifestInstaller` 实现通用"路径存在则问复用→注入 env"逻辑。
  - 即 `_select_android_config` / `_env.py` 的 android 分支 / `types.py` 的 android 字段**全部删除**，行为由 android 自己的 `platform.toml` 声明驱动。
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
| **P0 地基** | 4 平台补 `platform.toml`（SSOT）+ `_canonical_tools.py` 契约 + **AST** conformance/端口/版本测试 + 补 win/mac/ios server 单测 + iOS `take_screenshot` 加 `region` 形参 | 基本加法；conformance 走 AST（无 import，跨平台 CI 安全）；win/mac/ios server 单测在各自平台跑，AST 测试管跨平台契约 |
| **P1 共享核心** | **先 win/mac diff audit + 修 bug**，再抽 `_bridge`/`_proc`/`_fsops`/`_search`（参数化合理差异）；win/mac holder 迁到 `DeviceStateRegistry`（单设备 = 单条目，serial `"host"`） | 触 4 server，本设计**唯一**高回归区，靠 P0 测试兜底 + 逐平台迁移 |
| **P2 CLI 自动发现 + 去硬编码 + 文档生成** | manifest 驱动 registry + 通用 `platform_options` + `config_reuse` + `gen-docs.py` | 改共享 CLI，靠现有 cli/tests + 新测兜底；删 android 专属字段/分支 |
| **P3 工具名对齐 canonical**（breaking） | 先出**影响域清单**（SKILL.md / examples / guidance / README 都编码了工具名，且 SKILL 被 agent 框架缓存，非"重连"可清）→ 加 `test_no_legacy_naming`（旧名出现即 CI 红）→ 按收敛表改名，**拆 PR：先 CORE 工具、再 OPTIONAL** | 机械但面广；conformance + no-legacy 测试保证一致 |
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

## 九、架构评审采纳（2026-05-21，APPROVE-WITH-CHANGES）

architect subagent 评审，方向获认可，已采纳以下修订（均已并入上文）：

**3 个关键改动（实现前必须）**
1. **conformance = AST 静态分析**（非 import+inspect）：win/mac 依赖 pyautogui/pywinauto/pyobjc、android 顶层 `_resolve_adb()` → Linux CI 无法 import；改用 `ast` 解析 + `_canonical_tools.py`（§支柱2/4、§五P0）。
2. **manifest 补 `config_reuse` + 通用 `platform_options`**：android 的"复用已有配置"是条件分支，线性 `options` 表达不了；同时删 `InstallContext` 的 android 专属字段（§支柱1/5、§五P2）。
3. **P1 先做 win/mac diff audit + 修 bug 再参数化抽取**：两版 `read_file` 等 `expanduser`/shell/`shlex` 有真实差异，盲抽会埋静默 bug（§支柱3、§五P1）。

**重要细化**
- `launch_app`/`find_elements`/`tap_element` 从 CORE 降为 CANONICAL-OPTIONAL（签名/语义跨平台分歧大，强塞 CORE 是 leaky abstraction）。
- 单设备平台 `list_devices()` 返回 `[{device:"host",...}]`、`acquire/release/get_status` 不带 device 参数（不给 agent 增认知成本）。
- `platforms/common/` 加 `__init__.py` 变本地包，避免模块增多后命名冲突。
- P3 改名前出"影响域清单" + `test_no_legacy_naming`，SKILL.md/examples/guidance 同步，拆 CORE/OPTIONAL 两批 PR。

**次要**
- iOS `take_screenshot` 补 `region` 形参（P0 对齐签名）。
- 单仓库单一版本号策略；HarmonyOS `host_os` 先保守 `["windows","macos"]`（hdc on Linux 待 P4 验证）。
- `_FASTMCP_DEADLINE_SAFE_SECONDS` 合并进 `_bridge.py` 时加 `# TODO: remove once fastmcp#823 fixed`。
