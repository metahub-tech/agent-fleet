"""Unit tests for _upload_common.py (跨平台上传 helper)."""
import base64

import pytest

import _upload_common as up


# ----- Task 1: 骨架 + 常量 + UploadError + ensure_dirs -----

def test_constants_and_error():
    assert up.URL_HARD_MAX == 200 * 1024 * 1024
    assert ".jpg" in up.IMAGE_EXTS and ".png" in up.IMAGE_EXTS
    assert ".mp4" in up.VIDEO_EXTS and ".mov" in up.VIDEO_EXTS
    assert issubclass(up.UploadError, ValueError)


def test_ensure_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "uploads")
    up.ensure_dirs()
    assert (tmp_path / "uploads").is_dir()


# ----- Task 2: 校验 helper -----

def test_require_xor():
    up.require_xor("a", None, ("a", "b"))
    up.require_xor(None, "b", ("a", "b"))
    with pytest.raises(up.UploadError):
        up.require_xor("a", "b", ("a", "b"))
    with pytest.raises(up.UploadError):
        up.require_xor(None, None, ("a", "b"))


def test_decode_b64():
    assert up.decode_b64(base64.b64encode(b"hi").decode()) == b"hi"
    with pytest.raises(up.UploadError):
        up.decode_b64("not!!base64")


def test_sanitize_filename_minimal():
    assert up.sanitize_filename("bg.jpg") == "bg.jpg"
    for bad in ["", "../x", "a/b", "a\\b", "a;b", 'a"b', "a\nb"]:
        with pytest.raises(up.UploadError):
            up.sanitize_filename(bad)
    # 单引号通用 base 不禁（Android 自行扩展）
    assert up.sanitize_filename("it's.jpg") == "it's.jpg"


def test_is_image_and_video():
    assert up.is_image("a.JPG") and up.is_image("a.heic") and not up.is_image("a.mp4")
    assert up.is_video("v.MOV") and up.is_video("v.mp4") and not up.is_video("a.jpg")
