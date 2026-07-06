# R5 反应式恢复工具原语 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 R5 反应式恢复提供两个工具原语——① `vision_locate` 暴露被丢的 OCR 检测置信度 `ocr_conf`（低置信闸的输入）；② 新 core 工具 `hover_preview(x,y)`（移真鼠标到 (x,y) 不点 + 截图 + 在 (x,y) 画确定性十字），供上层验点。「何时验/何时降级」编排归 agenthub charter，不在本仓。

**Architecture:** 加法为主、零回归。`ocr_conf` 是 `rank_candidates` 候选新增字段（既有 `score`=match 质量不动）。`hover_preview` 放 **core**（两端 server inline，非 vision——它 locator 无关、零 OCR 依赖，放 vision 会被 `_probe_deps` OCR gate 连坐），复用既有 `_capture_logical_png`（tap 空间截图）+ common 纯函数 `draw_crosshair`。

**Tech Stack:** Python；PIL/Pillow（draw_crosshair、截图）；pyautogui（moveTo）；pytest。`draw_crosshair` 纯 PIL 本机可跑；`ocr_conf` 测试依赖 numpy（本机缺，需 numpy 环境）；`hover_preview` host-only（server import pyautogui）。

**Spec:** `docs/superpowers/specs/2026-07-06-reactive-hover-verify-score-design.md`（architect 已审，无 BLOCKING，核心决策=hover_preview 放 core 已采纳）。

**测试现实：** `platforms/common/tests` 不进 CI required；`_locate.py` 顶层 import numpy/cv2 → 本机(缺 numpy)不能 import，`ocr_conf` 测试需 numpy 环境；`draw_crosshair` 纯 PIL 本机可跑（PIL 12.2 已装）；`hover_preview` 在 win/mac server（import pyautogui）→ 只 host 跑，本机 `py_compile` 验语法。

---

## 文件结构

**新建**
- `platforms/common/_marker.py`（common 顶层，core 两端都能 import）：纯函数 `draw_crosshair(png_bytes, x, y, ...) -> png_bytes`（PIL ImageDraw）。
- `platforms/common/tests/test_marker.py`：`draw_crosshair` 纯 PIL 单测（本机可跑）。

**修改**
- `platforms/common/capabilities/vision/_locate.py`：`rank_candidates` 候选加 `ocr_conf`（透 `it["conf"]`）。
- `platforms/common/capabilities/vision/_vision.py`：vision_locate/vision_locate_image docstring 标清 `score`(match 质量)/`ocr_conf`(OCR 检测置信度, 行级) 语义。
- `platforms/windows/server/win_device_mcp.py` / `platforms/macos/server/mac_device_mcp.py`：加 core inline `@mcp.tool hover_preview(x,y)` + `from _marker import draw_crosshair`。
- `platforms/common/tests/test_vision_locate.py`：加 ocr_conf 断言（需 numpy 环境）。

**不动**：OCR/模板/子行算法、坐标映射、human_dom（含契约）、VisionCapability 注入签名（不加 move_fn）、core 既有工具行为（只加 hover_preview）。

---

## Task 0: 建实现分支

- [ ] **Step 1: 从最新 main 建分支**（R5 独立于未合并的 R1/R4）

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git checkout main && git pull
git checkout -b feat/reactive-hover-verify-score-r5
```

---

## Phase A — 实现

### Task 1: `draw_crosshair` 纯函数（本机 PIL TDD）

**Files:**
- Create: `platforms/common/_marker.py`
- Test: `platforms/common/tests/test_marker.py`

- [ ] **Step 1: 写失败测试**

```python
# platforms/common/tests/test_marker.py
"""draw_crosshair 纯 PIL 单测(平台无关, 本机可跑; 非 CI)。"""
import io
from _marker import draw_crosshair
from PIL import Image


def _blank(w, h, color=(0, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_crosshair_marks_at_point():
    png = draw_crosshair(_blank(100, 100), 50, 50, size=10, color=(255, 0, 255), width=3)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.getpixel((50, 50)) == (255, 0, 255)   # 中心
    assert img.getpixel((45, 50)) == (255, 0, 255)   # 横线上(±size 内)
    assert img.getpixel((10, 10)) == (0, 0, 0)       # 远处仍是背景


def test_crosshair_out_of_bounds_no_crash():
    png = draw_crosshair(_blank(50, 50), 999, -5, size=8)   # 越界 → clamp, 不抛
    assert Image.open(io.BytesIO(png)).size == (50, 50)


def test_crosshair_preserves_size():
    png = draw_crosshair(_blank(120, 80), 60, 40)
    assert Image.open(io.BytesIO(png)).size == (120, 80)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python3 -m pytest tests/test_marker.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named '_marker'`

- [ ] **Step 3: 写实现**

```python
# platforms/common/_marker.py
"""在已截好的 PNG 上画确定性标记(纯 PIL, 平台无关)。R5 hover-verify 用: 把 tap 落点 (x,y)
画成醒目十字+外圈, 直接可视化"这一点会不会落在目标上"。不依赖光标捕获(截图本就不含硬件光标)。"""
from __future__ import annotations
import io


def draw_crosshair(png_bytes: bytes, x: int, y: int, size: int = 20,
                   color=(255, 0, 255), width: int = 3) -> bytes:
    """在 png 的 (x,y) 画十字 + 外圈(默认洋红), 返回新 png bytes。
    x,y 越界 → clamp 到图内, 绝不抛。纯函数、只用 PIL。"""
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    cx = max(0, min(w - 1, int(x)))
    cy = max(0, min(h - 1, int(y)))
    d = ImageDraw.Draw(img)
    r = int(size)
    d.line([(cx - r, cy), (cx + r, cy)], fill=color, width=width)          # 横
    d.line([(cx, cy - r), (cx, cy + r)], fill=color, width=width)          # 竖
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)  # 外圈
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python3 -m pytest tests/test_marker.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/_marker.py platforms/common/tests/test_marker.py
git commit -m "feat(r5): draw_crosshair 纯函数(PNG 上画确定性十字@tap点, 越界 clamp)"
```

---

### Task 2: `vision_locate` 暴露 `ocr_conf`（需 numpy 环境）

**Files:**
- Modify: `platforms/common/capabilities/vision/_locate.py`（`rank_candidates`）
- Modify: `platforms/common/capabilities/vision/_vision.py`（docstring）
- Test: `platforms/common/tests/test_vision_locate.py`（加断言）

- [ ] **Step 1: 写失败测试**（加到 `test_vision_locate.py`；`rank_candidates` 接受 ocr_items 列表，无需真 OCR）

```python
def test_rank_candidates_exposes_ocr_conf():
    from capabilities.vision._locate import rank_candidates
    items = [{"text": "登录", "box": [10, 20, 40, 18], "conf": 0.87}]
    cands = rank_candidates(items, "登录")
    assert cands[0]["ocr_conf"] == 0.87          # 透出 OCR 检测置信度
    assert cands[0]["score"] == 1.0              # 既有 match 质量(exact)不变
    assert cands[0]["match_field"] == "exact"


def test_rank_candidates_ocr_conf_defaults_when_missing():
    from capabilities.vision._locate import rank_candidates
    items = [{"text": "登录", "box": [10, 20, 40, 18]}]   # 无 conf
    cands = rank_candidates(items, "登录")
    assert cands[0]["ocr_conf"] == 0.0           # 防御默认, 不 KeyError
```

- [ ] **Step 2: 跑测试确认失败**（numpy 环境）

Run: `cd platforms/common && python3 -m pytest tests/test_vision_locate.py::test_rank_candidates_exposes_ocr_conf -q`
Expected: FAIL — `KeyError: 'ocr_conf'`（或 numpy 缺失环境下 collection error——则换有 numpy 的环境/真机跑）

- [ ] **Step 3: 写实现**（`_locate.py` 的 `rank_candidates` 里候选 dict 加一个 key）

在 `rank_candidates` 的 `out.append({...})`（现 `_locate.py:50-57`）中，`"score"` 行之后加 `"ocr_conf"`：

```python
        out.append({
            "text": it["text"],
            "center": [cx + ox, cy + oy],
            "box": [x + ox, y + oy, w, h],
            "score": _MATCH_SCORE[mf],
            "ocr_conf": round(float(it.get("conf", 0.0)), 3),  # R5: OCR 检测置信度(行级), 供低置信闸
            "match_field": mf,
            "on_screen": True,
        })
```

- [ ] **Step 4: 更新 docstring**（`_vision.py` 的 `vision_locate`，把 score/ocr_conf 语义写清）

把 `vision_locate` 的 docstring（现 `_vision.py:56-57`）改为：

```python
            """按可见文字在屏上定位元素(无障碍树失效时用,如网页/canvas/Electron)。返回排序候选。
            每候选:score=匹配质量(exact=1.0/prefix/contains,与读得清不清无关);ocr_conf=OCR 检测置信度
            (该文本【行级】读得多确信,小/糊/低对比会低——低置信闸对文字路径看这个);center 与 tap 同坐标空间。
            region=(left,top,right,bottom) 限定区域、None=全屏。"""
```

并把 `vision_locate_image` 的 docstring（现 `_vision.py:108-109`）补一句「score/best_score=模板匹配置信度∈[0,1],图标路径的低置信闸看这个」。

- [ ] **Step 5: 跑测试确认通过**（numpy 环境）

Run: `cd platforms/common && python3 -m pytest tests/test_vision_locate.py -q`
Expected: PASS（含新 2 条 + 既有 vision_locate 测试）

> **本机(缺 numpy)无法跑此测试**——`_locate.py` 顶层 `import numpy/cv2`。改动是加一个 dict key，纯逻辑；在有 numpy 的环境或真机 venv 跑。本机至少 `python3 -m py_compile platforms/common/capabilities/vision/_locate.py` 验语法。

- [ ] **Step 6: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/vision/_locate.py platforms/common/capabilities/vision/_vision.py platforms/common/tests/test_vision_locate.py
git commit -m "feat(r5): vision_locate 候选透出 ocr_conf(OCR 检测置信度, 行级)+docstring 分清 score/ocr_conf"
```

---

### Task 3: `hover_preview` core 工具 —— Windows

**Files:**
- Modify: `platforms/windows/server/win_device_mcp.py`（顶部 import + move_mouse 之后加 hover_preview）

- [ ] **Step 1: import draw_crosshair**

在 win server 的 common import 区（`sys.path.insert(common)` 之后，`import _fsops, _proc, _search` 那块旁）加：

```python
from _marker import draw_crosshair
```

- [ ] **Step 2: 加 hover_preview 工具**（在 `move_mouse`（现 `win_device_mcp.py:519-526`）之后插入）

```python
@mcp.tool
@with_touch
def hover_preview(x: int, y: int):
    """Move the real mouse to (x, y) WITHOUT clicking (triggers hover state/tooltip),
    screenshot, and draw a crosshair marker at (x, y). Use to verify a locate result
    before an irreversible / low-confidence tap: does the marked point land on the
    intended target? The marker is drawn deterministically at the tap point (screenshots
    do NOT capture the hardware cursor). Success → PNG Image; failure → {"ok": False, "error": ...}."""
    try:
        pyautogui.moveTo(x, y)
        png = _capture_logical_png()   # tap 空间 PNG(与 tap/move 同坐标空间, 画在 (x,y) 即真落点)
        return Image(data=draw_crosshair(png, x, y), format="png")
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
```

> `_capture_logical_png` 定义在文件下方（`win_device_mcp.py:959`），但按运行时全局解析——`hover_preview` 被调用时它早已定义，无前向引用问题。`Image`/`io`/`pyautogui` 顶部已 import。**无返回类型注解**：成功返 Image、失败返 dict，异构返回不加注解以免 fastmcp 类型校验冲突。

- [ ] **Step 3: 验语法**

Run: `cd platforms/windows/server && python3 -m py_compile win_device_mcp.py && echo OK`
Expected: OK

- [ ] **Step 4: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/windows/server/win_device_mcp.py
git commit -m "feat(r5): win 加 core hover_preview(移真鼠标+截图+画十字@tap点, 复用 _capture_logical_png)"
```

---

### Task 4: `hover_preview` core 工具 —— macOS

**Files:**
- Modify: `platforms/macos/server/mac_device_mcp.py`（顶部 import + move_mouse 之后加 hover_preview）

- [ ] **Step 1: import draw_crosshair**

在 mac server 的 common import 区（`sys.path.insert(common)` 后，`import _fsops, _proc, _search` 旁）加：

```python
from _marker import draw_crosshair
```

- [ ] **Step 2: 加 hover_preview 工具**（在 `move_mouse`（现 `mac_device_mcp.py:268-275`）之后插入，代码与 win 完全相同）

```python
@mcp.tool
@with_touch
def hover_preview(x: int, y: int):
    """Move the real mouse to (x, y) WITHOUT clicking (triggers hover state/tooltip),
    screenshot, and draw a crosshair marker at (x, y). Use to verify a locate result
    before an irreversible / low-confidence tap: does the marked point land on the
    intended target? The marker is drawn deterministically at the tap point (screenshots
    do NOT capture the hardware cursor). Success → PNG Image; failure → {"ok": False, "error": ...}."""
    try:
        pyautogui.moveTo(x, y)
        png = _capture_logical_png()   # tap 空间 PNG(mac: grab→resize 回逻辑, 与 tap/move 同空间)
        return Image(data=draw_crosshair(png, x, y), format="png")
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
```

> mac 的 `_capture_logical_png`（`mac_device_mcp.py:1103`）内部做 grab→(黑屏唤醒)→resize 到 `pyautogui.size()`（逻辑/tap 空间），故 (x,y) 画在正确落点。**关键**：mac 绝不能直接 `ImageGrab.grab()`（那是物理 Retina 2x, 与逻辑 (x,y) 错位）——必须走 `_capture_logical_png`。

- [ ] **Step 3: 验语法**

Run: `cd platforms/macos/server && python3 -m py_compile mac_device_mcp.py && echo OK`
Expected: OK

- [ ] **Step 4: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/macos/server/mac_device_mcp.py
git commit -m "feat(r5): mac 加 core hover_preview(复用 _capture_logical_png 保 tap 空间, 非裸 grab)"
```

---

## Phase B — On-host / 真机验收（用户在场那趟）

### Task 5: 真机验收

- [ ] **Step 1: hover_preview 视觉验收**（win/mac 真机）：任取一屏上元素坐标 (x,y)，`hover_preview(x,y)` → 返回 PNG，肉眼确认：① 鼠标确实移到了 (x,y)（hover 态/tooltip 触发）；② PNG 在 (x,y) 有醒目洋红十字+外圈；③ mac Retina 上十字落在正确位置（证 `_capture_logical_png` 的 tap 空间对齐，非物理错位）。
- [ ] **Step 2: ocr_conf 有用性验收**：对**清晰大字** vs **低对比小字**分别 `vision_locate`，确认低对比小字的 `ocr_conf` 明显低于清晰大字——证它是有用的低置信信号（而 `score` 对两者可能都 1.0/exact，区分不出）。
- [ ] **Step 3: 零回归**：`vision_tap`/`vision_locate` 既有行为不变（ocr_conf 只是多一个字段）；hover_preview 不影响任何既有工具。
- [ ] **Step 4: 取证（非阻断）**：确认 `take_screenshot` 到底含不含硬件光标（强先验=不含）——即便含，十字冗余无害。
- [ ] **Step 5: 记录验收结论回用户。**

---

## 质量门禁与收口（charter）

- [ ] **code-reviewer 审**：Phase A 落完，派 code-reviewer 审 diff（重点：ocr_conf 加字段零回归、hover_preview 复用 _capture_logical_png 保 tap 空间/mac 不裸 grab、draw_crosshair 越界不崩、只读除移鼠标）。发现问题先修复复验。
- [ ] **真机验收通过**（Task 5，用户在场）。
- [ ] **合并 + tag**：审过 + 真机过 → squash-merge PR → 打 `v0.8.x-alpha` annotated tag → GitHub Release(prerelease=true)。**合并/发版前与用户确认**（charter 不可逆/外发条款）。

---

## Self-Review（写完计划的自查）

- **Spec 覆盖**：ocr_conf 暴露(§4.1)→Task 2；hover_preview core+draw_crosshair(§4.2)→Task 1/3/4；score/ocr_conf docstring(§4.1)→Task 2 Step4；编排归 charter(NG1)→不做；真机验收(§5.2/§6)→Task 5。✓
- **占位扫描**：无 TBD。Task 2 的 numpy 环境依赖、Task 5 的真机依赖已在 GATE/注记说明，非空泛占位。
- **命名/签名一致**：`draw_crosshair(png_bytes,x,y,size,color,width)`、`hover_preview(x,y)`、`ocr_conf` 字段、复用 `_capture_logical_png`——全计划一致；win/mac 的 hover_preview 代码逐字相同（只注释平台差异）。
- **一处强调**：mac hover_preview **必须**走 `_capture_logical_png`（非裸 `ImageGrab.grab()`），否则 Retina 物理/逻辑错位——已在 Task 4 Step2 注记红字。

## ⚠️ 跨分支集成注记（R1 ↔ R5）

R5 从 main 起、hover_preview 复用 main 上的 `_capture_logical_png`。但 **R1 分支**（`feat/vision-coordinate-calibration-r1`，未合并）把两端 capture 收敛成单一 `_capture_in_tap_space`：**win 删除了 `_capture_logical_png`、mac 改成转调它的薄封装**。故 R1、R5 都要合入 main 时有集成点：

- **R5 先合、R1 后合**：R1 合入时删 win `_capture_logical_png` → 必须同时把 win `hover_preview` 里的 `_capture_logical_png()` 改为 `_capture_in_tap_space()`（mac 因保留薄封装不受影响，但也宜统一改 `_capture_in_tap_space`）。
- **R1 先合、R5 后合**：R5 rebase/合入时，win 上 `_capture_logical_png` 已不存在 → 把 R5 hover_preview 的调用直接写成 `_capture_in_tap_space()`。
- **本质**：两者都指「tap 空间截图的单一来源」，只是名字随 R1 变。集成时对齐到 `_capture_in_tap_space` 即可，语义不变。合并 R1/R5 的人（真机验收后那趟）留意这一处，py_compile + on-host smoke 会立刻抓到漏改（NameError）。
