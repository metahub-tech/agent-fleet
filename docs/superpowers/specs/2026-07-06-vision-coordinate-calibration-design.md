# 设计：vision 坐标系确定性校正（R1）——把「截图空间＝tap 空间」做成显式、单入口、可自检的硬不变量

> 状态：设计稿（待 architect 审 + 用户 spec 评审后转 writing-plans）· 2026-07-06
> 需求方：AgentHub（`docs/superpowers/specs/2026-07-06-device-op-precision-requirements-for-agent-fleet.md`，R1）
> 落地方：agent-fleet（device 工具 owner）
> 关联：`docs/internal/design/2026-06-04-vision-localization-capability.md`（现状 vision）、`docs/superpowers/specs/2026-07-02-deterministic-dom-install-design.md`（P1-A：win per-monitor DPI aware 的由来）
> 原则：从需求来、回需求中去——每个决策都能追回一条真实用户需求（§1、§7 决策表）。
> 范围：本 spec 只做 R1。R2/R3/R4/R5 各自独立成 spec（§8 排期）。

---

## 一、需求与现状（先把「为什么」说清，含一个反直觉的取证结论）

### 1.1 需求原话（R1）

> 截图常是物理像素、点击常是逻辑坐标，差一个 DPI/display scale 比例；坐标空间不一致时，即便 vision 定位对、点下去也偏。要求：读 OS 的 DPI/缩放，把 `vision_locate` 输出规整到与 tap 同一坐标空间，**零 agent、零校准点击、对调用方完全透明**。这是「系统性坐标误差」的主因，最高优先。

### 1.2 取证结论（禁区#11：先查代码，再下手）——需求的前提在快路径上**已被兜住**

对 pc-device 两端截图/点击原语做了尽调，结论**反直觉但关键**：**在单主屏上，「截图空间」与「tap 空间」当前已经自洽**，不是没做，而是两端各用相反策略把二者拉到同一空间：

| 端 | 截图 `take_screenshot` | 点击 `tap`/`_os_tap` | 是否自洽 |
|---|---|---|---|
| Windows | `ImageGrab.grab()` 出**物理像素**、不 resize（`win_device_mcp.py:164`） | `pyautogui.click`→`SetCursorPos` 吃**物理像素** | ✅ 进程 per-monitor-v2 DPI aware（`win_input.py:28-53`），截图/tap/`pyautogui.size()` 三者统一物理像素 |
| macOS | `ImageGrab.grab()` 物理后 **LANCZOS 压回逻辑点**（`mac_device_mcp.py:231-242`） | `pyautogui.click`→CGEvent 吃**逻辑点** | ✅ 截图 resize 到 `pyautogui.size()`（逻辑），与 tap 同空间 |

也就是说：150% 单主屏上，`vision_locate` 输出的 `center` **已经是 tap 空间**（win 全物理、mac 全逻辑）。需求设想的「截图物理 vs 点击逻辑差一个 scale 倍」在**单主屏快路径上不成立**。

> **这条「已自洽」是条件成立、不是无条件事实**：它**完全依赖 win 进程 awareness 设置成功**（mac 侧靠截图 resize 无此依赖）。目前的证据是 **test-win11 上 #100 已闭环**（若 awareness 当前正失效、坐标漂移，#100 轮3 的 1.5x 偏移就不会被判为已修）——即在**受支持机型（Win10 1703+）上、awareness 成功时**成立。落地第一步须在真机正向确认这一点（§5.2），并处理 awareness 失效时的残差（§1.6 残差声明）。

**由此得到一条硬约束（避免把 R1 做成有害的补丁）**：
> **awareness 成立（`dpi_aware:true`）时，绝不在 vision 输出处或 `tap_fn` 入口乘/除 scale。** center 已是 tap 空间，再乘除会**双重校正**、把对的坐标搞歪——这恰好会重造 R1 想治的系统性误差，方向相反。awareness 失效（`dpi_aware:false`）时坐标另有已知残差，见 §1.6。

### 1.3 那 R1 真正的空间在哪——三个「不变量会静默破裂」的边角

系统性坐标误差**确实存在**，但不在「缺一层除法」，而在这条自洽不变量的三个脆弱点：

1. **Windows DPI awareness 会静默失效（win 上系统性误差的真单点）**：
   - `_ensure_dpi_awareness()` 的返回值被**裸调丢弃**（`win_device_mcp.py:49`），三级降级若全失败（老系统/权限/被抢先），**无任何日志**。
   - `import pyautogui`（`win_device_mcp.py:35`）排在置 awareness（`:49`）**之前**——而设计文档自己记过「pyautogui import 会破坏 Windows DPI awareness（已知 bug）」（`docs/internal/design/2026-05-24-win-mac-element-action.md:88`）。若 pyautogui 抢先把进程置成 system-aware，`SetProcessDpiAwarenessContext(-4)` 可能失败并静默降级。
   - 一旦失效 → 截图变物理、tap 变虚拟化 → **重现 #100 轮3 实锤的 (1347,82) vs (1893,115) 1.5x 漂移**（`docs/superpowers/specs/2026-07-02-deterministic-dom-install-design.md:8`）。**这就是 R1 在 win 上要焊死的东西。**
   - **一个必须先解的张力**：§1.2「当前已自洽」与本条「import 时序可能已让 awareness 失效」，在同一台机器上不能同时是「活着的 bug」——要么 pyautogui import **并未**真的破坏 awareness（则「提前置位」是**硬化冗余**、保险而非救火），要么它破坏了（则 §1.2 对 win **当前就是假的**、坐标此刻在漂）。**落地第一步就在 test-win11 正向实测当前 `:49`（import 之后）的 awareness 到底 true 还是 false**（§5.2），据此判定「提前置位」是修活 bug 还是加保险，并解掉这个张力。无论哪种，提前置位 + 接返回值 + 可观测都是对的，只是定性不同。

2. **双份 capture 代码路径，极易漂移**：每端有**两处独立**截图逻辑——MCP 工具 `take_screenshot` 与注入 vision 的 `_capture_logical_png`。mac 两处**各写了一遍** grab→wake→resize（`mac_device_mcp.py:231-242` vs `:1103-1116`），逻辑非平凡却复制，改一处漏一处就会让「vision 看到的空间 ≠ take_screenshot 空间」。win 版 `_capture_logical_png` 更名不副实（叫 logical 却不 resize，`:959-964`）。**「截图空间＝tap 空间」这条真理必须只有一处实现。**

3. **多显示器/副屏根本不支持**：`ImageGrab.grab()` 无 `all_screens`，只截主屏并强压主屏比例；pyautogui 副屏坐标本有已知问题（`docs/internal/design/2026-05-24-win-mac-element-action.md:98`）。副屏各自 scale 不同时不是「换算要小心」，而是「不在支持范围」。

### 1.4 需求一句话（重述后）

> **把「vision 截图所在的坐标空间 ≡ tap 坐标空间」从两条隐式约定，做成显式、单一入口、启动即断言、可对外自检的硬不变量；并堵死 Windows DPI awareness 的静默失效。** 对调用方仍然完全透明——agent 照常 `vision_locate/vision_tap`，拿到即可点中，且现在有 `scale_factor` 可供上层核对。

### 1.5 成功判据（验收对着这些，§6）

- 缩放显示器（150% DPI）上，`vision_locate(query)` 的 center 喂 `tap` **个位数 px 命中**，全程零 agent、零校准。
- Windows awareness 若设置失败，**有明确日志 + `get_status`/`get_screen_size` 暴露 `dpi_aware:false`**，不再静默漂移。
- `take_screenshot` 与 vision 注入的 capture **走同一个 capture 原语**（单一真理），on-host smoke 证明二者不分叉（§5.2）。
- `get_screen_size` 暴露 `scale_factor` + `dpi_aware`（零新依赖），vision/上层/测试可据以核对不变量。

### 1.6 已知残差与裁决：awareness 失效时怎么办（BLOCKING 裁决，不留白）

`dpi_aware:false` 的机器上，截图与 tap 分属两空间、vision 坐标此刻**已知不可信**。要不要在 R1 里给它做「独立于 awareness 的坐标兜底」？**裁决：本 spec 不做自动纠正**，理由与边界如下——

- **本 spec 的保证**：受支持机型（Win10 1703+，主流）上 awareness **必然成功**（三级降级至少 `SetProcessDPIAware()` 兜底，`win_input.py:49-51`）；提前置位 + 接返回值把「成功」从隐式变确定。此时 R1「透明命中」达标。
- **失效即降级 followup（写死）**：若某机型 awareness 三级全败（老系统/受限权限），vision 坐标不保证准，**明确暴露 `dpi_aware:false` + 告警**让上层可感知并降级（改用 agent 自身视觉 / element-action），**而不是静默漂移**。这与 `memory/feedback-device-support-mainstream-first`（老设备环境问题直接降级、不阻塞主流）一致。
- **为什么不在 R1 塞兜底**：唯一「失效也能透明纠正」的路径是「用同屏 AX 真值反推残余 scale」——那正是 **R2** 的职责（可选兜底）。把它提前进 R1 会让本 spec 从「零回归的硬化」膨胀成「带拟合的校准」，违背 YAGNI 与范围锁。**R2 消费本 spec 暴露的 `dpi_aware`/`scale_factor` 做这件事**（§8）。
- **净变化**：R1 前，失效是「静默错」；R1 后，失效是「可见地错 + 可降级」。这已是 R1 范围内对失效机的正确处置；「失效也正确命中」交给 R2。

---

## 二、目标 / 非目标

### 目标
- G1（追 §1.3-1）：Windows DPI awareness **确定化**——在任何碰 DPI 的 import 之前置位、检查返回值、失败可观测。
- G2（追 §1.3-2）：每端收敛出**单一** `_capture_in_tap_space() -> PNG bytes` 原语，`take_screenshot` 与 vision 注入**都调它**；「截图空间＝tap 空间」只有一处实现。
- G3（追 §1.2/§1.4）：**对外暴露 `scale_factor`**（+ win `dpi_aware`），供自检/诚实上报/R2·R5 复用；**不改 tap 输入坐标**。
- G4（追 §1.5）：真机 150% DPI 验收 + on-host smoke（单入口/awareness）+ 平台无关纯函数单测（§5，注意 common/tests 不进 CI required）。

### 非目标（YAGNI）
- NG1：**不在 vision 输出/`tap_fn` 加物理↔逻辑乘除层**（§1.2 硬约束，会双重校正）。
- NG2：**不做多显示器/副屏**（§1.3-3，改动量远大于单屏校正，另起 spec）。
- NG3：**不动 OCR / 子行定位 / 模板匹配算法**（文字定位 1px 不是瓶颈，需求文档明令「别动」）。
- NG4：**不做 R2（AX 交叉校准）**——它消费本 spec 暴露的 `scale_factor` + AX 真值，是独立可选兜底（§8）。
- NG5：**不做 R5 的 score 暴露**——虽是小改，但属 R5 范畴；本 spec 只在 §8 标注衔接点，避免范围蔓延。

---

## 三、方案对比（3 选 1，取证驱动）

| 方案 | 做法 | 判定 |
|---|---|---|
| **A. 加除法层**（需求文档字面读法） | 读 scale，在 vision 输出 center 处 `/scale` 换到 tap 空间 | ❌ **否决**。§1.2 取证：center 已是 tap 空间，再除必**双重校正**、把对的搞歪。方向错。 |
| **B. 硬化不变量 + 单入口 + 暴露 scale**（本 spec 选） | 焊死 win awareness；收敛单一 capture 原语；暴露 scale_factor 供自检，但不参与 tap 坐标运算 | ✅ **选它**。最省改动、零回归风险、正对三个真实脆弱点；透明性不变。 |
| **C. 截图返物理 + vision 内部按 scale 回算** | mac 不再 resize，截图给物理 PNG，vision 内部 OCR 像素 `×1/scale` 回 tap 空间 | ❌ 否决。改动面大（take_screenshot 契约、模型看到的尺寸、双重校正窗口都变），只为保 Retina 画质——而画质不是 R1 需求。留作 vision OCR 精度的**独立** followup。 |

选 B 的理由一句话：R1 的病不是「少算一步」，是「自洽不变量脆弱且不可见」。治法是**焊死 + 收口 + 点亮**，不是新增运算。

---

## 四、设计（方案 B 的四个组件）

### 4.1 组件一：焊死 Windows DPI awareness（G1）

- **提前置位**：把 `_ensure_dpi_awareness()` 提到 `win_device_mcp.py` 里**任何碰 DPI 的 import 之前**（尤其 `import pyautogui`、`PIL.ImageGrab`、`pywinauto`）。实现上：在 server 模块顶部、第三方 GUI 库 import 之前先 `from win_input import _ensure_dpi_awareness; _DPI_AWARE = _ensure_dpi_awareness()`。`win_input` 本身只惰性引用 `ctypes.windll`（`win_input.py:8`），提前 import 安全。
- **接返回值 + 可观测**：`_DPI_AWARE = _ensure_dpi_awareness()`；`False` 时 `print(..., file=sys.stderr)` 明确告警（「DPI awareness 设置失败，缩放屏上视觉点击将漂移」）。
- **对外暴露**：`get_screen_size` / `get_status` 返回加 `dpi_aware: _DPI_AWARE`（win）。
- 不改 `_ensure_dpi_awareness()` 三级降级本身（已 robust）；只改**调用时机 + 用返回值**。

### 4.2 组件二：单一 `_capture_in_tap_space()` 原语（G2）

每端把截图逻辑收敛成**一个** private helper，`take_screenshot` 工具与注入 vision 的 capture_fn 都调它：

```
# 每端唯一真理：截出来的 PNG 恒等于 tap 坐标空间
def _capture_in_tap_space(region=None) -> PNG bytes
```

- **macOS**：把现有 grab→(黑屏/屏保则唤醒 re-grab)→resize-to-`pyautogui.size()` 逻辑**只留一份**在 `_capture_in_tap_space`；`take_screenshot`（`:210`）和 `_capture_logical_png`（`:1103`）都改为薄封装调它。消灭 §1.3-2 的双份漂移。
- **Windows**：`_capture_in_tap_space` = `ImageGrab.grab(bbox=region)`（物理像素，awareness 生效即 tap 空间，不 resize）；`take_screenshot`（`:157`）与 vision 注入都调它。删掉名不副实的 `_capture_logical_png`（或改名为该原语）。
- **region 语义钉死**：原语接受 `region=(left,top,right,bottom)`，**格式两端一致，但 region 恒在「该端 tap 空间」**——win 是物理像素、mac 是逻辑像素。mac 必须原样保留现逻辑「`grab(bbox=逻辑 region)` → resize 到 region 的逻辑尺寸」（`mac_device_mcp.py:238-239`），**grab 内部才落到物理，绝不能拿物理 region 去 crop**（否则 off-by-scale 裁错）。vision 仍可选「全屏抓 + 内存裁剪」以复用其偏移回加逻辑（`vision/_locate.py:15-23`）；关键是 capture 空间由单一原语保证。
- **可测子函数**：把 mac 的「按 target resize」抽成纯函数 `resize_to_tap_space(img, target) -> img`（PIL 纯运算），平台无关可断言（§5.1）。

### 4.3 组件三：暴露 `scale_factor`（G3，零新依赖，不参与坐标运算）

- **Windows**：`ctypes.windll.shcore.GetScaleFactorForMonitor` 或 `GetDpiForMonitor`（`scale=dpi/96`），主屏取值；与 `win_input.py` 现有 ctypes 风格一致，**零新依赖**。
- **macOS**：`NSScreen.mainScreen().backingScaleFactor()`——`pyobjc-framework-Cocoa` 已在 `macos/server/requirements.txt`，**零新依赖**。
- **落点**：`get_screen_size` 返回加 `scale_factor: float`（两端）+ `dpi_aware: bool`（win）。放在这里因为它和 width/height 同属「屏幕度量」。
- **语义必须写死（否则误导 R2）**：`scale_factor` = **OS 显示缩放**（如 150%→1.5），**不等于「截图↔tap 像素比」**——
  - **win**：awareness 生效时截图与 tap **全程物理同空间**，「截图尺寸 ÷ tap 尺寸」**恒 = 1.0**；`GetScaleFactorForMonitor` 返回的 1.5 是 OS 缩放、与该比值无关。`get_screen_size` 报的是物理尺寸，**不暴露逻辑尺寸**，故**不能**靠它自检出 1.5。docstring 必须写明：R2 消费 `scale_factor` 时**别当像素比用**。
  - **mac**：`ImageGrab` 抓 backing store（= backingScaleFactor × 逻辑），截图被 resize 回逻辑，故 backingScaleFactor 恰 = 「物理 grab 尺寸 ÷ 逻辑尺寸」，`NSScreen.mainScreen().backingScaleFactor()` 取主屏正确。
  - **多屏未定义**（NG2）：`scale_factor` 仅主屏；多屏各自 scale 不同的情形本 spec 不覆盖。
- **红线**：`scale_factor` **只用于自检 / 诚实上报 / 给 R2·R5 复用**，**绝不进 tap 坐标运算**（否则 §1.2 双重校正）。docstring 写明。

### 4.4 组件四：不变量断言（仅测试期，不进产品返回）

- **不加产品返回字段**（吸收架构审 N3：进产品返回是过度设计、多一个长期维护面）。不变量的守护落在：① 真机验收（§6，最终证据）；② on-host smoke 断言「`take_screenshot` 与 vision capture_fn 引用同一 `_capture_in_tap_space`」（§5.2 真机门禁）。
- `vision_locate` 返回结构**不变**，不附 `space_check`；capture_fn 语义不变（仍是「注入的 tap 空间 PNG」）。

---

## 五、测试策略

> **测试现实（架构审 BLOCKING-2，已核）**：本仓 CI（`.github/workflows/ci.yml`）required 只有 `shell-syntax / powershell-syntax / blueprint-check`；`python-tests` 仅跑 `cd cli && pytest`、`continue-on-error`、非 required。**`platforms/common/tests` 根本不进 CI**（`memory/reference-agentfleet-ci-coverage-gap`）。且 `win_device_mcp`/`mac_device_mcp` 顶层就 `import pyautogui`/`pywinauto`，**在无 DISPLAY 的 Linux 上 import 即失败**。故：涉及 server 模块的断言**只能真机跑**；能进「平台无关纯函数」桶的必须真的不 import server。别把「CI 绿」当成不存在的护栏——这些单测靠**本地/真机执行 + review gate** 保证。

### 5.1 平台无关纯函数单测（`platforms/common/tests`，本地/review gate 执行，非 CI required）
- `resize_to_tap_space(img, target)`：物理尺寸图 + 逻辑 target → 输出尺寸 == target；相等时恒等不 resize。**纯 PIL、不 import server，可任意机跑。**
- **scale 换算纯函数**：`win` 的 `dpi→scale`（dpi/96）、`mac` 的 backingScaleFactor 透传；读取失败降级 `1.0` 且不抛——把「读 OS」与「换算」分离，换算部分纯函数可测，「读 OS」部分 mock。
- `_ensure_dpi_awareness` 返回值→告警分支的**纯逻辑**（`win_input` 顶层只惰性引用 ctypes、可在非 win 导入，`win_input.py:8`）：mock 三级 API 全失败→返回 `False`；据此断言「`_DPI_AWARE=False` 时走 stderr 告警」的判断函数（把告警判断抽成纯函数，不依赖 server import）。
- vision 既有 OCR/子行/模板/并发单测保持全绿（NG3 未动算法）。

### 5.2 On-host smoke（`test_win_server.py` / `test_mac_server.py`，真机门禁，非 CI）
- **单入口不分叉**（本 spec 防复发核心闸，验收 #2）：在真机上断言 `take_screenshot` 与 vision 注入的 capture_fn **落到同一** `_capture_in_tap_space`（monkeypatch 该 helper 计数，两个调用点都命中）。**此断言依赖 server import，只能 host 跑**——明确是真机门禁项、不是 CI 项。
- **awareness 时序/返回正向锚点**（解 §1.3-1 张力）：在 test-win11 上实测**当前** `:49`（import 之后）awareness 是否为 `true` 且「截图尺寸==get_screen_size==物理」；改为提前置位后复测仍 `true`。
- **awareness 失效路径**：故意 mock/构造 awareness 失败 → 断言有 stderr 告警 + `get_screen_size.dpi_aware:false`（不静默）。

### 5.3 真机 150% DPI 验收（win/mac，对着 §1.5）
- **test-win11**（MCP key `win-device`）设 150% 缩放 → ① `get_screen_size` 报物理像素 + `dpi_aware:true` + `scale_factor:1.5`；② `vision_locate(已知网页文字)`→`tap` 个位数 px 命中（human_browser 真实 Chrome 上）。
- **macmini**（MCP key `mac-device`，Retina/缩放）→ ① 截图尺寸 == `get_screen_size`（逻辑）；② `scale_factor` == backingScaleFactor；③ vision→tap 命中。注意 macmini idle 睡眠抓壁纸（`memory/reference-macmini-display-idle-sleep.md`），验证前先唤醒。
- **共享 tap 面回归 sanity（架构审 N4，必做）**：awareness 是**进程级**，`_os_tap` 被 **vision、human_dom_tap、element-action `tap_element` 三家共用**同一光标空间。提前置位 + capture 收敛属顶层 import/初始化重排，故改后须复测**这三家在真机仍点得准**，不能只测 vision。反向也是正面收益：**awareness 硬化同时保护 element-action 与 human_dom_tap**（§7 决策表已记）。
- **不趁用户不在时擅自重配共享测试机**：真机 150% 验收在实现阶段、与用户确认时机后执行（charter：外发/不可逆/改共享设备前确认）。

### 5.4 质量门禁（charter）
架构审（本 spec，subagent architect）→ 实现后 code-reviewer 审 → 真机验收 → 过了才合并 + tag。

---

## 六、验收判据（逐条可核）

1. 受支持机型 150% 缩放屏、`dpi_aware:true`：`vision_locate→tap` 个位数 px 命中，零 agent、零校准。
2. `take_screenshot` 与 vision capture 走同一 `_capture_in_tap_space`（**on-host smoke** 证明不分叉，§5.2；非 CI）。
3. Windows awareness 失败可观测：告警 + `dpi_aware:false`，不再静默漂移；awareness 在 pyautogui import 前置位（on-host 守时序 + 正向锚点，§5.2）。
4. **残差处置（§1.6）**：`dpi_aware:false` 时坐标已知不可信、R1 **不自动纠正**，但暴露 `dpi_aware:false` + 告警使上层可降级——「可见地错 + 可降级」而非静默漂移；「失效也正确命中」交 R2。
5. `get_screen_size` 暴露 `scale_factor` + `dpi_aware`（零新依赖），语义按 §4.3 写死（= OS 显示缩放，≠ 截图↔tap 比值），且**不参与** tap 坐标运算（代码审 + 无双重校正回归）。
6. **共享 tap 面回归**：element-action `tap_element`、human_dom_tap 在改动后真机仍点得准（§5.3 N4）。
7. vision OCR/子行/模板/并发既有单测全绿（NG3）。

---

## 七、决策记录（每条追回需求）

| 决策 | 选择 | 追回的需求 / 依据 |
|---|---|---|
| 是否加除法层 | **否**（NG1） | §1.2 取证：center 已是 tap 空间，除 scale 会双重校正——方向与需求相反 |
| R1 的病灶 | 不变量脆弱且不可见，非缺运算 | §1.3 三脆弱点（win awareness 静默失效 / 双份 capture / 副屏） |
| win awareness | 提前置位 + 接返回值 + 可观测 | §1.3-1；#100 轮3 (1347,82)/(1893,115) 漂移实锤 |
| awareness 失效兜底 | R1 **不做**自动纠正，暴露 `dpi_aware:false` + 告警可降级；纠正交 R2 | §1.6 裁决；`feedback-device-support-mainstream-first`；守 YAGNI 与零回归 |
| capture 路径 | 收敛单一 `_capture_in_tap_space` | §1.3-2 mac 两份 grab→resize 复制、易漂移 |
| scale_factor | 暴露供自检，不进坐标运算；语义 = OS 显示缩放≠像素比 | §1.2 硬约束 + 为 R2/R5 留 hook；零新依赖（win ctypes / mac pyobjc 已有）；架构审 N1 防 R2 拿错 |
| 共享 tap 面 | awareness 硬化同时护 element-action/human_dom_tap；须回归三家 | 架构审 N4：`_os_tap` 进程级共用同一光标空间 |
| 多显示器 | 不做（NG2） | §1.3-3 改动量大、#100 不需要，另起 spec |
| OCR/子行/模板 | 不动（NG3） | 需求文档「文字定位 1px 不是瓶颈，别动」 |
| R2/R5 | 本 spec 不含，只留衔接点 | §8 排期；避免范围蔓延 |

---

## 八、R1–R5 排期与本 spec 边界

5 条需求各自独立成 spec→plan→impl，按需求文档优先级：

1. **R1（本 spec）**：坐标系确定性校正 = 焊不变量 + 单入口 + 暴露 scale。
2. **R4**：human_dom 扩覆盖——`content.js` `visibleText` 补抽字段（alt/name…）+ 放宽候选池纳入无 role 图标容器，配 `matchAll` 级 node-vm 测试；坐标/桥/iframe 不动（尽调已定路径）。
3. **R5**：反应式恢复 + 分档 hover-verify 的**工具原语**——含「对外暴露 vision_locate 的置信 score」（消费本 spec 的 scale_factor 无关，但同属 vision 工具原语扩展）。行为编排规范归 agenthub charter，不在本仓。
4. **R3**：元素检测 + Set-of-Marks（较重，引入 OmniParser 式检测）。
5. **R2**：AX/DOM 交叉校准（可选兜底，消费本 spec 的 scale_factor + AX 真值）。

**本 spec 只交付 R1。** R2–R5 待 R1 落地、用户确认后各自开 spec。

---

## 九、落地位置与文件清单（给 writing-plans）

**修改**
- `platforms/windows/server/win_device_mcp.py`：① awareness 提前置位（pyautogui import 之前）+ 接 `_DPI_AWARE` + 失败告警；② `_capture_in_tap_space(region)` 单原语，`take_screenshot`/vision 注入都调它，删/改 `_capture_logical_png`；③ `get_screen_size`/`get_status` 加 `dpi_aware` + `scale_factor`。
- `platforms/macos/server/mac_device_mcp.py`：① `_capture_in_tap_space(region)` 收敛 grab→wake→resize 单份，`take_screenshot`/`_capture_logical_png` 薄封装调它；② `get_screen_size` 加 `scale_factor`（NSScreen backingScaleFactor）。
- `platforms/windows/server/win_input.py`（或新 `win_dpi.py`）：加 `read_scale_factor()`（GetScaleFactorForMonitor/GetDpiForMonitor，失败降级 1.0）。
- `platforms/macos/server/`：加 `read_scale_factor()`（NSScreen，失败降级 1.0）。
- vision 侧 **不改**：capture_fn 语义不变（仍是「注入的 tap 空间 PNG」）、返回结构不变（§4.4 不加 `space_check`）。

**新建**
- `platforms/common/tests/test_capture_tap_space.py`（**纯函数**：`resize_to_tap_space`、scale 换算 dpi/96、awareness 告警判断纯逻辑；不 import server，任意机可跑；§5.1）。
- 真机 smoke 断言加进 `platforms/windows/tests/test_win_server.py` / `platforms/macos/tests/test_mac_server.py`（**单入口不分叉** + awareness 正向锚点/失效路径 + 共享 tap 面回归；只在 host 跑，§5.2/§5.3）。
- **注意**：`platforms/common/tests` 不进 CI required（§5 现实），新纯函数单测靠本地/review gate 执行。

**不动**：OCR/子行/模板算法、element-action、android/ios、human_dom。

---

## 附：给 writing-plans 的实现注意
- **红线**：任何时候都不得在 vision 输出或 `tap_fn` 对 center 乘/除 scale（§1.2）。scale_factor 仅自检/上报。
- win awareness **必须**在 `import pyautogui` 之前置位——这是本 spec 最容易被后续 import 重排破坏的点，写测试守住时序。
- mac capture 单入口收敛后，**黑屏唤醒逻辑也只剩一份**（原 `:232-235` 与 `:1106-1109` 合并），别漏。
- scale_factor 读取失败一律降级 `1.0` 且不抛，`availability` 无关（core 原语，不能崩 server）。
- 真机 150% 验收改共享测试机缩放，落地前与用户确认时机（charter 外发/改共享设备条款）。
