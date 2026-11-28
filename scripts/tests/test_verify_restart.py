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
