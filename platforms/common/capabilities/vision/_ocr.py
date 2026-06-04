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
        xs = [p[0] for p in box4]
        ys = [p[1] for p in box4]
        x, y = int(min(xs)), int(min(ys))
        w, h = int(max(xs) - x), int(max(ys) - y)
        out.append({"text": text, "box": [x, y, w, h], "conf": float(score)})
    return out
