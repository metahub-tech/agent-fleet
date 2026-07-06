"""mac 主屏显示缩放读取(供自检/诚实上报, 不进坐标运算)。

AppKit 惰性 import → 本模块可在非 mac 导入(纯函数单测), 读不到降级 1.0。
mac 上 ImageGrab 抓 backing store(= backingScaleFactor × 逻辑), take_screenshot
resize 回逻辑, 故 backingScaleFactor 恰 = 物理 grab 尺寸÷逻辑尺寸(spec §4.3)。
"""
from __future__ import annotations


def read_scale_factor() -> float:
    """主屏 backingScaleFactor(Retina 通常 2.0, 非 Retina 1.0)。读不到降级 1.0, 绝不抛。"""
    try:
        from AppKit import NSScreen
        s = NSScreen.mainScreen()
        if s is not None:
            return round(float(s.backingScaleFactor()), 4)
    except Exception:
        pass
    return 1.0
