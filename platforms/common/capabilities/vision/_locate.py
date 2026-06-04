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
