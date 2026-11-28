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
