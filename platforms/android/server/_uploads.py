"""agent → device-host staging → phone 上传支撑逻辑（纯逻辑 + 后台 job）。

设计：docs/internal/design/2026-05-28-android-agent-file-upload-design.md
计划：docs/internal/plans/2026-05-28-android-agent-file-upload.md

不在导入期触碰 adb/网络/磁盘；副作用经参数注入或显式调用。
"""
from __future__ import annotations

import base64
import ipaddress
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

UPLOADS_DIR = Path.home() / ".agent-fleet" / "uploads"
JOBS_DIR = UPLOADS_DIR / "jobs"

SYNC_B64_MAX = 6 * 1024 * 1024           # upload_media: base64 解码后字节上限
SYNC_URL_MAX_USB = 20 * 1024 * 1024      # upload_media: USB 同步 url 上限
SYNC_URL_MAX_WIRELESS = 8 * 1024 * 1024  # upload_media: 无线同步 url 上限（保守默认）
URL_HARD_MAX = 200 * 1024 * 1024         # 任何 url 下载硬上限
MIN_FREE_BYTES = 500 * 1024 * 1024       # 暂存目录可用空间低于此值拒绝新会话/job
STAGE_TTL_SEC = 1800                     # 分片会话 30min 未收尾即可回收
JOB_TTL_SEC = 3600                       # 完成态 job 1h 后回收

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
ALLOWED_DEVICE_PREFIXES = ("/sdcard/", "/storage/emulated/0/")

# 由 android_device_mcp 在导入后注入真实 adb 路径
ADB_BIN = "adb"


class UploadError(ValueError):
    """入参/校验错误，工具层转成 {ok: false, error}。"""


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
