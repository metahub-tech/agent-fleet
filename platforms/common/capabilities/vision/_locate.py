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
            "ocr_conf": round(float(it.get("conf", 0.0)), 3),  # R5: OCR 检测置信度(行级), 供低置信闸
            "match_field": mf,
            "on_screen": True,  # 只 OCR 可见截图, 命中即在屏
        })
    rank = {"exact": 0, "prefix": 1, "contains": 2}
    out.sort(key=lambda c: (rank[c["match_field"]], c["center"][1] // 8, c["center"][0]))
    return out[:max_results]


def sub_line_center(box, full_text: str, query: str):
    """OCR 把整行合并 → 按 query 在 full_text 里的字符比例切子框, 返回子框中心 [x,y].
    找不到 query → 整行中心 (降级)."""
    x, y, w, h = box
    cy = y + h // 2
    lt, lq = full_text.lower(), query.lower()
    i = lt.find(lq)
    n = len(lt)                               # 全在小写坐标系下算比例
    if i < 0 or n == 0:
        return [x + w // 2, cy]
    frac = (i + len(lq) / 2.0) / n            # query 跨度中点的字符比例
    return [int(x + w * frac), cy]


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
