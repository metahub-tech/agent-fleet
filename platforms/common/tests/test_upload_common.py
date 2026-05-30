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


# ----- Task 3: url/SSRF + 流式 download_url -----

import functools
import http.server
import threading as _t


def _serve(d):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    s = http.server.HTTPServer(("127.0.0.1", 0), h)
    _t.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]


def test_ip_blocked():
    assert up._ip_is_blocked("127.0.0.1") and up._ip_is_blocked("10.1.2.3")
    assert up._ip_is_blocked("169.254.169.254")
    assert not up._ip_is_blocked("8.8.8.8")
    assert not up._ip_is_blocked("not-an-ip")


def test_validate_url():
    up.validate_url("https://example.com/x")
    with pytest.raises(up.UploadError):
        up.validate_url("ftp://example.com")
    with pytest.raises(up.UploadError):
        up.validate_url("http://127.0.0.1/x")


def test_download_url_ok(tmp_path, monkeypatch):
    (tmp_path / "a.bin").write_bytes(b"X" * 80)
    s, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)
    monkeypatch.setattr(up, "_ip_is_blocked", lambda ip: False)
    try:
        n = up.download_url(f"http://127.0.0.1:{port}/a.bin", tmp_path / "o", max_bytes=1000)
        assert n == 80 and (tmp_path / "o").read_bytes() == b"X" * 80
    finally:
        s.shutdown()


def test_download_url_over_limit(tmp_path, monkeypatch):
    (tmp_path / "big.bin").write_bytes(b"X" * 5000)
    s, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)
    monkeypatch.setattr(up, "_ip_is_blocked", lambda ip: False)
    try:
        with pytest.raises(up.UploadError):
            up.download_url(f"http://127.0.0.1:{port}/big.bin", tmp_path / "o", max_bytes=1000)
    finally:
        s.shutdown()
