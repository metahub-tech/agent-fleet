"""跨平台上传支撑 helper（Android / iOS / 后续 Win/Mac 都可共用的纯逻辑）。

设计：
- docs/internal/design/2026-05-28-android-agent-file-upload-design.md
- docs/internal/design/2026-05-30-ios-agent-file-upload-design.md

不引入 platform 特定逻辑（adb、pymobiledevice3、WDA），保持可单测且无外部依赖。
"""
from __future__ import annotations

import base64
import ipaddress
import socket
import urllib.parse
import urllib.request
from pathlib import Path

UPLOADS_DIR = Path.home() / ".agent-fleet" / "uploads"
URL_HARD_MAX = 200 * 1024 * 1024  # 任何 url 下载硬上限

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}

# 通用最小注入字符集（双引号/反引号/分号/$/反斜线/换行）。各平台可在自己模块按需扩展
# （Android 还需补单引号防 MediaStore SQL 注入）。
_FORBIDDEN_PATH_CHARS_BASE = set("\"`;$\n\r")


class UploadError(ValueError):
    """入参/校验错误，工具层转成 {ok: false, error}。"""


def ensure_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
