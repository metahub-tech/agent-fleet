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
