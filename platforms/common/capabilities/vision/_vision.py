from __future__ import annotations
import base64
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
