---
name: using-vision
description: Use when an element you need to click is NOT in the OS accessibility tree — web pages, canvas, Electron/Flutter apps, games — so find_elements/tap_element return nothing. Provides pixel-level location by visible text (OCR) or by icon image (template match), returning coordinates in the same space as tap. mac/win (pc-device) only.
---

# Using vision (像素级元素定位)

`vision` 是 pc-device(mac-device / win-device)的能力模块,补 **element-action 的盲区**:`find_elements`/`tap_element` 走 OS 无障碍树(AX/UIA),但**网页、canvas、Electron(关 a11y)、Flutter、游戏**的内容不在树里 → 它们返回空。这时用 vision 按**像素**定位。

## 何时用 vision(决策)

```
要点一个元素
  │
  ├─ 原生 app 控件? → 先 find_elements / tap_element(AX/UIA,更准更省,抗布局漂移)
  │
  └─ 网页 / canvas / Electron / Flutter / 游戏(a11y 树拿不到)?
        → vision_locate / vision_tap(像素,本节)
```

**不要**一上来就 vision。无障碍树能拿到就用 element-action。vision 是树失效时的 fallback。

## 三个工具

坐标都和 core `tap` 同一点空间——定位完直接能点。

### vision_locate(query) — 按可见文字定位
```
vision_locate("登录")
→ {"ok": true, "count": 2, "candidates": [
     {"text": "登录", "center": [1200, 29], "box": [...], "score": 1.0, "match_field": "exact"}, ...]}
```
- 返回排序候选(exact > 前缀 > 包含)。先 locate 看清候选,再决定点哪个。
- `region=(left, top, right, bottom)`:只搜这块区域(**强烈建议**——密集页全屏 OCR ~1–2s,裁剪到亚秒)。
- 没找到 → `count:0` + `ocr_sample`(当时读到的文本),据此换词/缩 region。

### vision_tap(query) — 找到即点
```
vision_tap("登录")                  # 唯一/exact 命中 → 直接点
vision_tap("hide", nth=2)           # 多命中时 nth(0-based)指定第几个
vision_tap("提交", region=(300,500,460,560))
```
- `nth`:**0-based**(0=最优候选);**省略=自动**(唯一或 exact 即点;多个歧义则不点、返回候选让你加 nth 或更具体的 query)。与 `tap_element` 同语义。
- 歧义返回 `{"ok": false, "error": "ambiguous", "candidates": [...]}` → 传 nth。

### vision_locate_image(template) — 按图标图定位(无字元素)
```
vision_locate_image(template_b64="<截图的 base64>")
vision_locate_image(template_path="/path/on/host/icon.png", threshold=0.9)
→ {"ok": true, "found": true, "center": [x, y], "score": 0.97}
```
- 给一张图标/按钮的小图,返回它在屏上的中心。用于**没有文字**的纯图标按钮(工具栏 icon 等)。
- **单尺度**:模板必须按**当前显示缩放**截取;跨 DPI/缩放会掉置信度(`found:false` + best_score + hint)。

## 红线 / 边界(重要)

- **vision 只管「定位」,不是全屏 OCR、不负责「读懂页面」。** 要理解页面内容、读低对比的次要文字(灰色元数据、说明文字),用 `take_screenshot` 交给你自己的视觉——那是你的强项,vision 的 OCR 在低对比文字上会漏。
- vision 擅长**高对比可交互元素**(按钮/链接/标题/菜单)的精确定位(~个位 px);低对比装饰文字定位不到很正常,不是 bug。
- 模板匹配跨 DPI 是已知短板(单尺度)。

## 典型流程(网页点登录)

```
1. find_elements("登录")        # web → 空(AX 树没有)
2. vision_locate("登录")        # 看候选、确认 center 落在按钮上
3. vision_tap("登录")           # 点中
```
全程 0 LLM token、离线、纯 CPU。
