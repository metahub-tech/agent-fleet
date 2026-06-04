# platforms/common/tests/test_vision_locate.py
import numpy as np
import cv2
from capabilities.vision import _locate


def test_decode_png_roundtrip():
    img = np.zeros((10, 20, 3), np.uint8)
    img[:, :, 2] = 255  # red
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
