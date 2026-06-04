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
