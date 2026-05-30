"""Unit tests for _uploads_ios.py (iOS 上传支撑：纯逻辑 + WDA 客户端 + afc wrapper)."""
import sys
from pathlib import Path

import pytest

_SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SERVER))                                # ios server dir
sys.path.insert(0, str(_SERVER.parent.parent / "common"))       # platforms/common

import _uploads_ios as up_ios
from _upload_common import UploadError


# ----- Task 6: validate_relpath + resolve_target -----

def test_validate_relpath_ok():
    assert up_ios.validate_relpath("Documents/x.txt") == "Documents/x.txt"
    assert up_ios.validate_relpath("inbox/sub/y.pdf") == "inbox/sub/y.pdf"


def test_validate_relpath_rejects_absolute_traversal_chars():
    for bad in ["", "/abs", "..", "a/../b", "a;b", 'a"b']:
        with pytest.raises(UploadError):
            up_ios.validate_relpath(bad)


def test_resolve_target_photos_image_and_video():
    fname, params = up_ios.resolve_target(target="photos", filename="bg.jpg",
                                          bundle_id=None, relpath=None)
    assert fname == "bg.jpg" and params["type"] == "image"
    fname, params = up_ios.resolve_target(target="photos", filename="v.mov",
                                          bundle_id=None, relpath=None)
    assert params["type"] == "video"


def test_resolve_target_app():
    fname, params = up_ios.resolve_target(target="app", filename=None,
                                          bundle_id="com.example", relpath="Documents/x.pdf")
    assert fname == "x.pdf"
    assert params["bundle_id"] == "com.example"
    assert params["relpath"] == "Documents/x.pdf"


def test_resolve_target_rejects_bad_combo():
    with pytest.raises(UploadError):
        up_ios.resolve_target("photos", None, None, None)
    with pytest.raises(UploadError):
        up_ios.resolve_target("app", None, None, None)
    with pytest.raises(UploadError):
        up_ios.resolve_target("invalid", "f.jpg", None, None)


def test_resolve_target_photos_rejects_non_media_extension():
    with pytest.raises(UploadError):
        up_ios.resolve_target("photos", "doc.pdf", None, None)


# ----- Task 7: WDA HTTP 客户端 -----

import httpx


def test_wda_photos_import_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/wda/photos/import"
        assert request.headers["X-Filename"] == "bg.jpg"
        assert request.headers["X-Type"] == "image"
        assert request.headers["Content-Type"] == "application/octet-stream"
        assert request.read() == b"BYTES"
        return httpx.Response(200, json={"ok": True, "asset_id": "AID-123"})
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"BYTES", filename="bg.jpg", ttype="image")
    assert res == {"ok": True, "asset_id": "AID-123"}


def test_wda_photos_import_server_error(monkeypatch):
    def handler(request):
        return httpx.Response(500, json={"ok": False, "error": "permission denied"})
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"X", "v.mp4", "video")
    assert res["ok"] is False and "denied" in res.get("error", "").lower()


def test_wda_photos_import_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow")
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"X", "f.jpg", "image")
    assert res["ok"] is False and "timeout" in res["error"].lower()


def test_wda_photos_import_connection_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"X", "f.jpg", "image")
    assert res["ok"] is False and "hint" in res  # 端点不可达 → 给 hint


# ----- Task 8: afc_push_to_app（注入式 wrapper） -----

def test_afc_push_to_app_success():
    called = {}

    def fake_afc_op(udid, bundle_id, documents_only, op):
        # op 是 coroutine factory，但在 fake 里我们不真跑 await（只记录调用参数）
        called["udid"] = udid
        called["bundle"] = bundle_id
        called["doc_only"] = documents_only
        called["op_callable"] = callable(op)

    rc = up_ios.afc_push_to_app(
        udid="UDID1", bundle_id="com.x", documents_only=True,
        host_path="/tmp/file.bin", device_relpath="Documents/x.bin",
        afc_op=fake_afc_op,
    )
    assert rc == {"ok": True}
    assert called == {"udid": "UDID1", "bundle": "com.x", "doc_only": True, "op_callable": True}


def test_afc_push_to_app_failure_transparent_hint():
    def fake_afc_op(*args, **kw):
        raise RuntimeError("HouseArrest denied")

    rc = up_ios.afc_push_to_app(
        udid="U", bundle_id="b", documents_only=True,
        host_path="/tmp/x", device_relpath="x.bin",
        afc_op=fake_afc_op,
    )
    assert rc["ok"] is False
    assert "HouseArrest" in rc["error"]
    assert "hint" in rc
