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
