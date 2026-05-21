import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/common
import _fsops


def _content(r):
    return r if isinstance(r, str) else r["content"]


def test_write_then_read_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    _fsops.write_file(str(f), "hello\nworld\n")
    assert "hello" in _content(_fsops.read_file(str(f)))


def test_edit_block_replaces(tmp_path):
    f = tmp_path / "b.txt"
    _fsops.write_file(str(f), "foo bar foo")
    _fsops.edit_block(str(f), "foo", "X", replace_all=True)
    assert "X bar X" in _content(_fsops.read_file(str(f)))


def test_list_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "f.txt").write_text("x")
    names = str(_fsops.list_directory(str(tmp_path)))
    assert "f.txt" in names and "sub" in names


def test_create_directory(tmp_path):
    d = tmp_path / "made"
    _fsops.create_directory(str(d))
    assert d.exists()


def test_get_file_info(tmp_path):
    f = tmp_path / "f.txt"; f.write_text("x")
    assert _fsops.get_file_info(str(f))  # non-empty


def test_move_file(tmp_path):
    src = tmp_path / "s.txt"; src.write_text("x")
    dst = tmp_path / "d.txt"
    _fsops.move_file(str(src), str(dst))
    assert dst.exists() and not src.exists()


def test_expanduser_is_applied(tmp_path, monkeypatch):
    # THE BUG FIX regression test: a path with ~ must expand.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows home var
    _fsops.write_file("~/tilde.txt", "via tilde")
    assert (tmp_path / "tilde.txt").exists()
    assert "via tilde" in _content(_fsops.read_file("~/tilde.txt"))


def test_expanduser_applied_to_move_file_both_paths(tmp_path, monkeypatch):
    # move_file was a multi-path bug site (win missed expanduser on BOTH src and dst).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows home var
    _fsops.write_file("~/src_tilde.txt", "content")
    _fsops.move_file("~/src_tilde.txt", "~/dst_tilde.txt")
    assert (tmp_path / "dst_tilde.txt").exists()
    assert not (tmp_path / "src_tilde.txt").exists()
