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
