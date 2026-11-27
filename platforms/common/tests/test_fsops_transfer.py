"""`_fsops` 字节收发（file_put / file_get）单测：原子性、对账、拒绝路径、超限不截断。

任何平台可跑（Linux 上符号链接可用；Windows 的 junction 分支由 3.12 isjunction /
st_file_attributes 兜底，逻辑相同）。
"""
import base64
import hashlib
import os
from pathlib import Path

import pytest

from _fsops import (
    MAX_TRANSFER_BYTES,
    first_reparse_component,
    get_bytes,
    put_bytes,
    sha256_bytes,
)


def test_roundtrip_and_sha256(tmp_path):
    target = tmp_path / "sub" / "img.png"
    data = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    put_result = put_bytes(str(target), data)
    assert put_result["ok"] is True
    assert put_result["bytes"] == len(data)
    assert put_result["sha256"] == hashlib.sha256(data).hexdigest()

    got = get_bytes(str(target))
    assert got["ok"] is True
    assert got["bytes"] == len(data)
    assert got["sha256"] == put_result["sha256"]
    assert base64.b64decode(got["content_b64"]) == data
    assert "mtime" in got


def test_put_is_atomic_and_leaves_no_partial_file(tmp_path):
    target = tmp_path / "a.bin"
    put_bytes(str(target), b"first")
    put_bytes(str(target), b"second")
    assert target.read_bytes() == b"second"
    leftovers = [p.name for p in tmp_path.iterdir() if ".part-" in p.name]
    assert leftovers == []


def test_put_rejects_oversize_without_writing(tmp_path):
    target = tmp_path / "big.bin"
    result = put_bytes(str(target), b"x" * (MAX_TRANSFER_BYTES + 1))
    assert result["ok"] is False and result["reason"] == "file_too_large"
    assert result["bytes"] == MAX_TRANSFER_BYTES + 1
    assert not target.exists()


def test_get_rejects_oversize_without_truncating(tmp_path):
    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * (MAX_TRANSFER_BYTES + 1))
    result = get_bytes(str(target))
    assert result["ok"] is False and result["reason"] == "file_too_large"
    assert "content_b64" not in result


def test_get_missing_and_directory(tmp_path):
    assert get_bytes(str(tmp_path / "nope"))["reason"] == "not_found"
    assert get_bytes(str(tmp_path))["reason"] == "is_directory"


def test_put_rejects_symlinked_parent(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    os.symlink(real_dir, link)
    result = put_bytes(str(link / "file.bin"), b"data")
    assert result["ok"] is False and result["reason"] == "symlink_not_allowed"
    assert result["real_path"].endswith("link")
    assert not (real_dir / "file.bin").exists()


def test_put_can_follow_symlinks_when_asked(tmp_path):
    real_dir = tmp_path / "real2"
    real_dir.mkdir()
    link = tmp_path / "link2"
    os.symlink(real_dir, link)
    result = put_bytes(str(link / "file.bin"), b"data", follow_symlinks=True)
    assert result["ok"] is True
    assert (real_dir / "file.bin").read_bytes() == b"data"


def test_first_reparse_component_returns_deepest_first_hit(tmp_path):
    real_dir = tmp_path / "r"
    real_dir.mkdir()
    link = tmp_path / "l"
    os.symlink(real_dir, link)
    assert first_reparse_component(str(link / "x" / "y.bin")) == str(link)
    assert first_reparse_component(str(real_dir / "plain.bin")) is None


def test_sha256_helper():
    assert sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()


def test_put_creates_parent_directories(tmp_path):
    target = tmp_path / "a" / "b" / "c.bin"
    assert put_bytes(str(target), b"x")["ok"] is True
    assert Path(target).read_bytes() == b"x"
