"""resize_to_tap_space 纯函数单测(PIL, 平台无关, 本机可跑; 非 CI)。"""
from _capture_geom import resize_to_tap_space
from PIL import Image


def test_resize_downscales_physical_to_logical():
    # Retina/150%: 物理 2880x1800 → tap 空间逻辑 1440x900
    img = Image.new("RGB", (2880, 1800))
    out = resize_to_tap_space(img, (1440, 900))
    assert out.size == (1440, 900)


def test_resize_identity_when_already_tap_space():
    # 尺寸已等于 target(如 win 物理==tap): 恒等返回, 不重新编码
    img = Image.new("RGB", (1440, 900))
    out = resize_to_tap_space(img, (1440, 900))
    assert out is img


def test_resize_accepts_list_or_tuple_target():
    img = Image.new("RGB", (200, 100))
    assert resize_to_tap_space(img, [100, 50]).size == (100, 50)
