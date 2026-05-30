"""iOS agent→设备 上传支撑（共享 helper from _upload_common；iOS 专属逻辑）。

设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md
计划：docs/internal/plans/2026-05-30-ios-agent-file-upload.md

不在导入期触碰 pymobiledevice3/WDA/网络；副作用经参数注入或显式调用。
"""
from __future__ import annotations

from pathlib import Path

from _upload_common import (
    UploadError,
    is_image,
    is_video,
    sanitize_filename,
    _FORBIDDEN_PATH_CHARS_BASE,
)

# WDA HTTP 默认端口（go-ios tunnel forward 到 mac host）
WDA_DEFAULT_PORT = 8100
PHOTOS_TIMEOUT_SECS = 35  # WDA 内部 PHPhotoLibrary 30s + 网络余量


def validate_relpath(relpath: str) -> str:
    """app 沙盒相对路径：拒绝绝对、`..`、注入字符。"""
    if not relpath or relpath.startswith("/"):
        raise UploadError(f"非法 relpath（不能为空或绝对路径）: {relpath!r}")
    if ".." in relpath.split("/"):
        raise UploadError(f"非法 relpath（含路径穿越 ..）: {relpath!r}")
    if set(relpath) & _FORBIDDEN_PATH_CHARS_BASE:
        raise UploadError(f"relpath 含非法字符: {relpath!r}")
    return relpath


def resolve_target(target: str, filename: str | None, bundle_id: str | None,
                   relpath: str | None) -> tuple[str, dict]:
    """根据 target 校验并归一化参数。返回 (fname, params)。

    target=photos: 必须 filename，且后缀须为 IMAGE_EXTS 或 VIDEO_EXTS。params={"type":"image"|"video"}
    target=app:    必须 bundle_id + relpath；fname 取 relpath basename。params={"bundle_id","relpath"}
    """
    if target == "photos":
        if not filename:
            raise UploadError("target=photos 必须提供 filename")
        fname = sanitize_filename(filename)
        if is_image(fname):
            ttype = "image"
        elif is_video(fname):
            ttype = "video"
        else:
            raise UploadError(
                f"filename 非图片/视频后缀（应在 IMAGE_EXTS / VIDEO_EXTS 内）: {fname!r}")
        return fname, {"type": ttype}

    if target == "app":
        if not bundle_id or not relpath:
            raise UploadError("target=app 必须提供 bundle_id 与 relpath")
        rp = validate_relpath(relpath)
        fname = sanitize_filename(Path(rp).name)
        return fname, {"bundle_id": bundle_id, "relpath": rp}

    raise UploadError(f"未知 target: {target!r}（应为 photos|app）")
