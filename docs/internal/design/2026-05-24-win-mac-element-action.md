# win/mac element-action 升级（element-first，截图兜底）

状态：已实现并合并主分支（architect 审查见 §8；win/mac `find_elements`/`tap_element` 已上线、双平台真机验证通过）
日期：2026-05-24

## 1. 背景与目标

**现状**（代码核实）：
- win/mac 的 UI 操作以 `pyautogui` **像素坐标**为主（`tap(x,y)`）；`dump_ui`（win=pywinauto UIA / mac=AX）只用于**读**。
- mac 已有 `find_ui_element(app,title?,role?,label?)` + `click_ui_element(...)` —— 后者是 `find → pyautogui.click(元素中心)`，**已是 "element-located 中心点击" 模型**，但用结构化多参数、且必须指定 `app`。
- win **完全没有** element-action，只有只读 `inspect_window` + 坐标 `tap`。
- android（`tap_element`=uiautomator 找→`input tap` 中心）、ios（WDA `find_elements`/`tap_element`）已有 element-action。

**目标**：给 win/mac 补齐 canonical 的 `find_elements(query)` / `tap_element(query)`，实现"**按语义查元素 → 点其当前中心**"（element-located，坐标执行）。Agent 默认 **element-first**，无匹配/歧义时再 `take_screenshot + tap(x,y)` 兜底。顺带补齐四平台 element-action 契约一致性。robustness 来源 = **按属性实时定位**（抗布局/滚动/分辨率漂移），而非截图猜坐标。

**非目标**（明确排除）：
- 浏览器 web 内容（不在 UIA/AX 树里，另开浏览器内部通路轨——用户另有想法）。
- element-typing / set-value（本批不做；输入仍 `tap_element` 聚焦 + `type_text`）。
- ios `find_elements(using,value)` → 单 `query` 收敛（已知契约分歧，单列后续）。

## 2. 设计决策（已定）

1. **统一查询模型**：单个 freeform `query`，**大小写不敏感子串**匹配各平台标识属性：
   - win UIA：`Name` / `AutomationId` / `ControlType` / `ClassName` / `Value`
   - mac AX：`AXTitle` / `AXDescription` / `AXRole` / `AXValue`
   - 默认作用域 = **前台窗口/app**（与 `dump_ui` 一致），可选参数覆盖（win: `window_title?`；mac: `app?`）。
   - 与 canonical `find_elements:[query]` / `tap_element:[query]` + android 单 query 模型一致。
2. **动作范围**：仅 **click**（`find_elements` + `tap_element`）。不做 element-typing。
3. **兜底契约**：
   - `tap_element` 成功 → `{ok:true, element:{...}, clicked_at:[cx,cy]}`。
   - 失败 → 结构化 `{ok:false, reason:"not_found"|"ambiguous", candidates:[...]}`（ambiguous 时回候选列表）。
   - `find_elements` → 候选列表（含 `rect`/`center`/属性），供 agent 选或细化 query。
   - **执行 = 元素当前中心坐标点击**（element-located；沿用 mac 现做法，win 同）。
   - element-first 由 **SKILL.md 引导**，工具本身不自动兜底（保持确定性）。

## 3. 各平台实现

### 3.1 win（pywinauto UIA，net-new）
- `find_elements(query, window_title=None, control_type=None, max_results=20)`：
  - 目标窗口 = `window_title` 指定，否则前台 `win32gui.GetForegroundWindow()` → `Desktop(backend="uia").window(...)`。
  - 遍历后代（`.descendants(control_type=...)`，`control_type` 可选预过滤），子串匹配 `query` 于 name/automation_id/control_type/class_name/value。
  - 返回 `[{control_type,name,automation_id,rect,center,enabled,visible}]`，截断到 `max_results`。
  - **复用 console-window 守卫**（前台是 console 类直接返回友好错误，避免 UIA 遍历卡死）；遍历限 `max_results` + 超时保护。
- `tap_element(query, window_title=None, control_type=None, nth=0)`：
  - 调 `find_elements`；恰好 1 个（或 `nth` 指定）→ `pyautogui.click(center)`；多个且未指定 nth → `{ok:false,reason:"ambiguous",candidates}`。
  - 返回 `{ok:true, element, clicked_at}`。
- **风险**：UIA `descendants()` 在复杂窗口慢/可能卡（同 console 类）→ 限单窗口 scope + `control_type` 过滤 + `max_results` + 超时。

### 3.2 mac（AX，收敛现有）
- 新增 canonical `find_elements(query, app=None, max_depth=8)` / `tap_element(query, app=None, nth=0)`：
  - 复用 `_ax_walk` / `list_ui_elements` 机制；单 `query` 子串匹配 `AXTitle`/`AXDescription`/`AXRole`/`AXValue`。
  - `app` 默认 = 前台（`NSWorkspace.frontmostApplication()`，与 `dump_ui` 一致），可选覆盖。
  - `tap_element` = 元素中心 `pyautogui.click`（沿用 `click_ui_element`）。
- **旧工具处理**：`find_ui_element` / `click_ui_element` 被 canonical 取代 → **移除**并加入 legacy guard（与本项目 canonical 对齐一贯做法）。`list_ui_elements`（全树 flat dump）保留为 extension **还是**折进 `dump_ui` —— **请 architect 给意见**。

## 4. 行为引导（SKILL.md）
- `using-win` / `using-mac`：新增"**优先 `find_elements`/`tap_element(query)` 定位语义元素**；无匹配或 ambiguous → `take_screenshot` + `tap(x,y)` 兜底"。强调 robustness 来源（按属性实时定位，抗漂移）。

## 5. 契约 / 文档 / 测试
- **canonical**：`find_elements`/`tap_element` 已在 OPTIONAL（`query`），win/mac 实现后覆盖提升；确认参数名 = `query`，无需改契约。
- **文档**：9 语 README 工具数（win +2、mac 净变化 = +2 新 −2 旧 = 0，视 list_ui_elements 去留）、SKILL.md、`docs/architecture.md`；`gen_docs.py --check`。
- **legacy guard**：移除 mac `find_ui_element`/`click_ui_element` → 加入 `LEGACY_TOOL_NAMES`。
- **测试**：
  - 纯查询匹配 helper 单测（Linux 可跑，不依赖 GUI 库）。
  - 真机：test-win11（win UIA：记事本/资源管理器 find_elements + tap_element）、一台 mac（AX：计算器/Safari find + click）；确认 element-first → 截图兜底闭环、旧名失效。

## 6. 任务拆分（subagent-driven，每任务 review gate）
- **A**：win `find_elements`/`tap_element`（UIA）+ console 守卫复用 + 单测
- **B**：mac canonical `find_elements`/`tap_element` 收敛 + 移除旧名 + 单测
- **C**：SKILL/README/docs/architecture + legacy guard + `gen_docs --check`
- **D**：真机验证（win+mac）+ 整体 code-review + 合并 main（**合并前用户确认，外发**）

## 7. 风险与缓解
- **UIA/AX 遍历性能/卡死**（console 类）→ scope 单窗口/app + control_type 过滤 + max_results + 超时 + 复用 console 守卫。
- **mac AX 需 Accessibility(TCC) 权限**（`dump_ui` 已在用 → 应已授权）。
- **移除 mac 旧工具是 breaking**（alpha 可接受，legacy guard 兜底）。
- **仅对原生 app 有效，web 无效**（已知，另轨）。
- **执行仍是坐标点击**（元素需可见/在屏）—— robustness 来自实时定位而非硬编码坐标；未来可加 UIA InvokePattern / AXPress 的"无鼠标语义动作"作增强（本批不做）。

---

## 8. architect 审查结论与定稿增量（2026-05-24）

**结论：方案可行**。architect 对标 Playwright MCP / darbot-windows-MCP / AXorcist / pywinauto 实测，确认核心决策正确：① 单 `query`（对齐 canonical+android，LLM 友好）；② "每次现查现点" 优于 Playwright 式持久 `ref`（桌面窗口在调用间随时变，缓存 ref 会无音误点；`tap_element` 内部 find→act 是 atomic、符合 Playwright 精神，**不引入持久 ref**）；③ 坐标中心点击本批足够（沿用 mac 现做法），AXPress/InvokePattern 留作未来增强；④ console 守卫复用、工具不自动兜底、mac 移旧名——均正确。

**必须采纳（阻断级，优先级 1）：**
1. **遍历超时保护**（win）：`descendants()` 在复杂窗口实测 2.5-3s+、可能阻塞整个 MCP server。用 `concurrent.futures.ThreadPoolExecutor` 包 `descendants()` 调用、`future.result(timeout=8)`；超时返回 `{ok:false, reason:"uia_timeout", ...}`。`max_results` 截断**不能**替代超时（挡不住遍历本身阻塞）。
2. **DPI/坐标缩放风险**（win，加入风险清单）：`pyautogui` import 本身会破坏 Windows DPI awareness（已知 bug），UIA `BoundingRectangle` 是物理像素；>100% 缩放显示器上 UIA rect 与 `pyautogui.click` 坐标空间可能不一致 → 误点。**真机验证必做**：确认 test-win11 显示缩放（理想 100%）、诊断 UIA rect/center 与 pyautogui 坐标空间是否一致；响应可带 `actual_position` 辅助诊断。

**强烈建议（质量，优先级 2）：**
3. **匹配排序 + `match_field`**：单 query OR 匹配多属性会产生 ambiguous 风暴。精确匹配排在子串前；Name/AXTitle 最高、ControlType/AXRole 最低；每个结果带 `match_field`（命中哪个属性）。
4. **默认排除 disabled**：`find_elements` 加 `include_disabled: bool=False`（win 查 enabled / mac 查 `AXEnabled`），避免点 disabled 静默 no-op。
5. **`on_screen` 字段 + 离屏告警**：每元素算 `on_screen`；`tap_element` 点离屏元素回 `{ok:true, warning:"element_may_be_off_screen", ...}`。

**采纳（完成度，优先级 3）：**
6. **`list_ui_elements` 决定：保留为 extension、不并入 `dump_ui`**（dump_ui=前台 app、list_ui_elements=指定 app，用途不同）。Task B 范围明确。
7. **SKILL.md 决策树**：`not_found`→`dump_ui` 查真实属性→改 query 重试→仍不行截图兜底；`ambiguous`→看 candidates 用更具体 query 或 `nth`。
8. **多显示器**列已知限制（pyautogui 副屏坐标已知问题），SKILL/README 注明：副屏元素 tap 失败需截图+手动坐标。
9. **`action_type:"coordinate_click"` 字段**：`tap_element` 响应带上，为未来 `prefer_semantic`（InvokePattern/AXPress 优先、坐标兜底）预留结构。

来源：Playwright MCP snapshots 文档、pywinauto issue #842、pyautogui issue #663、AXorcist、Microsoft UIAutomation/InvokePattern 文档。
