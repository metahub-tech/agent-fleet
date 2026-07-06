"""draw_crosshair 纯 PIL 单测(平台无关, 本机可跑; 非 CI)。"""
import io
from _marker import draw_crosshair
from PIL import Image


def _blank(w, h, color=(0, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_crosshair_marks_at_point():
    png = draw_crosshair(_blank(100, 100), 50, 50, size=10, color=(255, 0, 255), width=3)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.getpixel((50, 50)) == (255, 0, 255)   # 中心
    assert img.getpixel((45, 50)) == (255, 0, 255)   # 横线上(±size 内)
    assert img.getpixel((10, 10)) == (0, 0, 0)       # 远处仍是背景


def test_crosshair_out_of_bounds_no_crash():
    png = draw_crosshair(_blank(50, 50), 999, -5, size=8)   # 越界 → clamp, 不抛
    assert Image.open(io.BytesIO(png)).size == (50, 50)


def test_crosshair_preserves_size():
    png = draw_crosshair(_blank(120, 80), 60, 40)
    assert Image.open(io.BytesIO(png)).size == (120, 80)
