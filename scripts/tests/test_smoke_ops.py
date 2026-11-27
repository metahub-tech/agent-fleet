"""smoke_ops 纯判据单测（无网络、无 MCP SDK）。"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smoke_ops as so

SHA = hashlib.sha256(b"x").hexdigest()


# --- 工具注册 -------------------------------------------------------------

def test_tools_registered_ok():
    caps = {"capabilities": [{"id": "core", "status": "enabled",
                              "tools": list(so.REQUIRED_TOOLS)}]}
    ok, detail = so.check_tools_registered(caps)
    assert ok is True and "5 required" in detail


def test_tools_missing_is_reported():
    caps = {"capabilities": [{"id": "core", "status": "enabled", "tools": ["tap"]}]}
    ok, detail = so.check_tools_registered(caps)
    assert ok is False and "file_put" in detail
    assert so.check_tools_registered({})[0] is False


# --- 二进制往返 -----------------------------------------------------------

def _put(sha=SHA, ok=True):
    return {"ok": ok, "sha256": sha, "bytes": 2}


def _get(sha=SHA, ok=True, content=b"x"):
    import base64
    return {"ok": ok, "sha256": sha, "bytes": 1, "content_b64": base64.b64encode(content).decode()}


def test_roundtrip_ok():
    ok, detail = so.check_roundtrip(_put(), _get(), SHA, 1)
    assert ok is True and SHA[:12] in detail


def test_roundtrip_detects_sha_drift():
    ok, detail = so.check_roundtrip(_put(), _get(sha="deadbeef"), SHA, 1)
    assert ok is False and "round-trip sha" in detail


def test_roundtrip_detects_size_drift():
    got = _get()
    got["bytes"] = 99
    ok, detail = so.check_roundtrip(_put(), got, SHA, 1)
    assert ok is False and "size" in detail


def test_roundtrip_detects_wrong_decoded_payload():
    got = _get(content=b"different")     # sha 字段仍是 SHAs，但内容对不上
    ok, detail = so.check_roundtrip(_put(), got, SHA, 1)
    assert ok is False and "decoded payload" in detail


def test_roundtrip_reports_put_failure():
    ok, detail = so.check_roundtrip({"ok": False, "reason": "symlink_not_allowed"}, {}, SHA, 1)
    assert ok is False and "symlink_not_allowed" in detail


# --- 超限 ---------------------------------------------------------------

def test_oversize_rejected():
    ok, detail = so.check_oversize_rejected(
        {"ok": False, "reason": "file_too_large", "bytes": 5 * 1024 * 1024}, 5 * 1024 * 1024)
    assert ok is True


def test_oversize_accepted_is_failure():
    ok, detail = so.check_oversize_rejected({"ok": True}, 5 * 1024 * 1024)
    assert ok is False and "must fail" in detail


def test_oversize_wrong_reason_is_failure():
    ok, detail = so.check_oversize_rejected({"ok": False, "reason": "write_failed", "bytes": 1}, 1)
    assert ok is False and "file_too_large" in detail


# --- 剪贴板 -------------------------------------------------------------

def test_clipboard_ok():
    ok, detail = so.check_clipboard({"ok": True, "verified": True,
                                     "readback": "bytes_equal", "formats": ["HTML Format"]})
    assert ok is True and "bytes_equal" in detail


def test_clipboard_extra_format_is_failure():
    ok, detail = so.check_clipboard({"ok": True, "verified": True, "readback": "bytes_equal",
                                     "formats": ["CF_UNICODETEXT", "HTML Format"]})
    assert ok is False and "exactly" in detail


def test_clipboard_readback_failure_is_failure():
    ok, detail = so.check_clipboard({"ok": True, "verified": False, "readback": "markers_missing",
                                     "formats": ["HTML Format"]})
    assert ok is False and "markers_missing" in detail


# --- wait_for -----------------------------------------------------------

def test_wait_for_timeout_ok():
    ok, detail = so.check_wait_for({"ok": False, "reason": "timeout", "elapsed_ms": 305}, 300)
    assert ok is True and "305ms" in detail


def test_wait_for_too_early_is_failure():
    # 假超时：声称超时但几乎没等 —— 说明预算没被执行
    ok, detail = so.check_wait_for({"ok": False, "reason": "timeout", "elapsed_ms": 3}, 300)
    assert ok is False and "too early" in detail


def test_wait_for_unexpected_ok_is_failure():
    ok, detail = so.check_wait_for({"ok": True, "elapsed_ms": 100}, 300)
    assert ok is False and "expected a timeout" in detail


# --- 批量 ---------------------------------------------------------------

def test_batch_ok():
    payload = {"ok": True, "completed": 2, "total": 2,
               "steps": [{"status": "ok"}, {"status": "ok"}]}
    assert so.check_batch_ok(payload)[0] is True


def test_batch_partial_is_failure():
    payload = {"ok": True, "completed": 1, "total": 2,
               "steps": [{"status": "ok"}, {"status": "skipped"}]}
    ok, detail = so.check_batch_ok(payload)
    assert ok is False and "completed" in detail


def test_batch_rejected_ok():
    ok, detail = so.check_batch_rejected(
        {"ok": False, "reason": "invalid_steps", "allowed_tools": ["tap"]})
    assert ok is True and "rejected before running" in detail


def test_batch_rejected_but_ran_something():
    ok, detail = so.check_batch_rejected(
        {"ok": False, "reason": "invalid_steps", "allowed_tools": ["tap"],
         "steps": [{"index": 0, "status": "ok"}]})
    assert ok is False and "something ran" in detail


# --- 折行 base64 与重试路径 -------------------------------------------------

def test_wrapped_base64_accepted():
    ok, detail = so.check_wrapped_base64_accepted({"ok": True, "sha256": SHA}, SHA)
    assert ok is True and "76-column" in detail


def test_wrapped_base64_rejected_is_actionable():
    ok, detail = so.check_wrapped_base64_accepted({"ok": False, "reason": "invalid_base64"}, SHA)
    assert ok is False and "whitespace must be stripped" in detail


def test_wrapped_base64_sha_mismatch():
    ok, detail = so.check_wrapped_base64_accepted({"ok": True, "sha256": "deadbeef"}, SHA)
    assert ok is False and "sha mismatch" in detail


def test_attempts_reported_ok():
    ok, detail = so.check_attempts_reported({"ok": True, "attempts": 1}, 2)
    assert ok is True and "1/2" in detail


def test_attempts_out_of_range():
    ok, _ = so.check_attempts_reported({"ok": True, "attempts": 3}, 2)
    assert ok is False
    ok, _ = so.check_attempts_reported({"ok": True}, 2)
    assert ok is False


def test_attempts_reports_failure():
    ok, detail = so.check_attempts_reported({"ok": False, "reason": "clipboard_busy"}, 2)
    assert ok is False and "clipboard_busy" in detail


# --- UIA 稳定性（预算内必须返回） -----------------------------------------

def test_uia_ok_payload_is_fine():
    ok, detail = so.check_uia_latency("dump_ui", {"ok": True, "elements": []}, 1200)
    assert ok is True and "1200ms" in detail


def test_uia_timeout_reason_counts_as_bounded():
    # 超时本身是"有界"的答案，不是失败
    ok, detail = so.check_uia_latency("dump_ui", {"ok": False, "reason": "uia_timeout"}, 8100)
    assert ok is True and "uia_timeout" in detail


def test_uia_console_window_is_bounded():
    ok, _ = so.check_uia_latency("dump_ui", {"ok": False, "reason": "console_window"}, 30)
    assert ok is True


def test_uia_too_slow_is_failure():
    ok, detail = so.check_uia_latency("dump_ui", {"ok": True}, 20000)
    assert ok is False and "not bounded" in detail


def test_list_windows_returns_list():
    ok, detail = so.check_uia_latency("list_windows", [{"title": "a"}], 300)
    assert ok is True and "1 item" in detail


def test_uia_unexpected_failure_is_reported():
    ok, detail = so.check_uia_latency("find_elements", {"ok": False, "reason": "boom"}, 100)
    assert ok is False and "unexpectedly" in detail


def test_uia_no_foreground_special_case():
    ok, _ = so.check_uia_latency("dump_ui", {"ok": False, "error": "No foreground window detected"}, 5)
    assert ok is True
