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
