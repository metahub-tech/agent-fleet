# platforms/common/tests/test_vision_ocr.py
import numpy as np
import cv2
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
