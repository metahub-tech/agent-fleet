"""截图坐标几何纯函数(平台无关)。

`resize_to_tap_space`: 把物理像素截图规整到 tap 坐标空间的逻辑尺寸。
mac(Retina) 上截图是物理像素、点击是逻辑点, 需 resize 回逻辑; win 上截图==tap
(物理), target 恒等于原尺寸 → 恒等返回。此函数是两端 `_capture_in_tap_space`
原语里"按 target 归一"那一步的唯一实现(spec §4.2)。
"""
from __future__ import annotations


def resize_to_tap_space(img, target):
    """img=PIL.Image(物理像素), target=(w,h) tap 空间逻辑尺寸。
    尺寸不同 → LANCZOS resize; 相同 → 恒等返回(不重编码)。纯函数、只用 img.size/img.resize。"""
    if tuple(img.size) == tuple(target):
        return img
    from PIL import Image as _PILImage
    return img.resize(tuple(target), _PILImage.LANCZOS)
