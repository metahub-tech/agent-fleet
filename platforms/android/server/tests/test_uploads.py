"""Unit tests for _uploads.py (agent → device-host staging → phone 上传支撑逻辑)."""
import base64
import sys
import threading as _t
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import _uploads as up


# ----- Task 1: 骨架 + 常量 + 目录 -----

def test_constants_and_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "uploads" / "jobs")
    up.ensure_dirs()
    assert (tmp_path / "uploads" / "jobs").is_dir()
    assert up.SYNC_B64_MAX == 6 * 1024 * 1024
    assert up.MIN_FREE_BYTES == 500 * 1024 * 1024


# ----- Task 2: 校验 helper -----

def test_require_xor():
    up.require_xor("a", None, ("content_base64", "url"))       # ok
    up.require_xor(None, "b", ("content_base64", "url"))       # ok
    with pytest.raises(up.UploadError):
        up.require_xor("a", "b", ("content_base64", "url"))    # both
    with pytest.raises(up.UploadError):
        up.require_xor(None, None, ("content_base64", "url"))  # neither


def test_decode_b64():
    assert up.decode_b64(base64.b64encode(b"hi").decode()) == b"hi"
    with pytest.raises(up.UploadError):
        up.decode_b64("not!!base64")


def test_sanitize_filename():
    assert up.sanitize_filename("bg.jpg") == "bg.jpg"
    with pytest.raises(up.UploadError):
        up.sanitize_filename("../etc/passwd")
    with pytest.raises(up.UploadError):
        up.sanitize_filename("a/b.png")
    with pytest.raises(up.UploadError):
        up.sanitize_filename("")


def test_validate_device_path():
    assert up.validate_device_path("/sdcard/Pictures/x.jpg") == "/sdcard/Pictures/x.jpg"
    assert up.validate_device_path("/storage/emulated/0/Download/x") == "/storage/emulated/0/Download/x"
    with pytest.raises(up.UploadError):
        up.validate_device_path("/data/local/tmp/x")     # 前缀不允许
    with pytest.raises(up.UploadError):
        up.validate_device_path("/sdcard/../data/x")     # 穿越


def test_validate_url_scheme_and_ssrf():
    up.validate_url("https://example.com/a.jpg")          # ok（公网域名）
    with pytest.raises(up.UploadError):
        up.validate_url("ftp://example.com/a")            # scheme
    with pytest.raises(up.UploadError):
        up.validate_url("http://127.0.0.1/a")             # loopback
    with pytest.raises(up.UploadError):
        up.validate_url("http://169.254.169.254/latest")  # 元数据


def test_is_image():
    assert up.is_image("a.JPG") is True
    assert up.is_image("a.png") is True
    assert up.is_image("a.apk") is False


# ----- Task 3: 分片暂存 + 空间守卫 -----

def _patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()


def test_staging_chunks(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    sid = up.new_stage("big.apk")
    r1 = up.append_chunk(sid, b"AAAA", last=False)
    assert r1["bytes_received"] == 4 and r1["complete"] is False
    r2 = up.append_chunk(sid, b"BB", last=True)
    assert r2["bytes_received"] == 6 and r2["complete"] is True
    assert up.stage_is_complete(sid) is True
    assert up.stage_path(sid).read_bytes() == b"AAAABB"
    assert up.stage_filename(sid) == "big.apk"


def test_append_unknown_stage(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    with pytest.raises(up.UploadError):
        up.append_chunk("nonexistent", b"x", last=False)


def test_free_space_guard(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "_free_bytes", lambda: up.MIN_FREE_BYTES - 1)
    with pytest.raises(up.UploadError):
        up.new_stage("x.bin")
