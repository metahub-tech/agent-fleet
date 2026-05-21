"""Tests for platforms/common/_search.py — shared content-search ops."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/common
import _search


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poll_done(search_id: str, max_iterations: int = 60, interval: float = 0.05):
    """Poll get_more_search_results until search is done or we time out."""
    for _ in range(max_iterations):
        result = _search.get_more_search_results(search_id)
        if result.get("done"):
            return result
        time.sleep(interval)
    # Return whatever we have even if not done (test will fail on assertions)
    return _search.get_more_search_results(search_id)


def _poll_has_matches(search_id: str, min_matches: int = 1, max_iterations: int = 60, interval: float = 0.05):
    """Poll until we have at least min_matches OR search is done."""
    for _ in range(max_iterations):
        result = _search.get_more_search_results(search_id)
        if result.get("total_matches", 0) >= min_matches or result.get("done"):
            return result
        time.sleep(interval)
    return _search.get_more_search_results(search_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_basic_search_finds_matching_files(tmp_path):
    """Two files contain NEEDLE, one does not; search should find the two."""
    needle_file1 = tmp_path / "alpha.txt"
    needle_file2 = tmp_path / "beta.txt"
    no_match_file = tmp_path / "gamma.txt"
    needle_file1.write_text("This line has the NEEDLE token\n")
    needle_file2.write_text("Another NEEDLE line here\n")
    no_match_file.write_text("Nothing to see here.\n")

    result = _search.start_search(str(tmp_path), "NEEDLE")
    assert "search_id" in result, f"Expected search_id in result: {result}"
    assert "started_at" in result, f"Expected started_at in result: {result}"
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        assert final.get("done"), "Search did not complete within timeout"
        matched_files = {m["file"] for m in final["matches"]}
        assert str(needle_file1) in matched_files, f"{needle_file1} not found in matches"
        assert str(needle_file2) in matched_files, f"{needle_file2} not found in matches"
        assert str(no_match_file) not in matched_files, f"{no_match_file} should NOT be in matches"
    finally:
        _search.stop_search(search_id)


def test_match_shape(tmp_path):
    """Each match has file, line, text keys."""
    f = tmp_path / "test.txt"
    f.write_text("line one\nNEEDLE is here\nline three\n")

    result = _search.start_search(str(tmp_path), "NEEDLE")
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        assert final["total_matches"] >= 1
        match = final["matches"][0]
        assert "file" in match
        assert "line" in match
        assert "text" in match
        assert match["line"] == 2  # "NEEDLE is here" is on line 2
        assert "NEEDLE" in match["text"]
    finally:
        _search.stop_search(search_id)


def test_get_more_search_results_return_shape(tmp_path):
    """Return dict has the expected keys."""
    (tmp_path / "f.txt").write_text("NEEDLE\n")
    result = _search.start_search(str(tmp_path), "NEEDLE")
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        assert "search_id" in final
        assert "total_matches" in final
        assert "from_index" in final
        assert "to_index" in final
        assert "matches" in final
        assert "done" in final
        assert "truncated" in final
        assert final["search_id"] == search_id
    finally:
        _search.stop_search(search_id)


def test_get_more_search_results_offset_and_length(tmp_path):
    """offset/length pagination works."""
    f = tmp_path / "many.txt"
    f.write_text("\n".join(f"NEEDLE line {i}" for i in range(10)))

    result = _search.start_search(str(tmp_path), "NEEDLE")
    search_id = result["search_id"]

    try:
        _poll_done(search_id)
        page = _search.get_more_search_results(search_id, offset=2, length=3)
        assert page["from_index"] == 2
        assert len(page["matches"]) <= 3
    finally:
        _search.stop_search(search_id)


def test_unknown_search_id_returns_error():
    """get_more_search_results with unknown id returns error dict."""
    result = _search.get_more_search_results("nonexistent_id_xyz")
    assert "error" in result


def test_stop_search_unknown_id_returns_error():
    """stop_search with unknown id returns error dict."""
    result = _search.stop_search("nonexistent_id_xyz")
    assert "error" in result


def test_list_searches_includes_active(tmp_path):
    """list_searches returns the search we started."""
    (tmp_path / "f.txt").write_text("NEEDLE here\n")
    result = _search.start_search(str(tmp_path), "NEEDLE")
    search_id = result["search_id"]

    try:
        listing = _search.list_searches()
        ids = [s["search_id"] for s in listing]
        assert search_id in ids

        entry = next(s for s in listing if s["search_id"] == search_id)
        assert "root" in entry
        assert "pattern" in entry
        assert "started_at" in entry
        assert "matches" in entry  # count
        assert "done" in entry
        assert "truncated" in entry
    finally:
        _poll_done(search_id)
        _search.stop_search(search_id)


def test_stop_search_returns_ok(tmp_path):
    """stop_search returns ok=True."""
    (tmp_path / "f.txt").write_text("NEEDLE\n")
    result = _search.start_search(str(tmp_path), "NEEDLE")
    search_id = result["search_id"]
    _poll_done(search_id)

    stop_result = _search.stop_search(search_id)
    assert stop_result.get("ok") is True
    assert stop_result.get("search_id") == search_id


def test_case_insensitive_by_default(tmp_path):
    """Default search is case-insensitive."""
    (tmp_path / "f.txt").write_text("needle lowercase\n")
    result = _search.start_search(str(tmp_path), "NEEDLE")  # uppercase pattern
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        assert final["total_matches"] >= 1, "Case-insensitive search should find lowercase 'needle'"
    finally:
        _search.stop_search(search_id)


def test_case_sensitive_no_match(tmp_path):
    """Case-sensitive search should NOT match wrong case."""
    (tmp_path / "f.txt").write_text("needle lowercase\n")
    result = _search.start_search(str(tmp_path), "NEEDLE", case_sensitive=True)
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        assert final["total_matches"] == 0, "Case-sensitive search should not find lowercase 'needle' with NEEDLE pattern"
    finally:
        _search.stop_search(search_id)


def test_file_glob_filter(tmp_path):
    """file_glob restricts which files are searched."""
    (tmp_path / "match.py").write_text("NEEDLE in python\n")
    (tmp_path / "no_match.txt").write_text("NEEDLE in text\n")

    result = _search.start_search(str(tmp_path), "NEEDLE", file_glob="*.py")
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        matched_files = {m["file"] for m in final["matches"]}
        assert str(tmp_path / "match.py") in matched_files
        assert str(tmp_path / "no_match.txt") not in matched_files
    finally:
        _search.stop_search(search_id)


def test_invalid_regex_returns_error(tmp_path):
    """Invalid regex returns error, not an exception."""
    result = _search.start_search(str(tmp_path), "[invalid")
    assert "error" in result


def test_nonexistent_directory_returns_error():
    """Non-existent path returns error."""
    result = _search.start_search("/nonexistent/path/xyz123", "NEEDLE")
    assert "error" in result


def test_expanduser_tilde_expansion(tmp_path, monkeypatch):
    """Regression: start_search with '~/' must expand the tilde (Windows bug fix)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows home var

    # Invalidate Path's cached home so expanduser picks up the monkeypatched HOME
    (tmp_path / "tilde_needle.txt").write_text("NEEDLE via tilde path\n")

    result = _search.start_search("~/", "NEEDLE")
    # If tilde was not expanded this would return an error or find nothing
    assert "error" not in result, f"Expected search to start, got: {result}"
    search_id = result["search_id"]

    try:
        final = _poll_done(search_id)
        matched_files = {m["file"] for m in final["matches"]}
        assert str(tmp_path / "tilde_needle.txt") in matched_files, (
            f"Expected to find tilde_needle.txt after ~ expansion. "
            f"Matched: {matched_files}. done={final.get('done')}"
        )
    finally:
        _search.stop_search(search_id)
