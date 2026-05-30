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


# ============================================================
#                       VALIDATION
# ============================================================

def require_xor(a, b, names: tuple[str, str]) -> None:
    if (a is None) == (b is None):
        raise UploadError(f"必须且只能提供 {names[0]} 与 {names[1]} 之一")


def decode_b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:  # noqa: BLE001
        raise UploadError(f"base64 解码失败: {e}") from e


def sanitize_filename(name: str) -> str:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise UploadError(f"非法 filename: {name!r}")
    if set(name) & _FORBIDDEN_PATH_CHARS_BASE:
        raise UploadError(f"filename 含非法字符: {name!r}")
    return name


def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS


def is_video(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXTS


# ============================================================
#                    URL / SSRF / DOWNLOAD
# ============================================================

def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved


def _is_blocked_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return any(_ip_is_blocked(sa[0]) for *_, sa in infos)


def validate_url(url: str) -> None:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UploadError(f"仅支持 http/https: {url!r}")
    if not p.hostname:
        raise UploadError(f"url 缺少 host: {url!r}")
    if _is_blocked_ip(p.hostname):
        raise UploadError(f"拒绝内网/元数据地址: {p.hostname}")


def download_url(url: str, dest: Path, max_bytes: int) -> int:
    """下载 url 到 dest，SSRF 校验 + 大小上限 + DNS 重绑定对端复验。返回字节数。"""
    validate_url(url)
    cap = min(max_bytes, URL_HARD_MAX)
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": "agent-fleet"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (scheme 已校验)
        # DNS-rebinding 防御：pre-check 与 urlopen 之间 DNS 可能被翻转，复验真实对端 IP。
        try:
            peer_ip = resp.fp.raw._sock.getpeername()[0]
        except Exception:  # noqa: BLE001
            peer_ip = None
        if peer_ip and _ip_is_blocked(peer_ip):
            raise UploadError(f"连接对端为内网/元数据地址: {peer_ip}")
        clen = resp.headers.get("Content-Length")
        if clen and int(clen) > cap:
            raise UploadError(f"文件超过上限 {cap} 字节（Content-Length={clen}）")
        with dest.open("wb") as fh:
            while True:
                buf = resp.read(64 * 1024)
                if not buf:
                    break
                written += len(buf)
                if written > cap:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise UploadError(f"下载超过上限 {cap} 字节")
                fh.write(buf)
    return written
