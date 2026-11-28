"""`analyze_tool_audit.py`：窗口过滤、坏行容错、候选端点覆盖率。"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyze_tool_audit as ana  # noqa: E402


def _rec(tool, ts, ms=5, ok=True):
    return {"ts": ts, "tool": tool, "ms": ms, "ok": ok}


def _dump(path: Path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_load_records_skips_bad_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text('{"tool":"tap","ts":"2026-11-27T00:00:00+00:00"}\nnot json\n{"no_tool":1}\n',
                    encoding="utf-8")
    recs = ana.load_records([path])
    assert len(recs) == 1 and recs[0]["tool"] == "tap"


def test_filter_days_window():
    now = datetime(2026, 11, 28, tzinfo=timezone.utc)
    records = [
        _rec("tap", (now - timedelta(days=1)).isoformat()),
        _rec("tap", (now - timedelta(days=10)).isoformat()),
    ]
    kept = ana.filter_days(records, 5, now=now)
    assert len(kept) == 1


def test_filter_days_zero_means_all():
    records = [_rec("tap", "2020-01-01T00:00:00+00:00")]
    assert ana.filter_days(records, 0) == records


def test_profile_coverage_counts_calls_not_tools():
    import collections
    by_tool = collections.Counter({"run_shell": 90, "take_screenshot": 10})
    covered, needed = ana.profile_coverage(by_tool, ana.PROFILES["ops"])
    assert covered == 90
    assert needed == 1          # 只有 run_shell 真的出现过


def test_profiles_cover_known_tools():
    """内置候选必须至少覆盖一次真实存在的工具名（防止写成空集）。"""
    all_known = {"run_shell", "take_screenshot", "human_dom_locate", "eval_in_profile"}
    for name in ("ops", "gui"):
        assert ana.PROFILES[name] & all_known


def test_main_reports_missing_file(tmp_path, capsys):
    rc = ana.main(["--path", str(tmp_path / "nope.jsonl"), "--days", "5"])
    assert rc == 2
    assert "没有找到审计文件" in capsys.readouterr().err


def test_main_prints_summary(tmp_path, capsys):
    path = tmp_path / "a.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    _dump(path, [_rec("run_shell", now), _rec("take_screenshot", now, ok=False)])
    rc = ana.main(["--path", str(path), "--days", "5", "--profiles", "ops"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run_shell" in out and "覆盖" in out


def test_main_json_mode(tmp_path, capsys):
    path = tmp_path / "a.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    _dump(path, [_rec("tap", now)])
    rc = ana.main(["--path", str(path), "--days", "5", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["total"] == 1


# --- 会话序列（拆端点前真正该看的指标）-------------------------------

def _rec_s(tool, ts, session, ok=True):
    return {"ts": ts, "tool": tool, "ms": 5, "ok": ok, "session": session}


def test_session_sequences_orders_by_time():
    recs = [
        _rec_s("take_screenshot", "2026-11-27T00:00:02+00:00", "aaaa1111"),
        _rec_s("run_shell", "2026-11-27T00:00:01+00:00", "aaaa1111"),
    ]
    seqs = ana.session_sequences(recs)
    assert seqs[0]["tools"] == ["run_shell", "take_screenshot"]


def test_session_sequences_flags_cross_group():
    """一个会话同时用 ops 与 gui ⇒ coupled（拆端点会把它拆成两次连接）。"""
    recs = [
        _rec_s("run_shell", "2026-11-27T00:00:01+00:00", "mix00001"),
        _rec_s("take_screenshot", "2026-11-27T00:00:02+00:00", "mix00001"),
    ]
    seqs = ana.session_sequences(recs)
    assert seqs[0]["coupled"] is True
    assert set(seqs[0]["groups"]) == {"ops", "gui"}


def test_session_sequences_single_group_not_coupled():
    recs = [
        _rec_s("run_shell", "2026-11-27T00:00:01+00:00", "ops00001"),
        _rec_s("write_file", "2026-11-27T00:00:02+00:00", "ops00001"),
    ]
    assert ana.session_sequences(recs)[0]["coupled"] is False


def test_session_sequences_ignores_records_without_session():
    assert ana.session_sequences([{"ts": "x", "tool": "tap"}]) == []


def test_main_sessions_mode_prints_sequences(tmp_path, capsys):
    path = tmp_path / "a.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    _dump(path, [_rec_s("run_shell", now, "sess0001"), _rec_s("take_screenshot", now, "sess0001")])
    rc = ana.main(["--path", str(path), "--days", "5", "--sessions", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "会话序列" in out and "⚠ 跨组" in out
