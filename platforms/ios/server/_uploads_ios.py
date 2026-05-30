"""iOS agent→设备 上传支撑（共享 helper from _upload_common；iOS 专属逻辑）。

设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md
计划：docs/internal/plans/2026-05-30-ios-agent-file-upload.md

不在导入期触碰 pymobiledevice3/WDA/网络；副作用经参数注入或显式调用。
"""
from __future__ import annotations

from pathlib import Path

import httpx

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


# ============================================================
#                    WDA HTTP CLIENT
# ============================================================

def _new_wda_client(port: int = WDA_DEFAULT_PORT,
                    timeout: int = PHOTOS_TIMEOUT_SECS) -> httpx.Client:
    """tests 可 monkeypatch 这个函数注入 MockTransport client。"""
    return httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=timeout)


def wda_photos_import(body: bytes, filename: str, ttype: str,
                      port: int = WDA_DEFAULT_PORT) -> dict:
    """POST JSON {file_b64,filename,type} 到 WDA /wda/photos/import；返回 {ok, asset_id?, error?, hint?}。

    WDA 13.x 的 FBRouteRequest 只暴露 arguments（JSON 解析后的 body），没有
    raw body / headers API —— 因此 mac→WDA 走 JSON+base64（不是 raw body）。
    base64 ~33% 膨胀对于 4.4MB 图片→5.9MB 完全可接受；mac→WDA 全在 127.0.0.1。

    WDA 端 handler：base64 decode → 写 NSTemp → PHPhotoLibrary.performChanges
    （dispatch_semaphore 等 completion，30s 超时）→ 删 NSTemp → 返回 JSON。
    """
    import base64
    payload = {
        "file_b64": base64.b64encode(body).decode("ascii"),
        "filename": filename,
        "type": ttype,
    }
    try:
        with _new_wda_client(port=port) as client:
            r = client.post("/wda/photos/import", json=payload)
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": f"WDA non-JSON response ({r.status_code}): {r.text[:200]}"}
        # WDA 失败时通常 5xx + ok=false；2xx + ok=true。透传 WDA 的 error。
        if r.status_code >= 400 and "ok" not in data:
            return {"ok": False, "error": f"WDA HTTP {r.status_code}: {data}"}
        return data
    except httpx.TimeoutException as e:
        return {"ok": False, "error": f"WDA HTTP timeout: {e}"}
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "error": f"WDA HTTP error: {type(e).__name__}: {e}",
            "hint": "WDA daemon 未跑或端口未通：检查 launchctl list | grep wda、go-ios tunnel；"
                    "首次相册写入需在设备 设置→隐私→照片→WebDriverAgent→添加照片 中允许。",
        }


# ============================================================
#                    AFC PUSH（target=app）
# ============================================================

def afc_push_to_app(udid: str, bundle_id: str, documents_only: bool,
                    host_path: str, device_relpath: str, *, afc_op) -> dict:
    """注入式 wrapper：生产里 afc_op = ios_device_mcp._afc_op；tests 里 stub。

    afc_op(udid, bundle_id, documents_only, coroutine_factory) —— ios_device_mcp 已有该签名，
    coroutine_factory 接受 house_arrest 客户端 ha 并返回 await-able。
    """
    try:
        async def op(ha):
            await ha.push(host_path, device_relpath)
        afc_op(udid, bundle_id, documents_only, op)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "目标 app 需 UIFileSharingEnabled（documents_only=True）或 dev-signed 容器访问；"
                    "若是 WDA runner，注意它没 UIFileSharingEnabled，photos 路径应用 wda_photos_import。",
        }
    return {"ok": True}
