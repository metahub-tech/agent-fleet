"""在已截好的 PNG 上画确定性标记(纯 PIL, 平台无关)。R5 hover-verify 用: 把 tap 落点 (x,y)
画成醒目十字+外圈, 直接可视化"这一点会不会落在目标上"。不依赖光标捕获(截图本就不含硬件光标)。"""
from __future__ import annotations
import io


def draw_crosshair(png_bytes: bytes, x: int, y: int, size: int = 20,
                   color=(255, 0, 255), width: int = 3) -> bytes:
    """在 png 的 (x,y) 画十字 + 外圈(默认洋红), 返回新 png bytes。
    x,y 越界 → clamp 到图内, 绝不抛。纯函数、只用 PIL。"""
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    cx = max(0, min(w - 1, int(x)))
    cy = max(0, min(h - 1, int(y)))
    d = ImageDraw.Draw(img)
    r = int(size)
    d.line([(cx - r, cy), (cx + r, cy)], fill=color, width=width)            # 横
    d.line([(cx, cy - r), (cx, cy + r)], fill=color, width=width)            # 竖
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)  # 外圈
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
