# vision 定位能力模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 pc-device(win/mac)新增 `vision` 能力模块——无障碍树为空时(web/canvas/Electron/Flutter/游戏)用本地 OCR + 模板匹配做像素级元素定位(`vision_locate`/`vision_tap`/`vision_locate_image`),坐标与 core `tap` 同空间。

**Architecture:** 纯逻辑(匹配排序/子行定位/ROI/模板匹配)抽到 `_locate.py`,可不依赖 RapidOCR、用 fake OCR 结果与合成图在 Linux CI 全测;OCR 引擎单例+锁在 `_ocr.py`;`_vision.py` 是 `CapabilityModule`,**靠 server 注入 `capture_fn`/`tap_fn`** 破循环依赖(capability 不 import server)。3 工具镜像 element-action 心智。

**Tech Stack:** Python 3.10+,RapidOCR(rapidocr-onnxruntime,PP-OCRv4 ONNX,CPU),OpenCV(opencv-python-headless),NumPy,FastMCP,pytest。

**Spec:** `docs/internal/design/2026-06-04-vision-localization-capability.md`(已 architect 审,B1–B4 已并入)。

---

## 数据结构契约(全 plan 统一,勿改名)

- **OCR 归一项**(`run_ocr` 输出):`{"text": str, "box": [x, y, w, h], "conf": float}`(轴对齐 bbox,左上+宽高,点空间)。
- **候选**(`rank_candidates` 输出):`{"text": str, "center": [x, y], "box": [x, y, w, h], "score": float, "match_field": str, "on_screen": bool}`。
- **region**:`(left, top, right, bottom)` 逻辑像素(对齐 core `take_screenshot`);`None` = 全屏。
- **图像**:OpenCV BGR `np.ndarray`(`cv2.imdecode` 解的 PNG)。

## 文件结构

| 文件 | 职责 |
|---|---|
| `platforms/common/capabilities/vision/__init__.py` | export `VisionCapability` |
| `platforms/common/capabilities/vision/_locate.py` | **纯逻辑**:decode/crop/sub-line/rank/template(不 import rapidocr,可 fake 测) |
| `platforms/common/capabilities/vision/_ocr.py` | RapidOCR 引擎单例 + `threading.Lock` + `run_ocr` 归一化 |
| `platforms/common/capabilities/vision/_vision.py` | `VisionCapability(capture_fn, tap_fn)` + register 3 工具 |
| `platforms/common/tests/test_vision_locate.py` | 纯逻辑单测(无 rapidocr) |
| `platforms/common/tests/test_vision_ocr.py` | OCR 管线 + 并发 |
| `platforms/common/tests/test_vision.py` | 工具集成(注入 fake capture/tap) |

**修改**:`capabilities/__init__.py`(export)、`mac_device_mcp.py`/`win_device_mcp.py`(抽 helper + 注入 + docstring)、`macos|windows/platform.toml`、`*/server/requirements.txt`+pyproject、`docs/architecture.md`。

## 🔑 测试约定（权威——覆盖下方各 Task 里的测试文件路径 / 导入 / 运行命令）

核实自现有 `platforms/common/tests/`(conftest.py 已 `sys.path.insert(0, platforms/common)`):
- **测试文件统一放 `platforms/common/tests/`**(不是 `capabilities/vision/tests/`):`test_vision_locate.py`(Task 2–5)、`test_vision_ocr.py`(Task 6)、`test_vision.py`(Task 7–10)。**不建 `capabilities/vision/tests/` 目录与其 `__init__.py`。**
- **导入(测试文件里)**:`from capabilities.vision import _locate, _ocr` / `from capabilities.vision._vision import VisionCapability, _probe_deps`。**不要**用 `from platforms.common.capabilities...`(repo-root 不在 path,且触发 browser 的 `from _browser_lease import` bare-import 失败)。
- **运行命令一律**:`cd platforms/common/tests && /tmp/vision-dev/bin/python -m pytest <test_vision_*.py> -v`。
- **源码**仍在 `platforms/common/capabilities/vision/`,内部相对导入(`from .._base import ...`、`from . import _locate`),同 human_browser。
- **下方各 Task 的 `Test:` 路径、`from platforms.common...` 导入行、pytest 命令路径,全部以本约定为准。**

## 测试环境准备(实现前一次性)

```bash
cd /home/worker/claude-test/claude-remote/agent-fleet
python3 -m venv /tmp/vision-dev && /tmp/vision-dev/bin/pip install -U pip \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
/tmp/vision-dev/bin/pip install rapidocr-onnxruntime opencv-python-headless numpy pytest \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```
全部 `pytest` 用 `/tmp/vision-dev/bin/python -m pytest`。OCR/模板测试用 `cv2.putText`(Latin/数字,无需字体文件),CJK 准确率已 spike 验过、单测不重复证。

---

### Task 1: 包骨架 + 依赖声明

**Files:**
- Create: `platforms/common/capabilities/vision/__init__.py`
- Modify: `platforms/macos/server/requirements.txt`、`platforms/windows/server/requirements.txt`

- [ ] **Step 1: 建包(空 `__init__.py`,先不 export,Task 11 再补)**

`platforms/common/capabilities/vision/__init__.py`:
```python
"""vision capability — 无障碍树失效时的像素级元素定位(设计 2026-06-04)."""
```
（**不建** `capabilities/vision/tests/`——测试统一在 `platforms/common/tests/`,见上方测试约定。）

- [ ] **Step 2: 加依赖**

两个 `requirements.txt` 各追加：
```
rapidocr-onnxruntime
opencv-python-headless
```

- [ ] **Step 3: Commit**
```bash
git add platforms/common/capabilities/vision platforms/macos/server/requirements.txt platforms/windows/server/requirements.txt
git commit -m "feat(vision): package skeleton + deps"
```

---

### Task 2: `_locate.decode_png` + `crop_region`(ROI + 偏移)

**Files:**
- Create: `platforms/common/capabilities/vision/_locate.py`
- Test: `platforms/common/capabilities/vision/tests/test_locate.py`

- [ ] **Step 1: 失败测试**
```python
# platforms/common/tests/test_vision_locate.py
import numpy as np, cv2
from capabilities.vision import _locate

def test_decode_png_roundtrip():
    img = np.zeros((10, 20, 3), np.uint8); img[:, :, 2] = 255  # red
    ok, buf = cv2.imencode(".png", img)
    out = _locate.decode_png(buf.tobytes())
    assert out.shape == (10, 20, 3)
    assert int(out[0, 0, 2]) == 255

def test_crop_region_offset():
    img = np.zeros((100, 200, 3), np.uint8)
    cropped, offset = _locate.crop_region(img, (50, 20, 150, 60))  # left,top,right,bottom
    assert cropped.shape == (40, 100, 3)
    assert offset == (50, 20)

def test_crop_region_none():
    img = np.zeros((100, 200, 3), np.uint8)
    cropped, offset = _locate.crop_region(img, None)
    assert cropped.shape == (100, 200, 3) and offset == (0, 0)
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py -v`
Expected: FAIL（`module _locate not found` / `decode_png` 未定义）

- [ ] **Step 3: 最小实现**
```python
# _locate.py
from __future__ import annotations
import numpy as np
import cv2

def decode_png(data: bytes) -> np.ndarray:
    """PNG bytes -> OpenCV BGR ndarray."""
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("decode_png: not a valid image")
    return img

def crop_region(img: np.ndarray, region):
    """region=(left,top,right,bottom) or None. Returns (cropped, (ox, oy))."""
    if region is None:
        return img, (0, 0)
    l, t, r, b = region
    h, w = img.shape[:2]
    l, t = max(0, l), max(0, t)
    r, b = min(w, r), min(h, b)
    return img[t:b, l:r], (l, t)
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_locate.py platforms/common/capabilities/vision/tests/test_locate.py
git commit -m "feat(vision): decode_png + crop_region (ROI+offset)"
```

---

### Task 3: `_locate.sub_line_center`(子行定位——精度命门)

**Files:**
- Modify: `platforms/common/capabilities/vision/_locate.py`
- Test: `platforms/common/capabilities/vision/tests/test_locate.py`

- [ ] **Step 1: 失败测试**
```python
def test_sub_line_center_substring():
    # OCR 行框 box=[x,y,w,h]=[100,20,200,16], 识别文本 "330 points by Max", 找 "by"
    # "by" 在第 11-12 字符(共 17 字), 比例中心 ~ (11.5/17)
    box = [100, 20, 200, 16]
    cx, cy = _locate.sub_line_center(box, "330 points by Max", "by")
    assert 220 <= cx <= 260      # 100 + 200*(~0.676) ≈ 235
    assert cy == 28              # 20 + 16/2

def test_sub_line_center_fallback_whole_line():
    box = [100, 20, 200, 16]
    cx, cy = _locate.sub_line_center(box, "登录", "登录")  # query==whole text
    assert cx == 200 and cy == 28  # 整行中心

def test_sub_line_center_not_found_fallback():
    box = [100, 20, 200, 16]
    cx, cy = _locate.sub_line_center(box, "abc", "zzz")  # 不在文本里 → 整行中心
    assert cx == 200 and cy == 28
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py::test_sub_line_center_substring -v`
Expected: FAIL（`sub_line_center` 未定义）

- [ ] **Step 3: 实现**
```python
def sub_line_center(box, full_text: str, query: str):
    """OCR 把整行合并 → 按 query 在 full_text 里的字符比例切子框, 返回子框中心 [x,y].
    找不到 query → 整行中心 (降级)."""
    x, y, w, h = box
    cy = y + h // 2
    lt, lq = full_text.lower(), query.lower()
    i = lt.find(lq)
    n = len(full_text)
    if i < 0 or n == 0:
        return [x + w // 2, cy]
    frac = (i + len(query) / 2.0) / n        # query 跨度中点的字符比例
    return [int(x + w * frac), cy]
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_locate.py platforms/common/capabilities/vision/tests/test_locate.py
git commit -m "feat(vision): sub_line_center (子行定位)"
```

---

### Task 4: `_locate.rank_candidates`(匹配/排序/消歧/偏移/截断)

**Files:**
- Modify: `platforms/common/capabilities/vision/_locate.py`
- Test: `platforms/common/capabilities/vision/tests/test_locate.py`

- [ ] **Step 1: 失败测试**
```python
def _items():
    # 归一 OCR 项 {text, box:[x,y,w,h], conf}
    return [
        {"text": "登录", "box": [1180, 20, 40, 16], "conf": 0.99},      # exact
        {"text": "登录注册", "box": [1180, 50, 80, 16], "conf": 0.95},  # contains
        {"text": "用户登录页", "box": [300, 200, 100, 16], "conf": 0.9}, # contains
    ]

def test_rank_exact_first_and_center():
    c = _locate.rank_candidates(_items(), "登录", offset=(0, 0), max_results=20)
    assert c[0]["text"] == "登录" and c[0]["match_field"] == "exact"
    assert c[0]["score"] == 1.0
    assert c[0]["center"] == [1200, 28]   # 1180+40/2, 20+16/2

def test_rank_offset_added():
    c = _locate.rank_candidates(_items()[:1], "登录", offset=(50, 10), max_results=20)
    assert c[0]["center"] == [1250, 38]

def test_rank_no_match_empty():
    assert _locate.rank_candidates(_items(), "zzz", offset=(0, 0), max_results=20) == []

def test_rank_max_results_truncates():
    items = [{"text": f"go{i}", "box": [i, 0, 10, 10], "conf": 0.9} for i in range(30)]
    c = _locate.rank_candidates(items, "go", offset=(0, 0), max_results=5)
    assert len(c) == 5
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py::test_rank_exact_first_and_center -v`
Expected: FAIL

- [ ] **Step 3: 实现**
```python
_MATCH_SCORE = {"exact": 1.0, "prefix": 0.8, "contains": 0.6}

def _match_field(text: str, query: str) -> str | None:
    lt, lq = text.lower(), query.lower()
    if lt == lq:
        return "exact"
    if lt.startswith(lq):
        return "prefix"
    if lq in lt:
        return "contains"
    return None

def rank_candidates(ocr_items, query: str, offset=(0, 0), max_results: int = 20):
    """筛 query 子串命中项 → 子行定位中心(+offset) → 按 (exact>prefix>contains, 阅读序) 排序 → 截断."""
    ox, oy = offset
    out = []
    for it in ocr_items:
        mf = _match_field(it["text"], query)
        if mf is None:
            continue
        cx, cy = sub_line_center(it["box"], it["text"], query)
        x, y, w, h = it["box"]
        out.append({
            "text": it["text"],
            "center": [cx + ox, cy + oy],
            "box": [x + ox, y + oy, w, h],
            "score": _MATCH_SCORE[mf],
            "match_field": mf,
            "on_screen": True,  # 只 OCR 可见截图, 命中即在屏
        })
    rank = {"exact": 0, "prefix": 1, "contains": 2}
    out.sort(key=lambda c: (rank[c["match_field"]], c["center"][1] // 8, c["center"][0]))
    return out[:max_results]
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_locate.py platforms/common/capabilities/vision/tests/test_locate.py
git commit -m "feat(vision): rank_candidates (匹配/排序/偏移/截断)"
```

---

### Task 5: `_locate.match_template`(模板匹配 + 偏移)

**Files:**
- Modify: `platforms/common/capabilities/vision/_locate.py`
- Test: `platforms/common/capabilities/vision/tests/test_locate.py`

- [ ] **Step 1: 失败测试**
```python
def test_match_template_same_scale_hit():
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (0, 255, 0), -1)  # 绿块
    tmpl = img[60:90, 100:140].copy()
    r = _locate.match_template(img, tmpl, threshold=0.85, offset=(0, 0))
    assert r["found"] is True
    assert abs(r["center"][0] - 120) <= 2 and abs(r["center"][1] - 75) <= 2
    assert r["score"] > 0.95

def test_match_template_offset():
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (0, 255, 0), -1)
    tmpl = img[60:90, 100:140].copy()
    r = _locate.match_template(img, tmpl, threshold=0.85, offset=(10, 5))
    assert abs(r["center"][0] - 130) <= 2 and abs(r["center"][1] - 80) <= 2

def test_match_template_below_threshold():
    img = np.zeros((200, 300, 3), np.uint8)
    tmpl = np.full((30, 40, 3), 255, np.uint8)  # 全白, 图里没有
    r = _locate.match_template(img, tmpl, threshold=0.85, offset=(0, 0))
    assert r["found"] is False and "best_score" in r
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py::test_match_template_same_scale_hit -v`
Expected: FAIL

- [ ] **Step 3: 实现**
```python
def match_template(img: np.ndarray, template: np.ndarray, threshold: float, offset=(0, 0)):
    """OpenCV 单尺度模板匹配. 命中→{found:True,center,score}; 否则{found:False,best_score}."""
    ox, oy = offset
    res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    if maxv < threshold:
        return {"found": False, "best_score": round(float(maxv), 3)}
    th, tw = template.shape[:2]
    return {
        "found": True,
        "center": [int(maxloc[0] + tw / 2 + ox), int(maxloc[1] + th / 2 + oy)],
        "score": round(float(maxv), 3),
    }
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_locate.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_locate.py platforms/common/capabilities/vision/tests/test_locate.py
git commit -m "feat(vision): match_template"
```

---

### Task 6: `_ocr`(RapidOCR 引擎单例 + 锁 + 归一化 + 并发)

**Files:**
- Create: `platforms/common/capabilities/vision/_ocr.py`
- Test: `platforms/common/capabilities/vision/tests/test_ocr.py`

- [ ] **Step 1: 失败测试**
```python
# platforms/common/tests/test_vision_ocr.py
import numpy as np, cv2
from capabilities.vision import _ocr

def _login_img():
    img = np.full((80, 300, 3), 255, np.uint8)
    cv2.putText(img, "LOGIN 12345", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    return img

def test_run_ocr_normalized_shape():
    items = _ocr.run_ocr(_login_img())
    assert items and all({"text", "box", "conf"} <= set(it) for it in items)
    joined = " ".join(it["text"].upper() for it in items)
    assert "LOGIN" in joined.replace(" ", "") or "LOGIN" in joined
    it0 = items[0]
    assert len(it0["box"]) == 4  # [x,y,w,h]

def test_run_ocr_concurrent_stable():
    import concurrent.futures as cf
    img = _login_img()
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda _: _ocr.run_ocr(img), range(8)))
    assert all(r for r in results)  # 无崩溃、都非空
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_ocr.py -v`
Expected: FAIL（`_ocr` 不存在）

- [ ] **Step 3: 实现**
```python
# _ocr.py
from __future__ import annotations
import threading
import numpy as np

_engine = None
_engine_lock = threading.Lock()   # 保护引擎构造
_run_lock = threading.Lock()      # 串行化推理(B3: RapidOCR 线程安全不确定)

def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR()
    return _engine

def run_ocr(img_bgr: np.ndarray):
    """返回归一项 [{text, box:[x,y,w,h], conf}]. 串行锁保护推理."""
    eng = _get_engine()
    with _run_lock:
        res, _ = eng(img_bgr)
    out = []
    for box4, text, score in (res or []):
        xs = [p[0] for p in box4]; ys = [p[1] for p in box4]
        x, y = int(min(xs)), int(min(ys))
        w, h = int(max(xs) - x), int(max(ys) - y)
        out.append({"text": text, "box": [x, y, w, h], "conf": float(score)})
    return out
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_ocr.py -v`
Expected: PASS（首跑含模型冷启,可能 ~数秒）

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_ocr.py platforms/common/capabilities/vision/tests/test_ocr.py
git commit -m "feat(vision): OCR engine singleton + lock + run_ocr"
```

---

### Task 7: `VisionCapability` 骨架(元数据 + availability)

**Files:**
- Create: `platforms/common/capabilities/vision/_vision.py`
- Test: `platforms/common/capabilities/vision/tests/test_vision.py`

- [ ] **Step 1: 失败测试**
```python
# platforms/common/tests/test_vision.py
from capabilities.vision._vision import VisionCapability, _probe_deps

def _noop_capture():
    return b""
def _noop_tap(x, y):
    pass

def test_metadata():
    cap = VisionCapability(capture_fn=_noop_capture, tap_fn=_noop_tap)
    assert cap.id == "vision"
    assert cap.origin == "self-built"
    assert cap.platforms == ["windows", "macos"]
    assert cap.skill == "using-vision"
    assert cap.display_name and cap.usage_hint  # 非空发现信息

def test_availability_deps_present():
    cap = VisionCapability(capture_fn=_noop_capture, tap_fn=_noop_tap)
    ok, reason = cap.availability()
    assert ok is True and reason == ""

def test_availability_deps_missing(monkeypatch):
    monkeypatch.setattr("capabilities.vision._vision._probe_deps",
                        lambda: (False, "rapidocr/opencv 未装"))
    cap = VisionCapability(capture_fn=_noop_capture, tap_fn=_noop_tap)
    ok, reason = cap.availability()
    assert ok is False and "未装" in reason
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py::test_metadata -v`
Expected: FAIL

- [ ] **Step 3: 实现**
```python
# _vision.py
from __future__ import annotations
from typing import Callable, Optional
from .._base import CapabilityModule, ORIGIN_SELF_BUILT

def _probe_deps():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        import cv2  # noqa: F401
        return True, ""
    except Exception as e:
        return False, f"vision 依赖未安装(rapidocr-onnxruntime/opencv): {e}"

class VisionCapability(CapabilityModule):
    id = "vision"
    display_name = "视觉定位 vision(无障碍树失效时按文字/图标定位元素)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-vision"
    platforms = ["windows", "macos"]
    usage_hint = (
        "find_elements/tap_element 在 web/无 AX 树场景拿不到元素时用:vision_locate(query) "
        "按可见文字定位→候选+中心坐标;vision_tap(query) 找到即点;vision_locate_image(模板图) "
        "定位无字图标。只管定位,读懂页面用 take_screenshot 交给自己的视觉。"
    )

    def __init__(self, capture_fn: Callable[[], bytes], tap_fn: Callable[[int, int], None]):
        self._capture_fn = capture_fn   # () -> PNG bytes(点空间, 同 take_screenshot)
        self._tap_fn = tap_fn           # (x, y) -> None(OS 级点击, 同 tap)
        self.description = (
            "自建:OS 无障碍树为空时(网页/canvas/Electron/Flutter/游戏),用本地 OCR + 模板匹配"
            "按文字或图标图做像素级元素定位,返回与 tap 同坐标空间的中心点。0 LLM token、离线、纯 CPU。"
        )

    def availability(self):
        return _probe_deps()

    def register(self, mcp) -> list[str]:
        return []  # 工具在后续 Task 加
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_vision.py platforms/common/capabilities/vision/tests/test_vision.py
git commit -m "feat(vision): VisionCapability skeleton + availability"
```

---

### Task 8: 工具 `vision_locate`(capture→decode→crop→ocr→rank)

**Files:**
- Modify: `platforms/common/capabilities/vision/_vision.py`
- Test: `platforms/common/capabilities/vision/tests/test_vision.py`

- [ ] **Step 1: 失败测试**
```python
import numpy as np, cv2

def _png_bytes_login():
    img = np.full((80, 400, 3), 255, np.uint8)
    cv2.putText(img, "LOGIN", (250, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()

class _FakeMCP:
    def __init__(self): self.tools = {}
    def tool(self, fn): self.tools[fn.__name__] = fn; return fn

def test_vision_locate_finds_text():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP(); names = cap.register(m)
    assert "vision_locate" in names
    r = m.tools["vision_locate"]("LOGIN")
    assert r["ok"] and r["count"] >= 1
    c0 = r["candidates"][0]
    assert "LOGIN" in c0["text"].upper()
    assert 230 <= c0["center"][0] <= 360 and 30 <= c0["center"][1] <= 70

def test_vision_locate_not_found_has_sample():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP(); cap.register(m)
    r = m.tools["vision_locate"]("ZZZNOPE")
    assert r["ok"] and r["count"] == 0 and "ocr_sample" in r
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py::test_vision_locate_finds_text -v`
Expected: FAIL（`vision_locate` 未注册）

- [ ] **Step 3: 实现(改 `register`)**
```python
    def register(self, mcp) -> list[str]:
        from . import _locate, _ocr

        def _locate_impl(query, region, max_results):
            img = _locate.decode_png(self._capture_fn())
            cropped, offset = _locate.crop_region(img, region)
            items = _ocr.run_ocr(cropped)
            cands = _locate.rank_candidates(items, query, offset=offset, max_results=max_results)
            return items, cands

        @mcp.tool
        def vision_locate(query: str, region: Optional[tuple] = None,
                          max_results: int = 20) -> dict:
            """按可见文字在屏上定位元素(无障碍树失效时用,如网页/canvas/Electron)。返回排序候选
            (含与 tap 同坐标空间的 center)。region=(left,top,right,bottom) 限定区域、None=全屏。"""
            try:
                items, cands = _locate_impl(query, region, max_results)
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if not cands:
                sample = " ".join(it["text"] for it in items[:12])
                return {"ok": True, "query": query, "count": 0, "candidates": [],
                        "ocr_sample": sample,
                        "hint": "换个可见文字 / 缩小 region / 该处可能低对比,改用 take_screenshot 让自己的视觉读"}
            return {"ok": True, "query": query, "count": len(cands), "candidates": cands}

        return ["vision_locate"]
```

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_vision.py platforms/common/capabilities/vision/tests/test_vision.py
git commit -m "feat(vision): vision_locate tool"
```

---

### Task 9: 工具 `vision_tap`(locate→nth→tap_fn)

**Files:**
- Modify: `platforms/common/capabilities/vision/_vision.py`
- Test: `platforms/common/capabilities/vision/tests/test_vision.py`

- [ ] **Step 1: 失败测试**
```python
def test_vision_tap_clicks_center():
    taps = []
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: taps.append((x, y)))
    m = _FakeMCP(); names = cap.register(m)
    assert "vision_tap" in names
    r = m.tools["vision_tap"]("LOGIN")
    assert r["ok"] and len(taps) == 1
    assert taps[0] == tuple(r["tapped"]["center"])

def test_vision_tap_not_found():
    taps = []
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: taps.append((x, y)))
    m = _FakeMCP(); cap.register(m)
    r = m.tools["vision_tap"]("ZZZNOPE")
    assert r["ok"] is False and r["error"] == "not found" and not taps

def test_vision_tap_nth_out_of_range():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP(); cap.register(m)
    r = m.tools["vision_tap"]("LOGIN", None, 9)
    assert r["ok"] is False and "range" in r["error"].lower()
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py::test_vision_tap_clicks_center -v`
Expected: FAIL

- [ ] **Step 3: 实现(在 `register` 内 `vision_locate` 之后加,return 追加名字)**
```python
        @mcp.tool
        def vision_tap(query: str, region: Optional[tuple] = None,
                       nth: Optional[int] = None) -> dict:
            """按可见文字定位并点击(无障碍树失效时用)。nth: 0-based,0=最优候选;省略=自动
            (唯一/exact 即点,多个歧义则不点、返回候选)。"""
            try:
                _items, cands = _locate_impl(query, region, 20)
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if not cands:
                sample = " ".join(it["text"] for it in _items[:12])
                return {"ok": False, "error": "not found", "ocr_sample": sample,
                        "hint": "换更具体可见文字 / 缩小 region"}
            if nth is None:
                if len(cands) > 1 and cands[0]["match_field"] != "exact":
                    return {"ok": False, "error": "ambiguous", "candidates": cands,
                            "hint": "传 nth(0-based) 或更具体的 query"}
                pick = cands[0]
            else:
                if nth < 0 or nth >= len(cands):
                    return {"ok": False, "error": f"nth out of range (0..{len(cands)-1})",
                            "total_candidates": len(cands)}
                pick = cands[nth]
            x, y = pick["center"]
            self._tap_fn(x, y)
            return {"ok": True, "tapped": {"text": pick["text"], "center": [x, y]},
                    "total_candidates": len(cands)}

        return ["vision_locate", "vision_tap"]
```
（删掉旧 `return ["vision_locate"]`。）

- [ ] **Step 4: 跑,确认通过**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_vision.py platforms/common/capabilities/vision/tests/test_vision.py
git commit -m "feat(vision): vision_tap tool"
```

---

### Task 10: 工具 `vision_locate_image`(模板匹配)

**Files:**
- Modify: `platforms/common/capabilities/vision/_vision.py`
- Test: `platforms/common/capabilities/vision/tests/test_vision.py`

- [ ] **Step 1: 失败测试**
```python
import base64

def _png_with_green_box():
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (0, 255, 0), -1)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()

def _green_template_b64():
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (0, 255, 0), -1)
    tmpl = img[60:90, 100:140].copy()
    ok, buf = cv2.imencode(".png", tmpl)
    return base64.b64encode(buf.tobytes()).decode()

def test_vision_locate_image_hit():
    cap = VisionCapability(capture_fn=_png_with_green_box, tap_fn=lambda x, y: None)
    m = _FakeMCP(); names = cap.register(m)
    assert "vision_locate_image" in names
    r = m.tools["vision_locate_image"](_green_template_b64(), None, None, 0.85)
    assert r["ok"] and r["found"] and abs(r["center"][0] - 120) <= 2

def test_vision_locate_image_requires_template():
    cap = VisionCapability(capture_fn=_png_with_green_box, tap_fn=lambda x, y: None)
    m = _FakeMCP(); cap.register(m)
    r = m.tools["vision_locate_image"](None, None, None, 0.85)
    assert r["ok"] is False and "required" in r["error"]
```

- [ ] **Step 2: 跑,确认失败**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/test_vision.py::test_vision_locate_image_hit -v`
Expected: FAIL

- [ ] **Step 3: 实现(在 `register` 内加;import base64;return 追加名字)**
在 `_vision.py` 顶部 import 加 `import base64`。`register` 内加：
```python
        @mcp.tool
        def vision_locate_image(template_b64: Optional[str] = None,
                                template_path: Optional[str] = None,
                                region: Optional[tuple] = None,
                                threshold: float = 0.85) -> dict:
            """按图标图(无字元素)定位。template_b64 / template_path 二选一(同当前显示缩放截取,
            单尺度,跨 DPI 会掉)。命中返回 center(与 tap 同坐标空间)。"""
            if template_b64 is None and template_path is None:
                return {"ok": False, "error": "template_b64 or template_path required"}
            try:
                if template_b64 is not None:
                    tmpl = _locate.decode_png(base64.b64decode(template_b64))
                else:
                    with open(template_path, "rb") as f:
                        tmpl = _locate.decode_png(f.read())
                img = _locate.decode_png(self._capture_fn())
                cropped, offset = _locate.crop_region(img, region)
                res = _locate.match_template(cropped, tmpl, threshold, offset=offset)
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if not res["found"]:
                res["hint"] = "模板需按当前显示缩放截取;跨 DPI 会掉(单尺度限制)"
            return {"ok": True, **res}

        return ["vision_locate", "vision_tap", "vision_locate_image"]
```
（删掉旧 `return ["vision_locate", "vision_tap"]`。）

- [ ] **Step 4: 跑,确认通过(全套)**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/ -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/vision/_vision.py platforms/common/capabilities/vision/tests/test_vision.py
git commit -m "feat(vision): vision_locate_image tool"
```

---

### Task 11: 包 export + `capabilities/__init__.py`(B1)

**Files:**
- Modify: `platforms/common/capabilities/vision/__init__.py`
- Modify: `platforms/common/capabilities/__init__.py`

- [ ] **Step 1: 失败测试(临时断言导入路径)**
Run: `cd platforms/common && /tmp/vision-dev/bin/python -c "from capabilities import VisionCapability; print('ok')"`
Expected: FAIL（`ImportError: cannot import name 'VisionCapability'`）

- [ ] **Step 2: vision 包 export**
`platforms/common/capabilities/vision/__init__.py`:
```python
"""vision capability — 无障碍树失效时的像素级元素定位(设计 2026-06-04)."""
from ._vision import VisionCapability

__all__ = ["VisionCapability"]
```

- [ ] **Step 3: 顶层 capabilities export**
`platforms/common/capabilities/__init__.py`:在 `from .browser import ...` 后加：
```python
from .vision import VisionCapability
```
并在 `__all__` 列表里加 `"VisionCapability",`。

- [ ] **Step 4: 跑,确认通过**
Run: `cd platforms/common && /tmp/vision-dev/bin/python -c "from capabilities import VisionCapability; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**
```bash
git add platforms/common/capabilities/__init__.py platforms/common/capabilities/vision/__init__.py
git commit -m "feat(vision): export VisionCapability (capabilities __init__)"
```

---

### Task 12: 接入 mac/win server(抽 helper + 注入,B4)+ docstring + platform.toml

**Files:**
- Modify: `platforms/macos/server/mac_device_mcp.py`
- Modify: `platforms/windows/server/win_device_mcp.py`
- Modify: `platforms/macos/platform.toml`、`platforms/windows/platform.toml`

> 说明:`take_screenshot`/`tap` 是 server 里的 `@mcp.tool`。先把核心逻辑抽成纯 helper(不带装饰),`@mcp.tool` 改调它;再把 helper 注入 `VisionCapability`。capability 不 import server(破循环)。

- [ ] **Step 1: mac 抽 `_capture_logical_png` / `_os_tap`**

在 `mac_device_mcp.py` 的 `take_screenshot` **之前**加纯 helper(把现有抓图+唤醒+logical-resize 逻辑搬进来,返回 PNG bytes):
```python
def _capture_logical_png() -> bytes:
    """全屏抓图 → logical 像素 PNG bytes(与 take_screenshot 同实现, 供 vision 注入)。"""
    img = ImageGrab.grab()
    if _frame_is_black(img) or _screensaver_running():
        _wake_display()
        time.sleep(1.5)
        img = ImageGrab.grab()
    target = pyautogui.size()
    if img.size != target:
        from PIL import Image as PILImage
        img = img.resize(target, PILImage.LANCZOS)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue()

def _os_tap(x: int, y: int) -> None:
    pyautogui.click(x=x, y=y)
```
（`take_screenshot` 工具体可保持原样,或改为 `data = _capture_logical_png()` 后按 region 处理——保留原 region 行为,vision 只用全屏 helper。不强制重构 take_screenshot,避免回归;helper 是新增。）

- [ ] **Step 2: mac 注入 VisionCapability**

找到 mac server 里 `registry.add(HumanBrowserCapability())`（或 `add(...)` 接入 capability 处),其后加：
```python
from capabilities import VisionCapability
registry.add(VisionCapability(capture_fn=_capture_logical_png, tap_fn=_os_tap))
```
（若该处已 `from capabilities import (...)` 批量导入,把 `VisionCapability` 加进去。）

- [ ] **Step 3: win 同样处理**

`win_device_mcp.py`:照搬 helper(用 win 现有的截屏实现——查其 `take_screenshot` 体,通常也是 `ImageGrab`/`pyautogui`;若不同则按其实现抽),`_os_tap(x,y)` = win 现有点击实现;同样 `registry.add(VisionCapability(capture_fn=..., tap_fn=...))`。

- [ ] **Step 4: 更新 element-action docstring**

`mac_device_mcp.py` 与 `win_device_mcp.py` 的 `find_elements`/`tap_element` docstring 里 "for web, fall back to take_screenshot + tap" 改为 "for web / 无 AX 树, fall back to vision_locate / vision_tap"。

- [ ] **Step 5: platform.toml 启用(可选默认)**

`platforms/macos/platform.toml` 与 `platforms/windows/platform.toml` 的 `[capabilities].enabled` 列表加 `"vision"`。

- [ ] **Step 6: venv 内 import 自检(两平台主机真机做,或本地 dry-run)**
Run（本地 dry-run,确保无语法/循环导入）:
`/tmp/vision-dev/bin/python -c "import ast; ast.parse(open('platforms/macos/server/mac_device_mcp.py').read()); ast.parse(open('platforms/windows/server/win_device_mcp.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 7: Commit**
```bash
git add platforms/macos/server/mac_device_mcp.py platforms/windows/server/win_device_mcp.py platforms/macos/platform.toml platforms/windows/platform.toml
git commit -m "feat(vision): wire into mac/win server (inject capture/tap) + enable + docstrings"
```

---

### Task 13: skill 文档 `using-vision`

**Files:**
- Create: `platforms/macos/skills/using-vision/SKILL.md`
- Create: `platforms/windows/skills/using-vision/SKILL.md`(同内容,平台名替换)

- [ ] **Step 1: 写 skill**（要点,非占位——完整写出）:
  - 何时用:`find_elements`/`tap_element` 在 web/canvas/Electron/Flutter/游戏拿不到元素时。
  - 三工具用法 + 例子:`vision_locate("登录")` → 看候选 → `vision_tap("登录")`;`vision_tap` 的 `nth` 0-based + 省略自动消歧;`vision_locate_image` 给模板图。
  - 坐标与 core `tap` 同空间;`region=(left,top,right,bottom)` 缩小范围提速。
  - **红线/边界**:只管定位,不是全屏 OCR;读懂页面 / 低对比文字用 `take_screenshot` 交给自己的视觉。模板单尺度、跨 DPI 会掉。
  - 失败:not-found 会带 `ocr_sample`(读到了什么),据此调整。

- [ ] **Step 2: Commit**
```bash
git add platforms/macos/skills/using-vision platforms/windows/skills/using-vision
git commit -m "docs(vision): using-vision skill"
```

---

### Task 14: 文档登记 + 真机冒烟(质量门禁)

**Files:**
- Modify: `docs/architecture.md`(平台扩展表登记 vision 工具)

- [ ] **Step 1: architecture.md 平台扩展表**：Windows / macOS 行的扩展工具列加 `vision_locate`/`vision_tap`/`vision_locate_image`（无障碍树失效时像素定位）。

- [ ] **Step 2: 全套单测复跑**
Run: `/tmp/vision-dev/bin/python -m pytest platforms/common/capabilities/vision/tests/ -v`
Expected: PASS（全部）

- [ ] **Step 3: 真机冒烟(win + mac 各一次,对着 spec §1.4 成功判据)**
  - 主机 venv 装 `rapidocr-onnxruntime opencv-python-headless`(走镜像)。
  - 重启 server + 客户端 `/mcp` 重连 → `list_capabilities()` 应见 `vision`(enabled,3 工具)。
  - human_browser 开真实 Chrome 到一个有「登录/Login」按钮的页 → `vision_locate("登录")` 核对 center 落在按钮上 → `vision_tap("登录")` 端到端点中。
  - 一个 Electron app(如 VS Code)对 a11y 拿不到的 web 视图元素重复一次。

- [ ] **Step 4: code-reviewer 审 + 修复复验**（章程质量门禁:实现后派 code-reviewer,过了再合并）。

- [ ] **Step 5: Commit + 合并**（按章程,合并/推送前与用户确认）
```bash
git add docs/architecture.md
git commit -m "docs(vision): register tools in architecture.md"
```

---

## 自检(写完对照 spec)

- **Spec 覆盖**:§4 三工具→Task 8/9/10;§5.1 注入破循环→Task 12;§5.2 单例+锁→Task 6;§5.3 子行定位→Task 3;§7 错误/ocr_sample→Task 8/9;§8 单测(含并发)→Task 6;§9 文件清单→Task 11/12/13/14;B1→Task 11;B2 region 格式→Task 2/4/8;B3 锁→Task 6;B4 注入→Task 7/12。✓
- **类型一致**:OCR 归一项 `{text,box:[x,y,w,h],conf}`、候选 `{text,center,box,score,match_field,on_screen}`、region `(l,t,r,b)`——全 plan 统一。✓
- **无占位**:每步含完整代码/命令/期望。✓

## 已知实现注意
- 测试 import 路径用 `platforms.common.capabilities.vision...`;跑 pytest 需在 repo 根、`PYTHONPATH=.`(或 `cd` 到根)。若现有 common 测试用别的 import 根,按其约定对齐。
- win server 的截屏/点击实现可能与 mac 不同(pywin/pyautogui),Task 12 Step 3 按 win 实际实现抽 helper,不要照抄 mac。
- 子行定位对 CJK 等宽近似、英文比例近似,够点击用;超长/跨行 query 降级整行中心。
- 真机首次 OCR 冷启含模型载入(~数百 ms);server 进程内单例,后续快。
