"""`verify_restart.py`：第 4 件（pid 变化）是唯一能证明"新码进内存"的判据。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verify_restart as vr  # noqa: E402


def test_parse_audit_lines_skips_noise():
    stdout = 'garbage\n{"tool":"get_status","pid":266180}\nnot json\n'
    recs = vr.parse_audit_lines(stdout)
    assert len(recs) == 1 and recs[0]["pid"] == 266180


def test_latest_pid_takes_last_valid():
    recs = [{"tool": "a", "pid": 1}, {"tool": "b", "pid": 2}, {"tool": "c"}]
    assert vr.latest_pid(recs) == 2
    assert vr.latest_pid([]) is None


def test_count_tools_sums_capabilities():
    caps = {"capabilities": [{"tools": ["a", "b"]}, {"tools": ["c"]}, {}]}
    assert vr.count_tools(caps) == 3


def test_count_tools_tolerates_missing_key():
    assert vr.count_tools({}) == 0


def test_pid_change_is_the_real_evidence():
    """三条老判据旧进程也满足；只有 pid 变化能区分。"""
    old = 266180
    same = vr.latest_pid([{"tool": "x", "pid": 266180}])
    new = vr.latest_pid([{"tool": "x", "pid": 273212}])
    assert same == old        # 服务活着，但仍是旧进程
    assert new != old         # 真正重启


def test_health_ok_handles_bad_url():
    ok, detail = vr.health_ok("http://127.0.0.1:9/mcp", timeout_s=1)
    assert ok is False and detail


def test_read_audit_accepts_normalised_payload():
    """`call` 已经归一化过；再包一层 payload_of 会把 dict 变成 []（曾导致"审计 0 行"的假失败）。"""
    import asyncio

    async def call(tool, args):
        assert tool == "run_shell"
        return {"returncode": 0, "stdout": '{"tool":"x","pid":1}\n', "stderr": ""}

    out = asyncio.run(vr._read_audit(call, "whatever"))
    assert "pid" in out
    assert vr.latest_pid(vr.parse_audit_lines(out)) == 1


def test_read_audit_handles_error_payload():
    import asyncio

    async def call(tool, args):
        return {"ok": False, "reason": "device_leased"}

    assert asyncio.run(vr._read_audit(call, "x")) == ""


# --- 期望值集中管理：不要在脚本里硬编码 91 ------------------------------

def test_expected_tools_lookup_by_host():
    import _expectations as ex
    assert ex.expected_tools_for("http://test-win11:8766/mcp") == 91
    assert ex.expected_tools_for("http://unknown-host:1234/mcp") is None


def test_expect_holder_flag_per_host():
    import _expectations as ex
    assert ex.expect_holder_for("http://test-win11:8766/mcp") is True
    assert ex.expect_holder_for("http://other:1/mcp") is False


# --- holder 判据：有序两段，证据自造 -----------------------------------

def test_holder_skipped_when_pid_unchanged():
    """pid 未变 = 旧码：不再看 holder，也不把"没造证据"写成"字段未落地"。"""
    ok, detail = vr.holder_verdict(pid_changed=False, acquired=False,
                                   records=[], marker="m")
    assert ok is True and "skipped" in detail and "旧码" in detail


def test_holder_skipped_when_device_held_by_other():
    ok, detail = vr.holder_verdict(pid_changed=True, acquired=False,
                                   records=[], marker="m")
    assert ok is True and "无法自证" in detail


def test_holder_fails_only_when_pid_changed_and_no_evidence():
    ok, detail = vr.holder_verdict(pid_changed=True, acquired=True,
                                   records=[{"tool": "acquire", "holder": "other"}], marker="m")
    assert ok is False and "未找到 holder=m" in detail


def test_holder_passes_with_self_created_evidence():
    ok, detail = vr.holder_verdict(pid_changed=True, acquired=True,
                                   records=[{"tool": "acquire", "holder": "m"}], marker="m")
    assert ok is True and "已自证" in detail


# --- 三状态：pass / fail / skipped（"没验成"不是"验不过"）-------------

def test_summary_marks_skipped_separately(capsys, tmp_path, monkeypatch):
    """skipped 既不算通过也不算失败；退出码只看 fail。"""
    async def fake_run_checks(*a, **k):
        return [
            {"check": "a", "ok": True, "skipped": False, "detail": ""},
            {"check": "b", "ok": True, "skipped": True, "detail": "skipped: x"},
            {"check": "c", "ok": False, "skipped": False, "detail": ""},
        ]

    monkeypatch.setattr(vr, "run_checks", fake_run_checks)
    rc = vr.main(["--url", "http://h/mcp"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "1 passed, 1 failed, 1 skipped" in out
    assert "SKIP b" in out


def test_skipped_only_run_exits_zero(capsys, monkeypatch):
    async def fake_run_checks(*a, **k):
        return [
            {"check": "a", "ok": True, "skipped": False, "detail": ""},
            {"check": "b", "ok": True, "skipped": True, "detail": "skipped: 无法自证"},
        ]

    monkeypatch.setattr(vr, "run_checks", fake_run_checks)
    rc = vr.main(["--url", "http://h/mcp"])
    assert rc == 0
    assert "1 passed, 0 failed, 1 skipped" in capsys.readouterr().out


# --- CI 严格模式：SKIP 不能报绿 ----------------------------------------

def test_strict_mode_returns_4_when_only_skips(capsys, monkeypatch):
    async def fake_run_checks(*a, **k):
        return [
            {"check": "a", "ok": True, "skipped": False, "detail": ""},
            {"check": "b", "ok": True, "skipped": True, "detail": "skipped: 无法自证"},
        ]

    monkeypatch.setattr(vr, "run_checks", fake_run_checks)
    rc = vr.main(["--url", "http://h/mcp", "--strict"])
    assert rc == 4
    assert "未完整" in capsys.readouterr().err


def test_strict_mode_still_returns_1_on_failure(capsys, monkeypatch):
    async def fake_run_checks(*a, **k):
        return [{"check": "c", "ok": False, "skipped": False, "detail": ""}]

    monkeypatch.setattr(vr, "run_checks", fake_run_checks)
    assert vr.main(["--url", "http://h/mcp", "--strict"]) == 1


def test_non_strict_allows_skip(capsys, monkeypatch):
    async def fake_run_checks(*a, **k):
        return [{"check": "b", "ok": True, "skipped": True, "detail": "skipped: x"}]

    monkeypatch.setattr(vr, "run_checks", fake_run_checks)
    assert vr.main(["--url", "http://h/mcp"]) == 0


# --- build：直接断言"跑的是哪份代码"，而不是代理指标 ----------------------

def test_build_skipped_when_pid_unchanged():
    ok, detail, skipped = vr.build_verdict(False, [], "abc", 1)
    assert ok is True and skipped is True and "旧码" in detail


def test_build_skipped_without_expectation():
    ok, detail, skipped = vr.build_verdict(True, [], "", 1)
    assert ok and skipped and "未指定" in detail


def test_build_matches_new_pid_record():
    recs = [{"pid": 1, "build": "old"}, {"pid": 2, "build": "abc"}]
    ok, detail, skipped = vr.build_verdict(True, recs, "abc", 2)
    assert ok and not skipped and "一致" in detail


def test_build_mismatch_is_failure():
    recs = [{"pid": 2, "build": "zzz"}]
    ok, detail, skipped = vr.build_verdict(True, recs, "abc", 2)
    assert ok is False and "不是期望的代码" in detail


def test_build_skipped_for_old_records_without_field():
    recs = [{"pid": 2}]
    ok, detail, skipped = vr.build_verdict(True, recs, "abc", 2)
    assert ok and skipped and "旧版审计" in detail


# --- build 比较的形状归一 与 dirty 降级 --------------------------------

def test_normalize_build_handles_short_long_and_case():
    assert vr.normalize_build("5BB3A79") == vr.normalize_build("5bb3a79")
    assert vr.normalize_build("5bb3a79abc123") == "5bb3a79"
    assert vr.normalize_build("") == ""


def test_build_match_across_shapes_is_not_false_red():
    recs = [{"pid": 2, "build": "5bb3a79"}]
    ok, _d, skipped = vr.build_verdict(True, recs, "5bb3a79abc123def", 2)
    assert ok and not skipped


def test_dirty_downgrades_build_assertion_to_skip():
    """工作区脏 ⇒ HEAD 相同但代码可能不同，不能判 PASS。"""
    recs = [{"pid": 2, "build": "abc", "dirty": True}]
    ok, detail, skipped = vr.build_verdict(True, recs, "abc", 2)
    assert ok is True and skipped is True and "dirty" in detail


def test_clean_working_tree_allows_build_pass():
    recs = [{"pid": 2, "build": "abc", "dirty": False}]
    ok, _d, skipped = vr.build_verdict(True, recs, "abc", 2)
    assert ok and not skipped
