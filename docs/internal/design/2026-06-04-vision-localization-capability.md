# vision 能力模块设计:无障碍树失效时的像素级元素定位

> 状态：设计稿（待 architect 审 + 用户确认后转 writing-plans）· 2026-06-04
> 目标读者：核心维护者 + 未来贡献者
> 关联：能力模块框架 `docs/internal/design/2026-05-24-capability-module-framework.md`、element-action `docs/internal/design/2026-05-24-win-mac-element-action.md`、北极星愿景 `memory/project-agent-fleet-capability-platform-vision.md`
> 原则：本设计从需求来、回需求中去——每个决策都能追回一条真实用户需求（见 §1）。

---

## 一、需求与场景（先从用户视角说清「为什么」）

### 1.1 真实处境

agent 通过 pc-device（win-device / mac-device）操控电脑，经常需要**点击界面上的一个元素**——网页里的「登录」按钮、Electron 应用（VS Code / Slack / 飞书桌面端）里的一个菜单项、canvas 渲染的图表上的一个控件、Flutter/游戏界面里的一个按钮。

现状里 agent 有两条定位路径：

1. **element-action（`find_elements`/`tap_element`）**：走 OS 无障碍树（mac AX / win UIA），按语义找控件、返回中心坐标。**抗布局漂移、精确、免费**。但它的文档原话就划了边界：

   > *"a browser's web page content is not exposed via AX — for web, fall back to take_screenshot + tap. Some apps (Electron a11y-off, Java Swing, Flutter) expose no usable AX tree."*

2. **退回「截图 + 猜坐标」**：当无障碍树为空时，agent 只能截图、靠自己的视觉估个像素坐标去 `tap`。

### 1.2 痛点（现状路径 2 的代价，实测）

2026-06-04 在真实掘金页（中文密集 SPA）上做了 OCR vs「agent 自己视觉猜坐标」(VLM) 的对照，10 个跨对比度目标：

| 路径 | 定位精度（中位 / 最坏） | 成本/次 | 离线 |
|---|---|---|---|
| agent 视觉猜坐标（VLM） | **120px / 249px** | ~1280 token | 否 |
| 本地 OCR 定位 | **1px / 21px**（10/10 检出） | **0 token** | 是 |

120px 的误差，在 30px 高的导航条上 = **直接点错元素**。而且每次都烧 ~1280 视觉 token + 1–3s 在线往返。

### 1.3 需求一句话

> **当无障碍树拿不到元素时，agent 需要一条「便宜、精确、离线」的像素级定位路径，把它要点的那个元素的坐标稳稳找出来。**

### 1.4 成功判据（从用户视角，验收对着这些）

- agent 在**网页 / Electron / canvas / Flutter** 上，能用一个工具按「文字」或「图标图」定位到元素并点中，**不再靠自己猜坐标**。
- 高对比可交互元素（按钮/链接/标题/菜单）定位**误差 ≤ 个位数 px**，**0 LLM token**，**离线可用**。
- 一次定位**亚秒级**（常见场景，配 ROI 裁剪）。
- 找不到时给 agent **可据以调整的反馈**（读到了什么），而不是黑箱失败。

### 1.5 为什么是现在

element-action 已落地（win/mac，2026-05-24），把「有无障碍树」的场景做到了极致；human_browser 也已落地（真实 Chrome、截图+坐标操作真实账号）。两者都把**「无障碍树为空的 web/嵌入式 UI」**这块明确地留给了「截图+猜坐标」——这是当前 pc-device 操控能力里**最后一块靠 agent 硬猜、又贵又不准**的短板。spike 已证明 OCR/模板匹配能把它补上（§1.2）。

---

## 二、目标 / 非目标

### 目标
- G1（对应 §1.4）：提供**像素级元素定位**，覆盖无障碍树为空的场景（web/canvas/Electron/Flutter/游戏）。
- G2：定位结果与 core `tap` **同一坐标空间**，定位完即可点中。
- G3：**0 LLM token、离线、纯 CPU**；常见场景亚秒。
- G4：接口**镜像 element-action 心智**（query→候选→中心坐标 / 找点即点），agent 的既有思维直接迁移。
- G5：作为**能力模块**接入既有框架（self-built、platform.toml 可选启用、配 skill），**core 零改动**。

### 非目标（YAGNI，§1 需求里没有的就不做）
- NG1：**不做全屏 OCR 文字转录 / 页面理解**——「读懂页面」这条需求已由 **agent 自己的视觉**满足（实测 VLM 读字 ~100%、本地 OCR 在低对比上反而弱）。vision 只管「定位」。
- NG2：**不与 element-action 竞争 / 不自动融进它**——有无障碍树就该用 element-action（更准更省）；vision 是 a11y 失效时的独立 fallback，由 agent 显式选用。
- NG3：**不做移动端**（android/ios 多数有 a11y 树，需求不成立）。
- NG4：**不做多尺度模板匹配**（v1 单尺度 + DPI 提示）。
- NG5：**不做 `vision_read`（区域读字）**——同 NG1，理解归 agent 视觉。

---

## 三、模块身份与定位

| 项 | 值 |
|---|---|
| id | `vision` |
| origin | self-built（自建，护城河=操控物理设备本身的像素层，非嫁接） |
| platforms | `["windows", "macos"]`（pc-device） |
| 启用 | platform.toml `[capabilities].enabled` 可选；推荐 win/mac 启用 |
| skill | `using-vision` |
| 落地 | `platforms/common/capabilities/vision/` |
| 框架契约 | 继承 `CapabilityModule`，实现 `availability()` + `register()`，被 `CapabilityRegistry.setup()` 静态注册（同 human_browser 范式） |

**发现信息字段（`list_capabilities()` 用，草稿，不可留空）**：
- `display_name` = "视觉定位 vision(无障碍树失效时按文字/图标定位元素)"
- `description` = "自建:当 OS 无障碍树为空时(网页/canvas/Electron/Flutter/游戏),用本地 OCR + 模板匹配按文字或图标图做像素级元素定位,返回与 tap 同坐标空间的中心点。0 LLM token、离线、纯 CPU。"
- `usage_hint` = "find_elements/tap_element 在 web/无 AX 树场景拿不到元素时用:vision_locate(query) 按可见文字定位→返回候选+中心坐标;vision_tap(query) 找到即点;vision_locate_image(模板图) 定位无字图标。只管定位,读懂页面用 take_screenshot 交给自己的视觉。"
- `skill` = "using-vision"

**与 element-action 的关系（决策记录，追回 §1.1）**：二者**互补不竞争**。
- 有无障碍树（原生 app 控件）→ 用 `find_elements`/`tap_element`（AX/UIA，更准更省，抗漂移）。
- 无树（web/canvas/Electron-a11y-off/Flutter/游戏）→ 用 `vision_*`（像素）。
- 接口**刻意同构**（query→候选+中心坐标），让 agent 在两套之间无缝切换；但**保持独立工具**（用户已拍板）——core 不依赖可选 vision 模块（框架解耦），且 agent 清楚知道结果来自像素视觉（可靠性画像不同于无障碍树）。

---

## 四、工具接口契约（3 个工具）

所有坐标都是 **core `take_screenshot` 的点空间**（与 core `tap(x,y)` 一致），定位完直接 `tap` 命中。

### 4.1 `vision_locate` — 按文字定位（对标 `find_elements`）

```
vision_locate(
    query: str,                  # 要找的可见文字(子串,大小写不敏感)
    region: Optional[tuple[int,int,int,int]] = None,  # (left,top,right,bottom) 逻辑像素;None=全屏
    max_results: int = 20,       # 候选上限(超出按排序截断取前 N)
) -> dict
```

> **region 格式刻意对齐 core `take_screenshot`**（`(left, top, right, bottom)` 逻辑像素），不用 `[x,y,w,h]`——同名参数同语义,避免 agent 在两个工具间混淆,也让内部裁剪与 take_screenshot 无缝衔接(§10 决策表)。

返回：
```json
{
  "ok": true,
  "query": "登录",
  "count": 2,
  "candidates": [
    {"text": "登录", "center": [1200, 29], "box": [1180,20,40,18],
     "score": 1.0, "match_field": "exact", "on_screen": true}
  ],
  "ocr_ms": 360
}
```

- **`score` 语义（文字工具）**：匹配质量分 ∈ (0,1]，由 match_field 决定（exact=1.0 > 前缀 > 包含），**非** OCR 置信度（OCR 置信度不外露，低于内部阈值的检测直接丢弃）。注意与 `vision_locate_image` 的 `score`（模板匹配置信度）含义不同。
- **匹配与排序**（对标 element-action）：子串匹配；排序优先级 **on_screen > exact > 前缀 > 包含**；同分按与屏幕阅读序。候选超过 `max_results` → 按排序截断取前 N。
- **子行定位（关键机制，§5.3）**：OCR 会把整行合并；候选的 `center` 是**按 query 在识别文本里的字符偏移比例切出的子框中心**，不是整行中心——把密集页 ~30px 误差收到个位数 px。
- 找不到 → `{"ok": true, "count": 0, "candidates": [], "ocr_sample": "<当时读到的部分文本>", "hint": "..."}`（§7）。

### 4.2 `vision_tap` — 找点即点（对标 `tap_element`）

```
vision_tap(
    query: str,
    region: Optional[tuple[int,int,int,int]] = None,  # 同 vision_locate (left,top,right,bottom)
    nth: Optional[int] = None,   # 0-based,0=排序第一个;省略=自动(唯一/exact 即点,多个歧义→返回候选)
) -> dict
```

> **`nth` 刻意对齐 `tap_element`**：**0-based**（0=最优候选）、**Optional**（省略时自动消歧——唯一或 exact 命中即点，多个歧义则不点、返回候选让 agent 加 query 或显式 nth）。与 element-action 完全同构,避免 0/1-based 不一致导致 agent 系统性点错。

- 内部：`vision_locate(query, region)` → 按 nth 规则取候选 → 调注入的 **core OS 点击回调**（§5.1 B4，避免循环依赖）。
- 返回 `{"ok": true, "tapped": {"text": "...", "center": [x,y]}, "total_candidates": N}`。
- 0 命中 → `{"ok": false, "error": "not found", "ocr_sample": "...", "hint": "..."}`；歧义未给 nth → `{"ok": false, "error": "ambiguous", "candidates": [...]}`；`nth` 越界 → 清晰报错 + 候选数。

### 4.3 `vision_locate_image` — 按图标图定位（无字元素）

```
vision_locate_image(
    template_b64: Optional[str] = None,   # 模板图 base64(与 template_path 二选一)
    template_path: Optional[str] = None,  # 主机本地模板图路径
    region: Optional[tuple[int,int,int,int]] = None,  # (left,top,right,bottom),同 vision_locate
    threshold: float = 0.85,              # 置信度阈值
) -> dict
```

- 内部：OpenCV `matchTemplate(TM_CCOEFF_NORMED)`，`minMaxLoc` 取峰值。`score` = 模板匹配置信度 ∈ [0,1]（与文字工具的 match-质量 `score` 含义不同）。
- 两者都不传 → `{"ok": false, "error": "template_b64 or template_path required"}`（不把 None 喂进 OpenCV）。
- 返回 `{"ok": true, "found": true, "center": [x,y], "score": 0.97}`；低于 threshold → `{"ok": true, "found": false, "best_score": 0.61, "hint": "模板需按当前显示缩放截取;跨 DPI 会掉(单尺度限制)"}`。
- **单尺度**（NG4）：模板必须在当前显示缩放下截取；DPI 不一致会掉置信度（实测 1.25x → 0.62）。docstring + hint 写明。

---

## 五、内部架构

```
vision_locate/tap/locate_image
        │
        ├─(1) 抓图: 复用 core take_screenshot() → 点空间 PNG bytes  ──┐ 坐标天然对齐 core tap
        ├─(2) ROI: region 给定时在内存按 (left,top,right,bottom) 裁剪 │
        ├─(3a 文字) RapidOCR(引擎单例) → [(box,text,score)]         │
        │         → 匹配排序 + 子行定位(§5.3) → 候选+中心坐标       │
        └─(3b 图标) OpenCV matchTemplate → 峰值中心                  │
        (4) vision_tap: 取候选 → core tap(x,y) ───────────────────┘
```

### 5.1 抓图/点击 = 注入 core 原语（决策：坐标对齐 + 破循环依赖，B4）
vision 模块住在 `platforms/common/capabilities/`，**不能 import server 文件**（server 启动时 import capabilities → 反向 import 会循环）。core 的 `take_screenshot`/`tap` 又是 server 里的 `@mcp.tool`。**依赖倒置**：
- server 把两个**纯 OS 原语**（不带 `@mcp.tool` 装饰）注入 VisionCapability 构造器：
  `registry.add(VisionCapability(capture_fn=_os_capture_png, tap_fn=_os_tap))`，其中 `capture_fn() -> PNG bytes`（点空间，与 take_screenshot 同实现）、`tap_fn(x, y)`（OS 级点击，与 tap 同实现）。
- writing-plans 需先把各 server 的截屏/点击核心逻辑抽成可复用 private helper（`@mcp.tool` 的 take_screenshot/tap 改为调它们），再注入 vision。capability 侧零 server 依赖。
- 坐标：capture_fn 给的就是 core `tap` 点空间 → 定位坐标直接喂 tap_fn，零转换。`region` 给定时**全屏抓后在内存按 (left,top,right,bottom) 裁剪**，内部坐标加回 `(left, top)` 偏移再返回（不把 region 透给 capture_fn，统一一处裁剪逻辑，避免两种格式）。

### 5.2 OCR 引擎（决策：进程内 + 单例缓存 + 串行锁，用户已拍板）
- RapidOCR（PP-OCRv4 ONNX 模型），纯 CPU，模型随包内置（离线、确定性）。
- 引擎实例**模块级单例**，首次用时 lazy 构造并缓存（冷启 74ms–843ms，之后每次推理只付推理时间）。
- **线程安全（B3）**：FastMCP 同步工具在 worker 线程池并发跑，多个 `vision_*` 可能同时进 OCR。v1 用一把 `threading.Lock` **串行化 OCR 推理调用**（并发量极低，串行不损吞吐，且消除 RapidOCR 内部状态的线程安全不确定性）。模板匹配（OpenCV，无共享状态）不需锁。
- **进程内**运行（非 sidecar）：模型小、缓存后开销可忽略，YAGNI 不引 sidecar 复杂度。

### 5.3 子行定位（关键机制，直接对应「定位要准」需求）
OCR 把一整行合并成一个框（实测密集页整行框中心偏离单个目标 ~30px）。修法：
1. 在 OCR 行的识别文本里找 query 的字符起止偏移 `[i, j)`。
2. 按 `i/len`、`j/len` 比例在行框宽度上线性切出子框。
3. 候选 `center` = 子框中心。
→ 把 30px 收到个位数 px（CJK 等宽近似、英文比例近似；够点击用）。**v1 必做**，否则密集页不可用。

### 5.4 模板匹配（§4.3）
OpenCV `matchTemplate`，单尺度。region 裁剪后匹配更快更准。

### 5.5 依赖与 availability
- 依赖：`rapidocr-onnxruntime` + `opencv-python-headless` + `numpy`（venv 增量 ~250M，纯 CPU，离线）。装在各平台 server 的 venv（同 fastmcp/pillow 路径）。
- `availability()`：探 `import rapidocr_onnxruntime, cv2` 成功 → 可用；失败 → `(False, "vision 依赖未安装(rapidocr-onnxruntime/opencv)")`，模块标 unavailable，**绝不崩 server**（框架 try/except 已兜）。

---

## 六、数据流（端到端实例：在网页点「登录」）

1. agent 在 human_browser 开了真实 Chrome，要点「登录」。先试 `find_elements("登录")` → AX 树无 web 内容、空 → agent 转 vision。
2. `vision_tap("登录")`：
   - core take_screenshot → 1280×800 点空间 PNG。
   - RapidOCR(单例) → 识别出含「登录」的行框。
   - 子行定位 → 候选 `{text:"登录", center:[1200,29], score:1.0}`。
   - core `tap(1200, 29)` → 点中。
   - 返回 `{ok:true, tapped:{text:"登录", center:[1200,29]}}`。
3. 全程 0 LLM token、离线、~0.3–2s。

---

## 七、错误处理与诚实边界（对应 §1.4「可据以调整的反馈」）

| 情况 | 行为 |
|---|---|
| query 没找到 | `{ok:true,count:0, ocr_sample:"<当时读到的文本片段>", hint:"换个可见文字 / 缩小 region / 该处可能低对比,改用 agent 自身视觉读"}` —— 带回**读到了什么**,让 agent 能调整,而非黑箱 |
| 多命中 | 返回排序候选；`vision_tap` 需 `nth` 消歧（同 element-action） |
| 低对比/装饰文字读不出 | **已知局限**（实测整页含大量浅灰字时 OCR 召回掉）。定位**高对比可点元素**是强项；「读懂低对比内容」请用 agent 自己的视觉（skill 写明，对应 NG1） |
| 模板跨 DPI 掉置信 | `found:false` + best_score + hint（单尺度限制，NG4） |
| 依赖缺失 | 模块 unavailable（§5.5），不崩 server |

**诚实定位（写进 skill 红线）**：vision 是**可交互元素定位器**，不是全屏 OCR 转录器；理解交给 agent 视觉。

---

## 八、测试策略

### 8.1 Linux 可跑单测（`platforms/common/capabilities/vision/tests/`）
- 用合成渲染图（已知文字+坐标，同 spike 手法：HTML→Chrome headless 或预存 PNG fixture + ground-truth JSON）。
- 断言：① `vision_locate` 召回（目标文字命中率）；② **子行定位精度**（命中目标中心误差 ≤ 阈值 px）；③ 排序/消歧（exact 优先、nth 0-based、ambiguous 行为）；④ ROI 裁剪坐标换算正确（region 偏移加回）；⑤ `vision_locate_image` 同尺度命中、跨尺度按阈值判 not-found、双 None 报错；⑥ not-found 带 ocr_sample；⑦ availability 探测；⑧ **并发压测**（N=4 线程并发 `vision_locate` 不崩、结果稳定——验证 §5.2 串行锁）。
- 这些不需要真设备（纯图像处理 + 注入的 capture_fn 用 fixture PNG），**Linux CI 可跑**。

### 8.2 真机冒烟（win/mac，对着 §1.4 成功判据）
- 在 human_browser 真实 Chrome 上：`vision_locate("登录")` 误差核对 + `vision_tap` 端到端点中已知网页元素。
- 在一个 Electron app（如 VS Code）上：对 a11y 拿不到的 web 视图元素做同样验证。

### 8.3 质量门禁
按章程：架构审（本 spec）→ 实现后 code-reviewer 审 → 真机验收，过了才合并。

---

## 九、落地位置与文件清单

**新建**
- `platforms/common/capabilities/vision/__init__.py`
- `platforms/common/capabilities/vision/_vision.py` —— `VisionCapability(CapabilityModule)` + 3 工具 register；纯逻辑（OCR 引擎单例、匹配排序、子行定位、模板匹配）抽成可单测函数。
- `platforms/common/capabilities/vision/tests/test_vision.py`
- `platforms/<win|mac>/skills/using-vision/SKILL.md`

**修改**
- **`platforms/common/capabilities/__init__.py`（B1，易漏！）**：`from .vision import VisionCapability` + 加入 `__all__`（无自动发现，不 export 则 `from capabilities import VisionCapability` ImportError、server 起不来）。
- `platforms/windows/server/win_device_mcp.py` / `platforms/macos/server/mac_device_mcp.py`：① 把截屏/点击核心逻辑抽成 private helper（`@mcp.tool` 的 take_screenshot/tap 改调它们）；② `registry.add(VisionCapability(capture_fn=..., tap_fn=...))`（注入，§5.1；与 human_browser 同处接入；core 工具行为不动）。
- **`find_elements`/`tap_element` 的 docstring**：把 "for web, fall back to take_screenshot + tap" 更新为 "for web/无 AX 树, fall back to vision_locate/vision_tap"（否则 agent 不知道有更优 fallback）。
- `platforms/windows/platform.toml` / `platforms/macos/platform.toml`：`[capabilities].enabled` 可加 `"vision"`（或留给运维/默认）。
- `platforms/<win|mac>/server/requirements.txt`（+ pyproject）：加 `rapidocr-onnxruntime` / `opencv-python-headless`；setup 脚本 pip 走镜像。
- README / `docs/architecture.md` 平台扩展表：登记 vision 工具。

**不动**：core 工具行为、element-action 逻辑、android/ios。

---

## 十、决策记录（每条追回需求）

| 决策 | 选择 | 追回的需求 / 依据 |
|---|---|---|
| 集成模型 | 独立 `vision_*` 工具（非融进 find_elements） | §1.1 互补不竞争；框架解耦（core 不依赖可选模块）；agent 需知道可靠性画像 |
| 工具范围 | 文字定位 + 找点即点 + 图标模板（不含 read） | §1.3 需求是「定位」；理解需求已由 agent 视觉满足(NG1/NG5) |
| OCR vs VLM | OCR 管定位 | §1.2 实测 OCR 1px/0token vs VLM 120px/1280token |
| 引擎部署 | 进程内 + 单例缓存 | G3 亚秒；YAGNI 不引 sidecar |
| 模板尺度 | 单尺度 v1 | NG4；多尺度无紧迫需求，留 followup |
| 平台 | win/mac（pc-device） | §1.1 场景在桌面 web/Electron；移动端有 a11y 树(NG3) |
| 子行定位 | v1 必做 | §1.4「误差≤个位 px」——否则密集页 30px 不达标 |
| region 格式 | `(left,top,right,bottom)` 对齐 take_screenshot | 同名参数同语义，避免 agent 混淆 + 内部裁剪一处逻辑（架构审 B2） |
| nth 语义 | 0-based + 省略即自动，对齐 tap_element | 与 element-action 同构，避免 0/1-based 系统性点错（架构审建议） |
| 破循环依赖 | server 注入 capture_fn/tap_fn | capability 不 import server（框架解耦，架构审 B4） |
| OCR 并发 | threading.Lock 串行 | 消除 RapidOCR 线程安全不确定性，并发量低不损吞吐（架构审 B3） |

---

## 附：实现注意（给 writing-plans）
- **坐标全程点空间**；region=`(left,top,right,bottom)`，全屏抓后内存裁剪、内部坐标加回 `(left,top)` 偏移再返回（§5.1）。
- **OCR 引擎单例 + `threading.Lock` 串行推理**（B3，§5.2）；构造一次、复用；模板匹配不锁。
- **破循环依赖**（B4，§5.1）：先把 server 截屏/点击核心逻辑抽成 private helper，再注入 `VisionCapability(capture_fn, tap_fn)`；capability 不 import server。
- **`__init__.py` 加 export**（B1，§9）——容易漏，列为独立任务。
- **更新 element-action docstring** 推荐 vision fallback（§9）。
- 子行定位对超长 query / 跨行 query 做降级（取整行中心 + 标注 `approx:true`）。
- 依赖体积大（~250M），setup 脚本 pip 安装走镜像；availability 缺失时模块 unavailable 而非报错。
- 测试加并发压测用例（§8.1 ⑧）验证串行锁。
