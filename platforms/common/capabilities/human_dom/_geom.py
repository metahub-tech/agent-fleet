"""视口坐标(CSS px) → 屏幕坐标(point 空间, 与 take_screenshot/tap 同空间)。
mac: window.screenX/Y 与 getBoundingClientRect 同在 CSS px, OS 点空间 1:1, 不乘 dpr。
top_chrome_px 后续真机标定; 默认 outerH-innerH。"""
from __future__ import annotations


def top_chrome_px(geom: dict) -> float:
    return float(geom["outerH"]) - float(geom["innerH"])


def viewport_to_screen(rect: dict, geom: dict) -> dict:
    ox = float(geom["screenX"])
    oy = float(geom["screenY"]) + top_chrome_px(geom)
    sl = ox + float(rect["left"]); st = oy + float(rect["top"])
    w = float(rect["width"]); h = float(rect["height"])
    return {"center": [sl + w / 2, st + h / 2], "box": [sl, st, rect["width"], rect["height"]]}
