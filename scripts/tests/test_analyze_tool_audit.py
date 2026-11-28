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


# --- 重连碎片：不粘回去会系统性低估跨组耦合 ------------------------------

def _r(tool, ts, session="s1", pid=100, holder=""):
    rec = {"ts": ts, "tool": tool, "ms": 5, "ok": True, "session": session, "pid": pid}
    if holder:
        rec["holder"] = holder
    return rec


def test_stitch_merges_reconnect_fragments():
    """同一 pid、间隔 < 60s 的两段（不同 session）应粘成一个单元，且识别为跨组。

    这是"拆端点"决策的关键偏差：重连把一条 ops→gui 的工作流切成两个单组会话，
    不粘回去就会得出"没有跨组"的结论（恰好指向"可以拆"，最危险）。
    """
    recs = [
        _r("run_shell", "2026-11-27T00:00:00+00:00", session="aaaa", pid=7),
        _r("run_shell", "2026-11-27T00:00:10+00:00", session="aaaa", pid=7),
        _r("take_screenshot", "2026-11-27T00:00:20+00:00", session="bbbb", pid=7),  # 重连后新 session
        _r("type_text", "2026-11-27T00:00:30+00:00", session="bbbb", pid=7),
    ]
    units = ana.stitch_units(recs, gap_s=60)
    assert len(units) == 1
    assert ana.unit_profile(units[0])["coupled"] is True
    # 不粘时：两个单组会话
    raw = {}
    for r in recs:
        raw.setdefault(r["session"], []).append(r)
    assert sum(1 for g in raw.values() if ana.unit_profile(g)["coupled"]) == 0


def test_stitch_splits_on_large_gap():
    recs = [
        _r("run_shell", "2026-11-27T00:00:00+00:00", pid=7),
        _r("run_shell", "2026-11-27T00:05:00+00:00", pid=7),   # 5 分钟空档 ⇒ 两个单元
    ]
    assert len(ana.stitch_units(recs, gap_s=60)) == 2


def test_stitch_splits_across_pids():
    recs = [
        _r("run_shell", "2026-11-27T00:00:00+00:00", pid=1),
        _r("run_shell", "2026-11-27T00:00:05+00:00", pid=2),
    ]
    assert len(ana.stitch_units(recs, gap_s=60)) == 2


def test_call_count_histogram_buckets():
    units = [[{}] * 1, [{}] * 2, [{}] * 4, [{}] * 10, [{}] * 30]
    hist = ana.call_count_histogram(units)
    assert hist == {"1": 1, "2": 1, "3-5": 1, "6-20": 1, "21+": 1}


def test_main_warns_when_fragments_present(tmp_path, capsys):
    path = tmp_path / "a.jsonl"
    now = datetime.now(timezone.utc)
    recs = [
        _r("run_shell", (now - timedelta(seconds=30)).isoformat(), session="aaaa", pid=9),
        _r("take_screenshot", now.isoformat(), session="bbbb", pid=9),
    ]
    _dump(path, recs)
    rc = ana.main(["--path", str(path), "--days", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "粘贴后单元" in out
    assert "下界" in out


# --- 多 agent 同时段：同 pid 但不同 holder 不得粘连（上界方向）-----------

def test_stitch_does_not_merge_different_holders():
    """pid 是服务端进程、多 agent 共享；只有 holder 能区分。

    否则会把 A 的 ops 调用和 B 的 gui 调用缝成一个"跨组单元"，让跨组率**虚高**
    （与重连碎片导致的虚低方向相反）。
    """
    recs = [
        _r("run_shell", "2026-11-27T00:00:00+00:00", pid=7, holder="agent-A"),
        _r("take_screenshot", "2026-11-27T00:00:10+00:00", pid=7, holder="agent-B"),
    ]
    units = ana.stitch_units(recs, gap_s=180)
    assert len(units) == 2
    assert all(not ana.unit_profile(u)["coupled"] for u in units)


def test_stitch_merges_same_holder_across_sessions():
    recs = [
        _r("run_shell", "2026-11-27T00:00:00+00:00", session="aaaa", pid=7, holder="agent-A"),
        _r("take_screenshot", "2026-11-27T00:00:10+00:00", session="bbbb", pid=7, holder="agent-A"),
    ]
    units = ana.stitch_units(recs, gap_s=180)
    assert len(units) == 1 and ana.unit_profile(units[0])["coupled"] is True


def test_cut_pairs_counts_only_over_threshold():
    recs = [
        _r("run_shell", "2026-11-27T00:00:00+00:00", pid=7, holder="A"),
        _r("run_shell", "2026-11-27T00:00:10+00:00", pid=7, holder="A"),   # 10s：不切
        _r("run_shell", "2026-11-27T00:10:00+00:00", pid=7, holder="A"),   # 590s：切
    ]
    assert ana.cut_pairs(recs, gap_s=180) == 1


# --- 延迟统计：墙钟含排队，必须用分位数 --------------------------------

def test_percentile_basic():
    vals = list(range(1, 101))
    assert ana.percentile(vals, 0.50) in (50, 51)
    assert ana.percentile(vals, 0.95) >= 95
    assert ana.percentile([], 0.5) == 0


def test_latency_stats_separates_outlier_from_typical():
    """一条 68s 的离群值不该把 p50 拉高——这正是"服务器忙"与"工具慢"的区别。"""
    recs = [{"tool": "run_shell", "ms": 5} for _ in range(9)]
    recs.append({"tool": "run_shell", "ms": 68815})
    stats = ana.latency_stats(recs)["run_shell"]
    assert stats["n"] == 10
    assert stats["p50"] == 5
    assert stats["max"] == 68815


def test_latency_stats_ignores_missing_ms():
    stats = ana.latency_stats([{"tool": "tap"}, {"tool": "tap", "ms": 7}])
    assert stats["tap"] == {"n": 1, "p50": 7, "p95": 7, "max": 7}


# --- 粘法自检：失效时不该出跨组结论 ------------------------------------

def test_stitch_health_flags_low_unit_ratio():
    units = [[{"ts": "2026-11-27T00:00:00+00:00", "tool": "run_shell"}]]   # 1 单元
    h = ana.stitch_health(units, session_count=32)
    assert h["degraded"] is True
    assert any("粘成了时间桶" in r for r in h["reasons"])


def test_stitch_health_flags_long_units():
    unit = [{"ts": "2026-11-27T00:00:00+00:00", "tool": "run_shell"},
            {"ts": "2026-11-27T01:00:00+00:00", "tool": "take_screenshot"}]
    h = ana.stitch_health([unit, unit], session_count=2)      # 比值 1.0，但时长 60 分钟
    assert h["degraded"] is True
    assert any("时长中位数" in r for r in h["reasons"])


def test_stitch_health_ok_when_dense_and_short():
    unit = [{"ts": "2026-11-27T00:00:00+00:00", "tool": "run_shell"},
            {"ts": "2026-11-27T00:01:00+00:00", "tool": "write_file"}]
    h = ana.stitch_health([unit, unit, unit], session_count=3)
    assert h["degraded"] is False and h["reasons"] == []


def test_unit_duration_uses_first_and_last():
    unit = [{"ts": "2026-11-27T00:00:00+00:00"}, {"ts": "2026-11-27T00:02:30+00:00"}]
    assert ana.unit_duration_s(unit) == 150
