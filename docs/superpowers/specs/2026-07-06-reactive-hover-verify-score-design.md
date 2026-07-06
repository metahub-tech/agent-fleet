# 设计：反应式恢复的工具原语（R5）——暴露 locate 置信 score + hover-verify（移真鼠标 + 截图画十字@tap点）

> 状态：设计稿（待 architect 审 + 用户 spec 评审后转 writing-plans）· 2026-07-06
> 需求方：AgentHub（`docs/superpowers/specs/2026-07-06-device-op-precision-requirements-for-agent-fleet.md`，R5）
> 落地方：agent-fleet（device 工具 owner）
> 关联：`docs/internal/design/2026-06-04-vision-localization-capability.md`（vision 现状）、R1 spec（坐标系）、R4 spec（human_dom 扩覆盖）
> 原则：从需求来、回需求中去；改动加法为主、零回归。
> 范围：本 spec 只做 R5 的**工具原语侧**（score 暴露 + hover-verify 原语）。**「何时验 / 何时降级」的编排规范归 agenthub charter/skill**（用户明确划走，不在本仓）。

---

## 一、需求与现状（含第三个 premise 反转 + 用户澄清）

### 1.1 需求原话（R5，工具侧）

> 1. **默认反应式**：直接点 → 结果校验 → 不对就带线索结构化重定位，不盲重猜。
> 2. **分档提前 hover-verify**（两类确定性闸触发）：**低置信**（vision_locate 的 match 质量 score / 模板匹配置信度低于阈值）、**不可逆/高代价动作**（发布/删除/导航跳转）。hover-verify = **移真实鼠标到目标（不点）+ 截图**，光标即天然标记；验在目标上→点，不在→带差量线索重定位。
> 3. 工具需**对外暴露 locate 的置信 score**，供上层做确定性闸。
> 归属：**R5（工具原语 + score 暴露）= agent-fleet 落地**；**「何时验/何时降级」编排 = agenthub charter**。

### 1.2 现状取证（先读源码）

- **vision_locate 的 score 是「匹配质量」不是「检测置信度」**：`vision/_locate.py:54` 候选的 `score` = `_MATCH_SCORE[match_field]`（exact=1.0/prefix=0.8/contains=0.6）——它衡量「query 匹配得多好」，**不衡量「OCR 读得多确信」**。而 OCR 真正的检测置信度 `conf` 在 `vision/_ocr.py:31` 算出来了，却在 `_locate.py rank_candidates` 里**被丢弃**（没进候选）。
- **vision_locate_image 的 score 才是真置信度**：`_locate.py:88` 的 `score` / `:83` 的 `best_score` = OpenCV `TM_CCOEFF_NORMED` 峰值 ∈ [0,1]，是真模板匹配置信度。
- **human_dom_locate 无 score**：精确 DOM 命中（`human_dom/_locate.py`），无检测不确定性。
- **move_mouse 两端已有**：`win_device_mcp.py:519` / `mac_device_mcp.py:268`，`pyautogui.moveTo(x,y)`（移动不点击）。
- **take_screenshot 用 ImageGrab**（R1 已查），**全仓零 cursor 处理**（无 GetCursorInfo / `screencapture -C` / composite cursor）。

### 1.3 第三个 premise 反转：截图截不到硬件光标（用户已确认 + 澄清）

需求里 hover-verify「移真鼠标 + 截图，**光标即天然标记（无需自绘 overlay）**」有个前提：截图能看到光标。**取证：这前提不成立**——`take_screenshot`（`ImageGrab`）在 win（BitBlt 屏 DC）/ mac（screencapture 默认）上**都不含硬件光标**，且全仓零 cursor 合成代码。所以当前截图里根本看不到光标。

**用户澄清（2026-07-06）**：「无需自绘 overlay」原意是**不搞 OS 级屏上透明窗口**（那个跨平台复杂），**不是**排斥「在已截好的 PNG 上用 PIL 画标记」。而在 PNG 上画标记**更好**——画在**确定性的 tap 落点** (x,y) 上，直接可视化「这一点会不会落在目标上」，比光标热点像素还精确。故：

> **hover-verify = 移真实鼠标到目标 (x,y)（不点，仍触发 hover 态/tooltip 助辨识）+ 截图 + 在 PNG 的 (x,y) 处用 PIL 画小十字/圈。** 标记是**确定性的**（我们知道 tap 会落在 (x,y)），不依赖光标捕获。真机取证只需确认「标记画出来了 + 移鼠标触发了 hover 态」，非阻断（设计对光标截不截得到都成立）。

### 1.4 需求一句话（工具侧重述）

> **① 把 vision_locate 被丢的 OCR 检测置信度透出来（+保留 match 质量 score），让上层的「低置信闸」有真正的检测置信度可用；② 提供 hover-verify 原语：移真鼠标到 (x,y) + 截图 + 在 (x,y) 画十字，返回带标记的截图供上层校验。** 「何时触发闸 / 校验后如何决策」全归 agenthub charter。

### 1.5 成功判据（工具侧验收）

- `vision_locate` 每个候选带 `ocr_conf`（OCR 检测置信度）+ 既有 `score`（match 质量），语义分明；`vision_locate_image` 的置信度 score 语义写清；human_dom 精确=高置信（按 source 约定，不加 per-candidate score）。
- `hover_preview(x, y)` 移真鼠标到 (x,y) + 截图 + 在 (x,y) 画确定性十字标记，返回带标记 PNG；标记像素确实落在 (x,y)。
- 既有 vision/human_dom 行为零回归（score 暴露是加法；hover_preview 是新工具）。

---

## 二、目标 / 非目标

### 目标
- G1（追 §1.2/§1.4-①）：`vision_locate` 候选**加 `ocr_conf`**（透出被丢的 OCR 检测置信度），保留既有 `score`（match 质量），docstring 写清两者语义差异。
- G2（追 §1.4-②）：新 `hover_preview(x, y)` 工具——移真鼠标 (x,y) + 截图 + PIL 画十字@ (x,y)，返回带标记 PNG。
- G3：纯函数 `draw_crosshair(png, x, y)` 抽出到 common（平台无关可测）；hover_preview 放 **core**（两端 inline），直接用本地 `moveTo`/`ImageGrab` + `draw_crosshair`，不走 vision 注入、不被 OCR gate 连坐。

### 非目标（YAGNI）
- NG1：**不做「何时验 / 何时降级」编排**（发布/删除/导航等不可逆动作的判定、低置信阈值、校验后重定位决策）——**全归 agenthub charter**（用户明确划走）。
- NG2：**不做 OS 级屏上 overlay**（透明窗口画光标环，跨平台复杂）——用户明确不要；PNG 上 PIL 画标记即可。
- NG3：**不合成真实光标位图**（方案 2，win GetCursorInfo/mac NSCursor）——用户否决：平台特定 + 光标热点不如十字清晰。
- NG4：**不动 OCR/模板/子行算法**、不动坐标映射、不动 human_dom（R4 刚改完，不再碰其契约）。
- NG5：**human_dom 不加 per-candidate score**（精确 DOM=高置信，上层按「调的是哪个工具」的 source 约定判，避免再触 R4 契约）。
- NG6：**hover_preview 不重定位、不点击**——只 (x,y)→移+截+标；取候选/决策在上层。

---

## 三、方案对比（hover-verify 的「标记」怎么做）

| 方案 | 做法 | 判定 |
|---|---|---|
| **1. PNG 上 PIL 画十字@tap点**（本 spec 选） | 移真鼠标 + 截图 + 在已知 (x,y) 画小十字/圈 | ✅ **选它**（用户确认）。确定性（画在真 tap 落点）、平台无关、纯 PIL、不依赖光标捕获；比光标热点更精确直观。 |
| 2. 合成真实光标位图@(x,y) | 移真鼠标 + 截图 + composite 真光标图到 (x,y) | ❌ 否决（用户）。平台特定（win GetCursorInfo/GetIconInfo、mac NSCursor）；光标热点像素不如十字清晰；无必要。 |
| 3. OS 级屏上 overlay 画光标环 | 起透明置顶窗口在 (x,y) 画环再截 | ❌ 否决（用户）。跨平台复杂、有 OS 级副作用；「无需自绘 overlay」本意就是不要这个。 |

选 1 一句话：既然光标本就截不到，就在**确定性的 tap 落点**上画标记——比依赖光标更准、更简、更可移植。

---

## 四、设计

### 4.1 组件一：暴露 OCR 检测置信度（G1）

`vision/_locate.py rank_candidates`（`:40-60`）在构造候选时**补带** OCR 行的 `conf`：

```python
# 每个候选加 ocr_conf(OCR 检测置信度, 来自该 OCR 行), 保留 score(match 质量)。
out.append({
    "text": it["text"],
    "center": [cx + ox, cy + oy],
    "box": [x + ox, y + oy, w, h],
    "score": _MATCH_SCORE[mf],          # match 质量: exact=1.0/prefix=0.8/contains=0.6(既有, 不变)
    "ocr_conf": round(float(it.get("conf", 0.0)), 3),  # ★新增: OCR 检测置信度(该行读得多确信)
    "match_field": mf,
    "on_screen": True,
})
```

- **语义写清（docstring + skill）**：
  - `score` = **匹配质量**（query 匹配得多好），exact 恒 1.0——不反映 OCR 是否读清。
  - `ocr_conf` = **OCR 检测置信度**（该文本区域读得多确信），小/糊/低对比文字会低——这才是「低置信闸」对文字路径真正该看的信号。**粒度=行级、非子串级**：RapidOCR 只给每检测行一个 conf，子行切分（sub_line_center）出的候选继承的是**整行** conf；docstring/skill 须写明，charter 在子串查询时别据它对子串下过强结论。
  - `vision_locate_image` 的 `score`/`best_score` = 模板匹配置信度（既有，真置信度），docstring 标明「这是图标路径给闸用的置信度」。
- **加法、零回归**：只新增 `ocr_conf` 字段，既有 `score`/`center`/`box` 不变；上层不读 `ocr_conf` 则无感。
- **human_dom**：不加 per-candidate score（NG5）；上层按 source 约定「human_dom 命中=高置信」。

### 4.2 组件二：`hover_preview(x, y)` 原语（G2）—— 放 **core**，非 vision（架构审采纳）

新增 **core 工具**（两端 server inline，同 `move_mouse`/`take_screenshot` 范式），**不放 vision**：hover_preview 的三个依赖（截图、moveTo、PIL 画标记）**没一个需要 OCR/cv2**、locator 无关（human_dom/element-action/手工坐标都能用），若放 vision 会被 `_vision.py:9-15 _probe_deps()` 的 rapidocr/opencv gate **连坐**——装了 human_dom 却没装 vision 的设备就没 hover_preview，恰撞 R5 第二类触发（对 human_dom 定位的不可逆按钮做 hover-verify）。放 core 则通用可用、无 OCR 依赖。

```
hover_preview(x: int, y: int) -> Image | dict   # 成功返回带标记 Image; 失败返回 {ok:False,error}
```
流程（两端 core inline @mcp.tool）：
1. **移真鼠标**到 (x,y)（`pyautogui.moveTo(x,y)`，不点击，同 `move_mouse`）——触发 hover 态/tooltip，助辨识。
2. **截图**（同 `take_screenshot` 的 `ImageGrab` 路径 → tap 空间 PNG）。
3. **画标记**：调 common 纯函数 `draw_crosshair(png_bytes, x, y) -> png_bytes`，在 (x,y) 画醒目小十字 + 外圈（PIL ImageDraw，高对比色如洋红，尺寸约 20px、线宽 2-3px）。
4. 返回带标记 `Image`（PNG）；capture/move 抛错 → `{ok:False, error}`（结构化，便于 charter 编排判分支，对齐 vision_locate 的失败形）。

- **唯一共享代码 = `draw_crosshair`（common 纯函数）**；两端 core 的 hover_preview @mcp.tool 各调它 + 本地 `moveTo`/`ImageGrab`（少量 inline 重复，同 take_screenshot/move_mouse 现状，可接受）。**不需给 VisionCapability 加 move_fn 注入**（放 core 后不走注入）。
- **坐标空间**：x,y 是 tap 空间坐标（截图空间≡tap 空间）→ 画在截图 (x,y) 即真 tap 落点，无换算。R1 若已合入则截图更稳（单一 `_capture_in_tap_space`），未合入也一致（现 take_screenshot 即 tap 空间）。
- **只读无副作用（除移鼠标）**：不点击、不改 DOM；移鼠标是 hover-verify 的题中之义（`pyautogui.FAILSAFE=False` 已全局关，角点 hover 不触发 abort）。
- **Image 返回形**：需 `from fastmcp.utilities.types import Image`（两端 server 已 import，同 take_screenshot）。

### 4.3 不做的部分（划清边界）

- **编排**：低置信阈值取多少、哪些算不可逆动作、hover 后「在目标上就点/不在就带线索重定位」的决策链——**全归 agenthub charter**（NG1）。R5 只给「闸的输入（score）」+「验的原语（hover_preview）」。
- **反应式恢复的「线索」**：locate 已返回候选清单（上层可换 nth）、tap 已返回落点坐标、hover_preview 返回带标记截图——这些**已是**上层做「带线索重定位」的素材，R5 不另造新结构。

---

## 五、测试策略

> 测试现实：`platforms/common/tests` 不进 CI required；vision 单测依赖 `numpy`/`cv2`（本 Linux dev box **缺 numpy**，vision 相关测试本机不能跑，靠有 numpy 的环境/真机 + review gate）。纯 PIL 的 `draw_crosshair` 本机可跑（PIL 12.2 已装）。

### 5.1 平台无关纯函数单测（本机可跑部分）
- **`draw_crosshair(png, x, y)`**（PIL）：造一张纯色 PNG → 画标记 → 断言 (x,y) 邻域像素被改成标记色、远处未改；越界 (x,y) 不崩（clamp 或忽略）。**本机 PIL 可跑。**
- **`rank_candidates` 带 ocr_conf**：喂合成 ocr_items（含 `conf`）→ 断言候选含 `ocr_conf` 且=输入 conf、既有 `score` 不变。**注意 `_locate.py` 顶层 import numpy/cv2 → 本机(缺 numpy)不能 import**；此测试需有 numpy 的环境跑（同既有 vision 测试的处境）。

### 5.2 On-host / 真机验收
- `hover_preview(x,y)` 真机：移鼠标到 (x,y)（截图前后光标确实动了/hover 态触发）、返回 PNG 在 (x,y) 有醒目十字；`vision_locate` 返回带 `ocr_conf`（低对比小字的 ocr_conf 明显低于清晰大字——验证它是有用的低置信信号）。
- 真机取证（非阻断）：确认 `take_screenshot` 到底含不含光标（强先验=不含；即便某平台含，十字标记冗余但无害）。

### 5.3 质量门禁（charter）
架构审（本 spec）→ 实现后 code-reviewer 审 → 真机验收 → 过了才合并 + tag。

---

## 六、验收判据（逐条可核）

1. `vision_locate` 候选含 `ocr_conf`（=该 OCR 行检测置信度）+ 既有 `score`（match 质量），docstring/skill 讲清两者差异；`vision_locate_image` 置信度语义标明。
2. `hover_preview(x,y)` 是 **core 工具**（两端 inline，非 vision）：移真鼠标 (x,y) + 截图 + 在 (x,y) 画确定性十字，返回带标记 PNG（失败返 `{ok:False,error}`）；`draw_crosshair` common 纯函数本机测过（标记落在 (x,y)、越界不崩）。**装了 human_dom 没装 vision 的设备也有 hover_preview**（不被 OCR gate 连坐）。
3. hover_preview 不依赖 vision/OCR，不需给 VisionCapability 加注入；坐标空间=tap 空间（画在 (x,y) 即真落点）。
4. **零回归**：既有 vision_locate/vision_tap/vision_locate_image、human_dom、core 既有工具全不变（ocr_conf 是加字段；hover_preview 是新 core 工具；human_dom 不动）。
5. 边界：R5 不含编排（低置信阈值/不可逆判定/校验后决策=charter）；不做 OS overlay / 不合成真光标。

---

## 七、决策记录（每条追回需求）

| 决策 | 选择 | 追回的需求 / 依据 |
|---|---|---|
| hover 标记 | PNG 上 PIL 画十字@tap点(方案1) | §1.3 用户确认；光标截不到 + 画在确定性 tap 落点更准；非 OS overlay |
| 不合成真光标 / 不 OS overlay | 否(NG2/NG3) | 用户否决：平台特定 / 跨平台复杂 / 十字更清晰 |
| score 暴露 | vision_locate 加 ocr_conf + 保留 match score | §1.2 取证：既有 score 是 match 质量非检测置信度, 闸对文字路径需要 OCR conf |
| human_dom score | 不加 per-candidate(按 source 约定高置信) | NG5；R4 刚改完不再触其契约 |
| hover_preview 归属 | **core 工具**(两端 inline), 非 vision | 架构审：locator 无关+零 OCR 依赖；放 vision 会被 `_probe_deps` OCR gate 连坐、撞 R5 第二类触发(human_dom 定位的不可逆按钮) |
| hover_preview 失败 | 返回 `{ok:False,error}`(非裸 Image) | 架构审：便于 charter 编排判分支, 对齐 vision_locate 失败形 |
| 编排 | 不做, 归 charter | §1.1 归属；NG1 |
| 反应式「线索」 | 复用既有(候选/落点/带标记截图), 不另造 | §4.3；YAGNI |

---

## 八、落地位置与文件清单（给 writing-plans）

**修改**
- `platforms/common/capabilities/vision/_locate.py`：`rank_candidates` 候选加 `ocr_conf`（透 `it["conf"]`），既有字段不动。
- `platforms/common/capabilities/vision/_vision.py`：vision_locate/vision_locate_image docstring 标清 `score`(match 质量)/`ocr_conf`(OCR 检测置信度, 行级) 语义差异。（**不加 move_fn 注入**——hover_preview 放 core，不走 vision 注入。）
- `platforms/windows/server/win_device_mcp.py` / `platforms/macos/server/mac_device_mcp.py`：各加 **core inline** `@mcp.tool hover_preview(x, y)`——`pyautogui.moveTo(x,y)`(不点) → `ImageGrab` 截图 → `draw_crosshair(png, x, y)` → 返回 `Image`(失败返 `{ok:False,error}`)；需 `from fastmcp.utilities.types import Image`(两端已 import)。与 `move_mouse`/`take_screenshot` 同处、同范式。

**新建**
- `platforms/common/_marker.py`（common 顶层, 非 vision 子目录——core 两端都 import）：纯函数 `draw_crosshair(png_bytes, x, y, ...) -> png_bytes`（PIL ImageDraw）。
- `platforms/common/tests/test_marker.py`：`draw_crosshair` 纯 PIL 测（本机可跑：标记落 (x,y)、越界不崩、标记色）。
- `rank_candidates` 的 ocr_conf 断言加进既有 `test_vision_locate.py`（需 numpy 环境, 本机缺 numpy 不能跑）。

**不动**：OCR/模板/子行算法、坐标映射、human_dom（含契约）、VisionCapability 注入签名（不加 move_fn）、core 既有工具行为（只**加** hover_preview 一个新工具）。

---

## 附：给 writing-plans 的实现注意
- **零回归**：ocr_conf 是加字段，既有 score/center/box 不动；hover_preview 是新 core 工具；human_dom/vision 注入签名一行不碰。
- **hover_preview 放 core**：两端 server inline `@mcp.tool`，直接 `pyautogui.moveTo` + `ImageGrab` + `draw_crosshair`（common `_marker.py`），**不走 vision 注入、不被 OCR gate 连坐**。draw_crosshair 是唯一共享代码（common 纯函数）。
- **坐标空间**：hover_preview 的 (x,y) 是 tap 空间；core 的 `ImageGrab` 截图与 tap 同空间（win DPI-aware / mac take_screenshot 已 resize 到逻辑），画在 (x,y) 即真落点。R1 合入与否不影响（core 截图路径本就 tap 空间）。
- **draw_crosshair 越界**：x,y 超出图像范围时 clamp 到边界或安全忽略，不抛。
- **draw_crosshair 显眼**：高对比色（洋红/红）+ 十字 + 外圈，避免落在同色背景看不见；线宽 2-3px、尺寸 ~20px。
- **ocr_conf 语义**：docstring 写明「行级 OCR 检测置信度、非子串级」；`it.get("conf", 0.0)` 防御默认（合成测试项无 conf 也不崩）。
- **hover_preview 失败**：capture/move 抛错返回 `{ok:False, error}`（结构化，非裸 Image），便于 charter 判分支。
