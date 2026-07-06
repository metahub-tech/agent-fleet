# R1 vision 坐标系确定性校正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「vision 截图坐标空间 ≡ tap 坐标空间」从两条隐式约定做成显式、单入口、启动即断言的硬不变量，并堵死 Windows DPI awareness 的静默失效——让缩放屏上 `vision_locate→tap` 零 agent 精确命中。

**Architecture:** 三组件（对应 spec §4）：① 焊死 win DPI awareness（提前置位 + 接返回值 + 可观测）；② 每端收敛单一 `_capture_in_tap_space()` 原语（`take_screenshot` 与 vision 注入都调它，灭 mac 两份 grab→resize 漂移）；③ 暴露 `scale_factor`/`dpi_aware`（零新依赖，仅自检/上报，**绝不进坐标运算**）。**红线：任何时候不得对 vision 输出/tap 坐标乘除 scale**（单主屏上 center 已在 tap 空间，再乘除会双重校正）。

**Tech Stack:** Python 3.10+，FastMCP，PIL/Pillow（截图/resize），pyautogui（点击/尺寸），ctypes.windll（win DPI），pyobjc AppKit NSScreen（mac scale）；pytest。

**Spec:** `docs/superpowers/specs/2026-07-06-vision-coordinate-calibration-design.md`（architect 已审，2 BLOCKING 已修）。

**测试现实（重要）:** `platforms/common/tests` 不进 CI required；win/mac server 顶层 import pyautogui/pywinauto，**Linux 上 import 即失败**。故：
- **Phase A** 纯函数 → 本机（Linux dev box，PIL 12.2 + pytest 9 已装，numpy 缺不影响）**可跑 TDD**。
- **Phase B** server 编辑 → 本机只能 `py_compile` 验语法；功能验证在 Phase C host。
- **Phase C** on-host smoke + 真机 150% 验收 → **改共享测试机缩放，须用户在场**（用户明确要求，走到这步先约时机）。

---

## 文件结构（决策锁定）

**新建**
- `platforms/common/_capture_geom.py` — 纯函数 `resize_to_tap_space(img, target)`（物理截图 → tap 空间逻辑尺寸；平台无关，两端 server + 测试共用）。
- `platforms/common/tests/test_capture_tap_space.py` — resize 纯函数单测（PIL，本机跑）。
- `platforms/common/tests/test_dpi_scale.py` — win `_dpi_to_scale`/`_ensure_dpi_awareness`/`dpi_awareness_report`/`read_scale_factor` + mac `read_scale_factor` 纯函数单测（本机跑）。
- `platforms/macos/server/mac_dpi.py` — mac `read_scale_factor()`（NSScreen backingScaleFactor，惰性 import AppKit，失败降级 1.0）。

**修改**
- `platforms/windows/server/win_input.py` — 加 `_dpi_to_scale` / `read_scale_factor` / `dpi_awareness_report`（纯/惰性，Linux 可导入可测）。
- `platforms/windows/server/win_device_mcp.py` — awareness 提前置位；单一 `_capture_in_tap_space`；`get_screen_size`/`get_status` 加字段；vision 注入改 capture_fn。
- `platforms/macos/server/mac_device_mcp.py` — 单一 `_capture_in_tap_space`（收敛 grab→wake→resize）；`get_screen_size` 加 scale_factor；vision 注入改 capture_fn。
- `CHANGELOG.md` — Unreleased 记一条。

**不动:** OCR/子行/模板算法、element-action 逻辑、android/ios、human_dom、vision 模块内部（capture_fn 语义/返回结构不变）。

---

## Task 0: 建实现分支

- [ ] **Step 1: 从最新 main 建分支**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git checkout main && git pull
git checkout -b feat/vision-coordinate-calibration-r1
```

---

## Phase A — 平台无关纯函数（本机 TDD）

### Task 1: `resize_to_tap_space` 纯函数

**Files:**
- Create: `platforms/common/_capture_geom.py`
- Test: `platforms/common/tests/test_capture_tap_space.py`

- [ ] **Step 1: 写失败测试**

```python
# platforms/common/tests/test_capture_tap_space.py
"""resize_to_tap_space 纯函数单测(PIL, 平台无关, 本机可跑; 非 CI)。"""
from _capture_geom import resize_to_tap_space
from PIL import Image


def test_resize_downscales_physical_to_logical():
    # Retina/150%: 物理 2880x1800 → tap 空间逻辑 1440x900
    img = Image.new("RGB", (2880, 1800))
    out = resize_to_tap_space(img, (1440, 900))
    assert out.size == (1440, 900)


def test_resize_identity_when_already_tap_space():
    # 尺寸已等于 target(如 win 物理==tap): 恒等返回, 不重新编码
    img = Image.new("RGB", (1440, 900))
    out = resize_to_tap_space(img, (1440, 900))
    assert out is img


def test_resize_accepts_list_or_tuple_target():
    img = Image.new("RGB", (200, 100))
    assert resize_to_tap_space(img, [100, 50]).size == (100, 50)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python -m pytest tests/test_capture_tap_space.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_capture_geom'`

- [ ] **Step 3: 写最小实现**

```python
# platforms/common/_capture_geom.py
"""截图坐标几何纯函数(平台无关)。

`resize_to_tap_space`: 把物理像素截图规整到 tap 坐标空间的逻辑尺寸。
mac(Retina) 上截图是物理像素、点击是逻辑点, 需 resize 回逻辑; win 上截图==tap
(物理), target 恒等于原尺寸 → 恒等返回。此函数是两端 `_capture_in_tap_space`
原语里"按 target 归一"那一步的唯一实现(spec §4.2)。
"""
from __future__ import annotations


def resize_to_tap_space(img, target):
    """img=PIL.Image(物理像素), target=(w,h) tap 空间逻辑尺寸。
    尺寸不同 → LANCZOS resize; 相同 → 恒等返回(不重编码)。纯函数、只用 img.size/img.resize。"""
    if tuple(img.size) == tuple(target):
        return img
    from PIL import Image as _PILImage
    return img.resize(tuple(target), _PILImage.LANCZOS)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python -m pytest tests/test_capture_tap_space.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add platforms/common/_capture_geom.py platforms/common/tests/test_capture_tap_space.py
git commit -m "feat(vision-r1): resize_to_tap_space 纯函数(截图→tap 空间归一, 单一实现)"
```

---

### Task 2: win DPI 纯函数（scale 换算 + awareness 报告）

**Files:**
- Modify: `platforms/windows/server/win_input.py`（在文件末尾 `_ensure_dpi_awareness` 之后追加）
- Test: `platforms/common/tests/test_dpi_scale.py`

- [ ] **Step 1: 写失败测试**

```python
# platforms/common/tests/test_dpi_scale.py
"""win/mac DPI 纯函数单测(惰性 import, 平台无关, 本机可跑; 非 CI)。"""
import platform
import sys
from pathlib import Path

# win_input 在 platforms/windows/server, 无重依赖、Linux 可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "windows" / "server"))
import win_input


def test_dpi_to_scale_common_ratios():
    assert win_input._dpi_to_scale(96) == 1.0
    assert win_input._dpi_to_scale(120) == 1.25
    assert win_input._dpi_to_scale(144) == 1.5
    assert win_input._dpi_to_scale(192) == 2.0


def test_dpi_to_scale_bad_input_defaults_to_1():
    assert win_input._dpi_to_scale(0) == 1.0
    assert win_input._dpi_to_scale(-5) == 1.0
    assert win_input._dpi_to_scale(None) == 1.0


def test_ensure_dpi_awareness_returns_bool_and_false_off_windows():
    r = win_input._ensure_dpi_awareness()
    assert isinstance(r, bool)
    if platform.system() != "Windows":
        assert r is False  # 无 ctypes.windll → 三级全失败 → 优雅 False


def test_dpi_awareness_report_text():
    assert win_input.dpi_awareness_report(True) is None
    msg = win_input.dpi_awareness_report(False)
    assert msg and "漂移" in msg


def test_read_scale_factor_fallback_off_windows():
    # 无 windll → 优雅降级 1.0, 不抛
    assert win_input.read_scale_factor() == 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python -m pytest tests/test_dpi_scale.py -v`
Expected: FAIL — `AttributeError: module 'win_input' has no attribute '_dpi_to_scale'`

- [ ] **Step 3: 写最小实现**（追加到 `win_input.py` 末尾）

```python
def _dpi_to_scale(dpi) -> float:
    """DPI(96=100%) → 显示缩放倍率。dpi 非正/None 视为读取失败 → 1.0。纯函数、可测。"""
    if not dpi or dpi <= 0:
        return 1.0
    return round(dpi / 96.0, 4)


def read_scale_factor() -> float:
    """主屏 OS 显示缩放(1.0/1.25/1.5…)。读不到降级 1.0, 绝不抛。
    仅供自检/诚实上报, 【绝不进 tap 坐标运算】——awareness 生效时截图↔tap 比值恒 1.0,
    与本值(OS 显示缩放)无关(spec §4.3 红线)。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        shcore = ctypes.windll.shcore
        hmon = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        # MDT_EFFECTIVE_DPI=0; 成功返回 S_OK(0)
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            return _dpi_to_scale(dx.value)
    except Exception:
        pass
    return 1.0


def dpi_awareness_report(aware: bool):
    """awareness 失败时的 stderr 告警文案(成功→None)。纯函数、可测。"""
    if aware:
        return None
    return ("[dpi] per-monitor DPI awareness 设置失败; 缩放≠100% 屏上截图与 tap 坐标将错位、"
            "视觉点击漂移。请确认 Win10 1703+ 且进程有权限。")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python -m pytest tests/test_dpi_scale.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add platforms/windows/server/win_input.py platforms/common/tests/test_dpi_scale.py
git commit -m "feat(vision-r1): win_input 加 _dpi_to_scale/read_scale_factor/dpi_awareness_report 纯函数"
```

---

### Task 3: mac `read_scale_factor`

**Files:**
- Create: `platforms/macos/server/mac_dpi.py`
- Test: 追加到 `platforms/common/tests/test_dpi_scale.py`

- [ ] **Step 1: 追加失败测试**（`test_dpi_scale.py` 末尾）

```python
# --- mac ---
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macos" / "server"))
import mac_dpi


def test_mac_read_scale_factor_fallback_off_mac():
    # 无 AppKit(非 mac) → 优雅降级 1.0, 不抛
    assert mac_dpi.read_scale_factor() == 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && python -m pytest tests/test_dpi_scale.py::test_mac_read_scale_factor_fallback_off_mac -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mac_dpi'`

- [ ] **Step 3: 写最小实现**

```python
# platforms/macos/server/mac_dpi.py
"""mac 主屏显示缩放读取(供自检/诚实上报, 不进坐标运算)。

AppKit 惰性 import → 本模块可在非 mac 导入(纯函数单测), 读不到降级 1.0。
mac 上 ImageGrab 抓 backing store(= backingScaleFactor × 逻辑), take_screenshot
resize 回逻辑, 故 backingScaleFactor 恰 = 物理 grab 尺寸÷逻辑尺寸(spec §4.3)。
"""
from __future__ import annotations


def read_scale_factor() -> float:
    """主屏 backingScaleFactor(Retina 通常 2.0, 非 Retina 1.0)。读不到降级 1.0, 绝不抛。"""
    try:
        from AppKit import NSScreen
        s = NSScreen.mainScreen()
        if s is not None:
            return round(float(s.backingScaleFactor()), 4)
    except Exception:
        pass
    return 1.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && python -m pytest tests/test_dpi_scale.py -v`
Expected: PASS（6 passed 总计）

- [ ] **Step 5: 提交**

```bash
git add platforms/macos/server/mac_dpi.py platforms/common/tests/test_dpi_scale.py
git commit -m "feat(vision-r1): mac_dpi.read_scale_factor(NSScreen backingScaleFactor, 降级 1.0)"
```

---

## Phase B — server 集成编辑（本机 py_compile 验语法；功能验证在 Phase C host）

> 每个 Task 收尾用 `python -m py_compile <file>` 验语法（本机可跑，不 import 第三方 GUI 库）。功能行为在 Phase C on-host smoke 验。

### Task 4: 焊死 win DPI awareness（提前置位 + 接返回值 + 告警）

**Files:**
- Modify: `platforms/windows/server/win_device_mcp.py:32-49`（顶部 import 区）

- [ ] **Step 1: 提前置位 + 接返回值**

在 `win_device_mcp.py` 顶部，**`import pyautogui`（现 :34）之前**（即 `from typing import ...` 之后）插入：

```python
# per-monitor DPI awareness 必须在 pyautogui / PIL / pywinauto 之前置位:
# 这些库 import 时会锁定进程 DPI 模式, 之后再置可能【静默失败】→ 缩放屏视觉点击漂移
# (AgentHub #100 轮3 (1347,82) vs (1893,115))。这里接返回值并可观测, 不再裸调丢弃。
from win_input import _ensure_dpi_awareness as _boot_dpi_awareness, dpi_awareness_report
_DPI_AWARE = _boot_dpi_awareness()
_dpi_warn = dpi_awareness_report(_DPI_AWARE)
if _dpi_warn:
    print(_dpi_warn, file=sys.stderr)
```

（`sys` 已在 :30 导入；`win_input` 无重依赖、可在此点安全 import。）

- [ ] **Step 2: 删除原裸调**

删除现 `win_device_mcp.py:47-49` 的注释块 + 裸调：

```python
# 进程尽早设为 per-monitor DPI aware: 否则 DPI 缩放≠100% 机器上 take_screenshot(物理像素)与
# tap/get_screen_size(逻辑像素)坐标系错位, 视觉点击漂移(AgentHub #100 P1-A)。幂等、失败不阻断。
_ensure_dpi_awareness()
```

并把现 :45 的 `from win_input import _ensure_dpi_awareness, _send_unicode, maximize_chrome_window_for_udd` 改为（去掉已在顶部导入的 `_ensure_dpi_awareness`）：

```python
from win_input import _send_unicode, maximize_chrome_window_for_udd
```

- [ ] **Step 3: 验语法**

Run: `cd platforms/windows/server && python -m py_compile win_device_mcp.py && echo OK`
Expected: OK（无 SyntaxError）

- [ ] **Step 4: 提交**

```bash
git add platforms/windows/server/win_device_mcp.py
git commit -m "fix(vision-r1): win DPI awareness 提前置位(pyautogui import 前)+接返回值+失败告警, 堵静默漂移"
```

---

### Task 5: win 单一 `_capture_in_tap_space` 原语

**Files:**
- Modify: `platforms/windows/server/win_device_mcp.py`（take_screenshot :155-167；`_capture_logical_png` :959-964；vision 注入 :996）

- [ ] **Step 1: 定义单一原语**

在 `get_screen_size`（:145-152）之后、`take_screenshot` 之前插入：

```python
def _capture_in_tap_space(region=None) -> bytes:
    """截屏 → PNG bytes, 【恒在 tap 坐标空间】。win: 进程 per-monitor DPI aware, ImageGrab 出
    物理像素 = tap(SetCursorPos)空间, 不 resize。这是本端截图的唯一真理, take_screenshot 与
    vision 注入都调它(spec §4.2)。region=(left,top,right,bottom) 恒在 tap(物理)空间。"""
    img = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 2: take_screenshot 改调原语**

把 `take_screenshot`（:157-167）的函数体改为：

```python
@mcp.tool
@with_touch
def take_screenshot(
    region: Annotated[
        Optional[tuple[int, int, int, int]],
        Field(description="(left, top, right, bottom); None = full screen"),
    ] = None,
) -> Image:
    """Capture the screen and return a PNG (in tap coordinate space)."""
    return Image(data=_capture_in_tap_space(region), format="png")
```

- [ ] **Step 3: 删 `_capture_logical_png`、vision 注入改用原语**

删除 `_capture_logical_png`（现 :959-964 整个函数），并把 vision 注入（现 :996）：

```python
_cap_registry.add(VisionCapability(capture_fn=_capture_logical_png, tap_fn=_os_tap))
```

改为：

```python
_cap_registry.add(VisionCapability(capture_fn=_capture_in_tap_space, tap_fn=_os_tap))
```

- [ ] **Step 4: 验语法**

Run: `cd platforms/windows/server && python -m py_compile win_device_mcp.py && echo OK`
Expected: OK

- [ ] **Step 5: 提交**

```bash
git add platforms/windows/server/win_device_mcp.py
git commit -m "refactor(vision-r1): win 单一 _capture_in_tap_space 原语(take_screenshot+vision 共用), 删 _capture_logical_png"
```

---

### Task 6: win `get_screen_size` / `get_status` 暴露 scale_factor + dpi_aware

**Files:**
- Modify: `platforms/windows/server/win_device_mcp.py`（get_status :134-136；get_screen_size :145-152；顶部 import win_input 加 read_scale_factor）

- [ ] **Step 1: import read_scale_factor**

把 Task 4 里那句 `from win_input import _send_unicode, maximize_chrome_window_for_udd` 补上 `read_scale_factor`：

```python
from win_input import _send_unicode, maximize_chrome_window_for_udd, read_scale_factor
```

- [ ] **Step 2: get_screen_size 加字段**

把 `get_screen_size`（:145-152）返回改为：

```python
@mcp.tool
@with_touch
def get_screen_size() -> dict:
    """Return the primary screen resolution in PHYSICAL pixels.

    Process is per-monitor DPI-aware, so this matches take_screenshot's pixel
    space and tap(x,y) coordinates exactly. `scale_factor` = OS 显示缩放(如 1.5),
    仅供自检/上报, 【不等于截图↔tap 像素比】(awareness 生效时该比值恒 1.0), 别拿它算坐标。
    `dpi_aware` = 进程是否成功 per-monitor DPI aware; false 时缩放屏坐标不可信、应降级。"""
    w, h = pyautogui.size()
    return {"width": w, "height": h,
            "scale_factor": read_scale_factor(), "dpi_aware": _DPI_AWARE}
```

- [ ] **Step 3: get_status 加 dpi_aware**

把 `get_status`（:134-136）返回改为（status() 返回 dict, post-hoc 补键）：

```python
@mcp.tool
def get_status() -> dict:
    """Show whether the Windows test machine is currently claimed and by whom.
    Also reports `dpi_aware` (per-monitor DPI awareness; false → 缩放屏视觉点击不可信)。"""
    st = _state_registry.status(_SERIAL)
    st["dpi_aware"] = _DPI_AWARE
    return st
```

- [ ] **Step 4: 验语法**

Run: `cd platforms/windows/server && python -m py_compile win_device_mcp.py && echo OK`
Expected: OK

- [ ] **Step 5: 提交**

```bash
git add platforms/windows/server/win_device_mcp.py
git commit -m "feat(vision-r1): win get_screen_size/get_status 暴露 scale_factor+dpi_aware(仅自检, 不进坐标运算)"
```

---

### Task 7: mac 单一 `_capture_in_tap_space`（收敛 grab→wake→resize）

**Files:**
- Modify: `platforms/macos/server/mac_device_mcp.py`（take_screenshot :208-245；`_capture_logical_png` :1103-1116；vision 注入 :1148；顶部加 import）

- [ ] **Step 1: import resize_to_tap_space**

在 mac server 顶部 `sys.path.insert(common)` 之后的 common import 区，加：

```python
from _capture_geom import resize_to_tap_space
```

（mac server 已 `sys.path.insert(0, common)`；`_capture_geom` 是 common 裸模块，可直接 import。放在 `import _fsops` 等旁边。）

- [ ] **Step 2: 定义单一原语**

在 `take_screenshot`（:208）之前插入（`_frame_is_black`/`_screensaver_running`/`_wake_display` 已在其上定义）：

```python
def _capture_in_tap_space(region=None) -> bytes:
    """截屏 → PNG bytes, 【恒在 tap 坐标空间】(逻辑点)。mac: ImageGrab 出物理(Retina 2x),
    pyautogui 点击用逻辑点 → 抓完 resize 回逻辑; idle 黑屏/屏保先唤醒 re-grab。这是本端截图的
    唯一真理, take_screenshot 与 vision 注入都调它(spec §4.2)。黑屏唤醒逻辑也只此一份。
    region=(left,top,right,bottom) 恒在 tap(逻辑)空间; grab 内部才落到物理, 绝不拿物理 region crop。"""
    img = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    if _frame_is_black(img) or _screensaver_running():
        _wake_display()
        time.sleep(1.5)  # 等面板唤醒 + 淡入动画结束
        img = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    target = pyautogui.size() if region is None else (region[2] - region[0], region[3] - region[1])
    img = resize_to_tap_space(img, target)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 3: take_screenshot 改薄封装**

把 `take_screenshot`（:208-245）函数体改为（docstring 保留说明）：

```python
@mcp.tool
@with_touch
def take_screenshot(
    region: Annotated[
        Optional[tuple[int, int, int, int]],
        Field(description="(left, top, right, bottom) in logical pixels; None = full screen"),
    ] = None,
) -> Image:
    """Capture the screen and return a PNG sized to LOGICAL (tap) pixels.

    On Retina, ImageGrab returns physical pixels while clicks use logical pixels;
    the shared `_capture_in_tap_space` primitive resizes to logical so screenshot
    coordinates pass directly to click(x, y). Idle black/screensaver → wake + re-grab."""
    return Image(data=_capture_in_tap_space(region), format="png")
```

- [ ] **Step 4: `_capture_logical_png` 改薄封装 + vision 注入改**

把 `_capture_logical_png`（:1103-1116）整个替换为薄封装（保留符号以防他处引用，但只转调）：

```python
def _capture_logical_png() -> bytes:
    """[保留兼容] 全屏截图 → tap 空间 PNG bytes。实现收敛到 _capture_in_tap_space。"""
    return _capture_in_tap_space()
```

并把 vision 注入（:1148）改为直接用原语：

```python
_cap_registry.add(VisionCapability(capture_fn=_capture_in_tap_space, tap_fn=_os_tap))
```

> 说明：删 `_capture_logical_png` 亦可，但保留薄封装零风险（若无他处引用，可在 code-review 时删）。关键是**实现只剩一份**。

- [ ] **Step 5: 验语法**

Run: `cd platforms/macos/server && python -m py_compile mac_device_mcp.py && echo OK`
Expected: OK

- [ ] **Step 6: 提交**

```bash
git add platforms/macos/server/mac_device_mcp.py
git commit -m "refactor(vision-r1): mac 单一 _capture_in_tap_space 原语(收敛两份 grab→wake→resize), vision 共用"
```

---

### Task 8: mac `get_screen_size` 暴露 scale_factor

**Files:**
- Modify: `platforms/macos/server/mac_device_mcp.py`（顶部加 import mac_dpi；get_screen_size :147-150）

- [ ] **Step 1: import read_scale_factor**

mac server 顶部（mac_dpi 与 mac server 同目录，脚本目录在 sys.path[0]）加：

```python
from mac_dpi import read_scale_factor
```

- [ ] **Step 2: get_screen_size 加字段**

把 `get_screen_size`（:147-150）改为：

```python
@mcp.tool
@with_touch
def get_screen_size() -> dict:
    """Return the primary screen resolution (logical/tap pixels).
    `scale_factor` = 主屏 backingScaleFactor(Retina 2.0), 仅供自检/上报, 不进坐标运算。"""
    w, h = pyautogui.size()
    return {"width": w, "height": h, "scale_factor": read_scale_factor()}
```

- [ ] **Step 3: 验语法**

Run: `cd platforms/macos/server && python -m py_compile mac_device_mcp.py && echo OK`
Expected: OK

- [ ] **Step 4: 提交**

```bash
git add platforms/macos/server/mac_device_mcp.py
git commit -m "feat(vision-r1): mac get_screen_size 暴露 scale_factor(backingScaleFactor, 仅自检)"
```

---

### Task 9: CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（`## [Unreleased]` 下）

- [ ] **Step 1: 加条目**

在 `## [Unreleased]` 的 `### 修复` / `### 变更`（无则新建 `### 修复`）下加：

```markdown
- **vision 坐标系确定性校正(R1, AgentHub #100 目标3)**: 把「截图坐标空间≡tap 空间」做成显式硬不变量。
  ① win DPI awareness 提前置位(pyautogui import 前)+接返回值+失败告警, 堵静默漂移((1347,82)/(1893,115));
  ② 每端收敛单一 `_capture_in_tap_space` 原语(灭 mac 两份 grab→resize);
  ③ `get_screen_size`/`get_status` 暴露 `scale_factor`/`dpi_aware`(仅自检/上报, 不进坐标运算)。
  vision 输出/tap 坐标不做任何 scale 乘除(单主屏 center 已在 tap 空间)。awareness 失效兜底交 R2。
```

- [ ] **Step 2: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(vision-r1): CHANGELOG 记坐标系确定性校正"
```

---

## Phase C — on-host smoke + 真机验收（用户在场；改共享机缩放前约时机）

> **停止点**：Phase A/B 完成后**先回用户**报告：本机纯函数单测结果 + Phase B 已落 + 待真机验收。真机验收改 test-win11/macmini 缩放，**等用户在场一起跑**（用户明确要求）。以下为验收清单，实现者到这步照做。

### Task 10: on-host smoke（单入口不分叉 + awareness 锚点）

**Files:**
- Modify: `platforms/windows/tests/test_win_server.py`、`platforms/macos/tests/test_mac_server.py`（host-only, 只在对应真机跑）

- [ ] **Step 1: 单入口不分叉断言（两端各一）**

思路（host 上 import server 后）：
1. **注入身份**：断言 vision 模块拿到的 `capture_fn` **就是** server 的 `_capture_in_tap_space`（同一函数对象）——
   `assert mod._cap_registry._modules["vision"]._capture_fn is mod._capture_in_tap_space`。
2. **委派证明**：monkeypatch `mod._capture_in_tap_space` 为返回哨兵 bytes 的桩 → 调 `take_screenshot()` → 断言返回哨兵 → 证明 `take_screenshot` 确实委派给单一原语、未各写一份 grab。

```python
def test_screenshot_and_vision_share_single_capture_primitive(monkeypatch):
    import win_device_mcp as mod  # mac 上换 mac_device_mcp
    vis = mod._cap_registry._modules["vision"]
    assert vis._capture_fn is mod._capture_in_tap_space  # 注入即单一原语
    SENT = b"\x89PNG-sentinel"
    monkeypatch.setattr(mod, "_capture_in_tap_space", lambda region=None: SENT)
    out = mod.take_screenshot.fn()  # 取被 @mcp.tool 包装的原函数; 若无 .fn 用等价入口
    assert getattr(out, "data", out) == SENT  # take_screenshot 委派给单一原语
```

> 注：`@mcp.tool` 包装后取原函数的方式按 FastMCP 版本调整（`.fn` / `.__wrapped__` / 直接调 registry）。实现者在 host 上按实际 API 落地断言，核心是证明 ①注入身份 ②take_screenshot 委派。

- [ ] **Step 2: win awareness 正向锚点 + 失效路径**

```python
def test_dpi_aware_reported_in_screen_size():
    import win_device_mcp as mod
    ss = mod.get_screen_size.fn()
    assert "dpi_aware" in ss and "scale_factor" in ss
    # 真机(Win10 1703+): 期望 True
    assert ss["dpi_aware"] is True

def test_dpi_awareness_report_warns_on_false():
    import win_input
    assert win_input.dpi_awareness_report(False)  # 有告警文案
```

- [ ] **Step 3: host 上跑**

Run（各真机）: `pytest platforms/windows/tests/test_win_server.py -v` / `pytest platforms/macos/tests/test_mac_server.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add platforms/windows/tests/test_win_server.py platforms/macos/tests/test_mac_server.py
git commit -m "test(vision-r1): on-host smoke — 单入口不分叉 + awareness 锚点(host-only)"
```

### Task 11: 真机 150% DPI 验收 + 共享 tap 面回归（用户在场）

- [ ] **Step 1: 落地第一步——test-win11 awareness 现状实测（定性）**

用户在场，MCP `win-device`：`get_status`/`get_screen_size` 读 `dpi_aware`。**记录当前(未改代码前部署) awareness true/false**，定性 R1 是「修活 bug」还是「加保险」（spec §1.3-1 张力）。部署本分支后复测仍 `true`。

- [ ] **Step 2: test-win11 设 150% 缩放，验 vision→tap 命中**

- `get_screen_size` → `dpi_aware:true` + `scale_factor:1.5` + width/height 为物理像素。
- human_browser 开真实 Chrome，`vision_locate(已知网页文字)` → 拿 center → `tap` → **个位数 px 命中目标中心**（截图核对）。

- [ ] **Step 3: macmini（Retina/缩放）验证**

- 先唤醒屏幕（`memory/reference-macmini-display-idle-sleep`：caffeinate -u / 模拟输入），避免抓壁纸。
- `get_screen_size` → 截图尺寸 == width/height（逻辑）+ `scale_factor` == backingScaleFactor。
- `vision_locate→tap` 命中。

- [ ] **Step 4: 共享 tap 面回归（必做, spec §5.3 N4）**

awareness/capture 重排是进程级改动, `_os_tap` 被三家共用。在真机复测：
- `tap_element`（element-action）点中已知控件；
- `human_dom_tap` 点中已知 DOM 元素；
- `vision_tap` 点中。
三家都准 → 无回归。

- [ ] **Step 5: 记录验收结论**回用户（含 Step 1 的 awareness 定性结论）。

---

## 质量门禁与收口（charter）

- [ ] **code-reviewer 审**：Phase A/B 落完，派 code-reviewer subagent 审全 diff（重点核红线：无任何对 vision/tap 坐标的 scale 乘除；单入口无残留第二份 capture；awareness 提前置位未破坏其它 import）。发现问题先修复复验。
- [ ] **真机验收通过**（Task 11，用户在场）。
- [ ] **合并 + tag**：审过 + 真机过 → squash-merge PR → 打 `v0.8.x-alpha` annotated tag → GitHub Release(prerelease=true)。**合并/发版前与用户确认**（charter 不可逆/外发条款）。

---

## Self-Review（写完计划的自查）

- **Spec 覆盖**：R1 三组件 → Task 4(awareness)/5·7(单原语)/6·8(暴露 scale)；纯函数抽取 → Task 1/2/3；测试三层(纯函数/on-host/真机) → Phase A / Task 10 / Task 11；红线「不乘除 scale」→ 全程未加除法层 + code-review 核；awareness 失效残差裁决(交 R2) → 不在本计划实现(spec §1.6 已定, 仅暴露 dpi_aware)。✓
- **占位扫描**：无 TBD；Task 10 的 `@mcp.tool` 取原函数方式标注了「按 FastMCP 版本调整」——这是真机上确定 API 的合理留口，非空泛占位。
- **类型/命名一致**：`_capture_in_tap_space(region=None)->bytes`、`resize_to_tap_space(img,target)`、`read_scale_factor()->float`、`_dpi_to_scale(dpi)->float`、`dpi_awareness_report(bool)`、`_DPI_AWARE` 全计划一致。
