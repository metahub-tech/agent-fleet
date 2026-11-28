#!/usr/bin/env python3
"""分析 `tool-audit.jsonl`：**哪些工具真的在被用？端点该怎么拆？**

数据来自 `platforms/common/_tool_audit.py`（服务端每个工具调用记一行：
`ts/tool/ms/ok/pid[/session]`，不记参数与返回值）。

两种用法：

```bash
# 1) 看最近 7 天：按天、按工具、按能力分组
python3 scripts/analyze_tool_audit.py --days 7

# 2) 评估候选端点覆盖多少真实调用（决定怎么拆）
python3 scripts/analyze_tool_audit.py --days 7 --profiles ops,gui,human
```

`--profiles` 内置几组候选（`ops` / `gui` / `human` / `devtools` / `all`），
输出"覆盖了 X% 的调用、需要挂 N 个工具"。判定标准建议：
**覆盖 ≥95% 且工具数明显更少** 才值得单独开端点；覆盖率不足的拆分只会让 agent
频繁换端点（换端点 = 换 URL，比多几个工具更贵）。
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_PATH = "~/.agent-fleet/tool-audit.jsonl"

#: 候选端点定义：值 = 该端点要挂的工具名集合（不在审计里出现的名字会被忽略）
PROFILES: dict[str, set[str]] = {
    "ops": {
        "run_shell", "start_process", "read_process_output", "interact_with_process",
        "write_file", "read_file", "edit_block", "file_put", "file_get",
        "force_terminate", "kill_process", "list_directory", "list_processes",
        "get_file_info", "move_file", "create_directory", "list_windows",
        "acquire", "release", "get_status", "list_capabilities", "list_devices",
        "get_default_device", "set_default_device",
    },
    "gui": {
        "take_screenshot", "tap", "tap_element", "find_elements", "dump_ui",
        "get_screen_size", "current_app", "launch_app", "terminate_app",
        "press_key", "type_text", "swipe", "hover_preview", "wait_for", "run_actions",
        "clipboard_set_html", "list_windows",
    },
    "human": {
        "human_browser_open", "human_dom_locate", "human_dom_tap", "human_dom_fill",
        "human_dom_status", "human_dom_focused", "vision_locate", "vision_tap",
        "vision_locate_image", "eval_in_profile", "list_tabs", "activate_tab", "cdp_port",
    },
    "devtools": {"eval_in_profile", "list_tabs", "activate_tab", "cdp_port"},
    "browser": {"agent_browser", "browser_navigate", "browser_click", "browser_snapshot"},
}
PROFILES["all"] = set().union(*PROFILES.values())


def load_records(paths: Iterable[Path]) -> list[dict]:
    """读主文件 + 轮转文件；坏行直接跳过（审计是尽力而为，不能因为一行坏掉就罢工）。"""
    out: list[dict] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("tool"):
                out.append(rec)
    return out


def audit_files(base: Path) -> list[Path]:
    """主文件 + 可能存在的 `.1` 轮转文件（按 mtime 排序，旧在前）。"""
    candidates = [base, base.with_suffix(base.suffix + ".1")]
    return sorted([p for p in candidates if p.exists()], key=lambda p: p.stat().st_mtime)


def filter_days(records: list[dict], days: float, now: Optional[datetime] = None) -> list[dict]:
    if not days or days <= 0:
        return records
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=days)
    kept = []
    for rec in records:
        ts = rec.get("ts")
        if not ts:
            continue
        try:
            when = datetime.fromisoformat(str(ts))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            kept.append(rec)
    return kept


def summarize(records: list[dict]) -> dict:
    by_tool = collections.Counter(r["tool"] for r in records)
    by_day = collections.Counter((r.get("ts") or "")[:10] for r in records)
    slow = collections.Counter()
    failures = collections.Counter()
    for rec in records:
        if rec.get("ok") is False:
            failures[rec["tool"]] += 1
        if isinstance(rec.get("ms"), int) and rec["ms"] >= 2000:
            slow[rec["tool"]] += 1
    return {"total": len(records), "by_tool": by_tool, "by_day": by_day,
            "slow": slow, "failures": failures, "latency": latency_stats(records)}


def health_by_holder(records: list[dict], gap_s: float, **health_kw) -> list[dict]:
    """**按 holder 分组**再跑一次粘法自检。

    为什么不能只看全局：holder 落地后，全局比值可能看着健康（例如 0.6），
    但某个 agent 的「单元/会话」可能只有 0.1 —— **总体正常、个别人被粘成时间桶**。
    这种偏差会被全局均值掩盖，而它恰好会让那一个人的判断失真。
    """
    groups: dict[str, list[dict]] = {}
    for rec in records:
        groups.setdefault(str(rec.get("holder") or "(no holder)"), []).append(rec)
    out: list[dict] = []
    for scope, recs in sorted(groups.items()):
        units = stitch_units(recs, gap_s=gap_s)
        sessions = len({str(r.get("session") or "") for r in recs if r.get("session")}) or 0
        out.append({"scope": scope, "units": len(units), "sessions": sessions,
                    "health": stitch_health(units, sessions, **health_kw)})
    return out


def percentile(values: list[int], q: float) -> int:
    """最近秩法分位数（q 取 0–1）。样本为空返回 0。"""
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return int(ordered[idx])


def latency_stats(records: list[dict]) -> dict[str, dict[str, int]]:
    """按工具算 p50/p95/max/调用数。

    **为什么必须用分位数**：审计的 `ms` 是从进入中间件到返回的墙钟，**包含排队与事件循环争用**
    （真机见过"读 20 行文件"记 68815ms，而客户端感知是秒级）。单看最大值会把
    "服务器忙的时候调用了 run_shell" 误读成 "run_shell 很慢"。
    """
    buckets: dict[str, list[int]] = {}
    for rec in records:
        ms = rec.get("ms")
        if isinstance(ms, int):
            buckets.setdefault(rec["tool"], []).append(ms)
    out: dict[str, dict[str, int]] = {}
    for name, values in buckets.items():
        out[name] = {"n": len(values), "p50": percentile(values, 0.50),
                     "p95": percentile(values, 0.95), "max": max(values)}
    return out


def session_sequences(records: list[dict]) -> list[dict]:
    """按 `session` 还原每个会话的工具序列（时间升序）。

    为什么需要它：**调用次数**只能说明"哪个工具热"，决定不了能不能拆端点。
    拆端点的真实代价是**一次任务跨了多少个工具、其中多少依赖同一份会话态**
    （lease 绑定 MCP session、剪贴板是全局资源、前台窗口只有一份）。所以要看序列。

    返回 ``[{"session": id, "tools": [...], "groups": {组: 次数}, "coupled": bool}]``；
    ``coupled=True`` 表示该会话同时用到 ≥2 个候选端点组的工具——拆了就要跨端点，
    而跨端点意味着换 MCP session（lease 会认成另一个持有者）。
    """
    by_session: dict[str, list[dict]] = {}
    for rec in records:
        sid = rec.get("session") or ""
        if not sid:
            continue
        by_session.setdefault(sid, []).append(rec)

    out: list[dict] = []
    for sid, recs in by_session.items():
        recs_sorted = sorted(recs, key=lambda r: str(r.get("ts") or ""))
        tools = [r["tool"] for r in recs_sorted]
        groups: collections.Counter = collections.Counter()
        for name in tools:
            for group, members in PROFILES.items():
                if group != "all" and name in members:
                    groups[group] += 1
                    break
        out.append({"session": sid, "tools": tools, "groups": dict(groups),
                    "coupled": len(groups) >= 2})
    out.sort(key=lambda s: len(s["tools"]), reverse=True)
    return out


def _epoch(rec: dict) -> float:
    try:
        when = datetime.fromisoformat(str(rec.get("ts") or ""))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def group_of(tool: str) -> str:
    """把工具归到一个候选端点组（未知工具返回 ''）。"""
    for name, members in PROFILES.items():
        if name != "all" and tool in members:
            return name
    return ""


def stitch_units(records: list[dict], gap_s: float = 180.0) -> list[list[dict]]:
    """按 ``pid`` + 相邻调用间隔把会话碎片粘回"真实工作单元"。

    为什么必须粘：审计里的 ``session`` 是**连接级**标识，客户端重连就会换新 id
    （2026-11-28 win 上重启后实测如此）。于是一条真实工作流会被切成两个"单组会话"，
    **跨组耦合被系统性低估**——而低估的方向恰好指向"可以拆"，是最危险的偏差。

    ``pid`` 在进程生命周期内不变，所以"同一 pid + 相邻调用间隔 < gap_s"近似一份工作流。
    粘出来的单元数一定 **≤** 原始会话数；两者差距大说明重连频繁，跨组率只能当下界看。
    """
    # 归属键 = (pid, holder)：pid 是**服务端进程**（同一台机器的所有 agent 共享），
    # 只有 holder（acquire 声明的名字）才能把不同 agent 的调用分开。
    by_pid: dict[tuple, list[dict]] = {}
    for rec in records:
        key = (str(rec.get("pid") or "?"), str(rec.get("holder") or ""))
        by_pid.setdefault(key, []).append(rec)

    units: list[list[dict]] = []
    for _key, recs in by_pid.items():
        recs_sorted = sorted(recs, key=_epoch)
        current: list[dict] = []
        last_ts = None
        for rec in recs_sorted:
            ts = _epoch(rec)
            if current and last_ts is not None and (ts - last_ts) > gap_s:
                units.append(current)
                current = []
            current.append(rec)
            last_ts = ts
        if current:
            units.append(current)
    return units


def cut_pairs(records: list[dict], gap_s: float) -> int:
    """同一 (pid, holder) 内因**超过阈值**而被切开的相邻对数——阈值定得对不对看这个数。"""
    buckets: dict[tuple, list[float]] = {}
    for rec in records:
        key = (str(rec.get("pid") or "?"), str(rec.get("holder") or ""))
        buckets.setdefault(key, []).append(_epoch(rec))
    count = 0
    for stamps in buckets.values():
        stamps.sort()
        count += sum(1 for a, b in zip(stamps, stamps[1:]) if (b - a) > gap_s)
    return count


def unit_duration_s(unit: list[dict]) -> float:
    """单元首末调用的时间跨度（秒）。"""
    if not unit:
        return 0.0
    stamps = sorted(_epoch(r) for r in unit)
    return max(0.0, stamps[-1] - stamps[0])


def stitch_health(units: list[list[dict]], session_count: int,
                  max_unit_minutes: float = 30.0,
                  min_ratio: float = 0.3) -> dict:
    """自检：这套"按 pid(+holder) 粘回"的方法**在当前数据密度下还成不成立**。

    判据来自一次真实教训：83 次调用被粘成 3 个单元（比值 3/32≈0.09），每个单元跨多个操作者 ——
    那既不是下界也不是上界，而是"把整段时间当一个单元"的人为产物；用它做决策会得出
    "什么都在跨组"，对"要不要拆端点"没有信息量。

    返回 `{"degraded": bool, "reasons": [...], "ratio": float, "median_unit_s": float}`。
    ``degraded=True`` 时调用方**不应输出跨组结论**。
    """
    reasons: list[str] = []
    ratio = (len(units) / session_count) if session_count else 0.0
    durations = sorted(unit_duration_s(u) for u in units)
    median_s = durations[len(durations) // 2] if durations else 0.0
    if session_count and ratio < min_ratio:
        reasons.append(f"单元数/会话数 = {len(units)}/{session_count} ≈ {ratio:.2f}（< {min_ratio}）"
                       f"——粘成了时间桶，不是工作单元")
    if median_s > max_unit_minutes * 60:
        reasons.append(f"单元时长中位数 {median_s/60:.1f} 分钟（> {max_unit_minutes:g} 分钟）")
    return {"degraded": bool(reasons), "reasons": reasons,
            "ratio": ratio, "median_unit_s": median_s}


def unit_profile(unit: list[dict]) -> dict:
    tools = [r["tool"] for r in unit]
    groups = collections.Counter(g for g in (group_of(t) for t in tools) if g)
    return {"tools": tools, "groups": dict(groups), "coupled": len(groups) >= 2}


def call_count_histogram(records_groups: list[list[dict]]) -> dict[str, int]:
    """按每次会话/单元的调用数分桶：大量 1–2 次的桶多半是重连碎片。"""
    buckets = {"1": 0, "2": 0, "3-5": 0, "6-20": 0, "21+": 0}
    for group in records_groups:
        n = len(group)
        key = ("1" if n == 1 else "2" if n == 2 else "3-5" if n <= 5
               else "6-20" if n <= 20 else "21+")
        buckets[key] += 1
    return buckets


def profile_coverage(by_tool: collections.Counter, tools: set[str]) -> tuple[int, int]:
    """返回 (覆盖的调用数, 该端点需要挂的工具数)。"""
    covered = sum(count for name, count in by_tool.items() if name in tools)
    needed = len({name for name in tools if by_tool.get(name)})
    return covered, needed


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Analyze agent-fleet tool-audit.jsonl")
    ap.add_argument("--path", default=DEFAULT_PATH, help="audit jsonl (default ~/.agent-fleet/tool-audit.jsonl)")
    ap.add_argument("--days", type=float, default=7.0, help="window in days (0 = all)")
    ap.add_argument("--profiles", default="", help="comma list of candidate profiles to score")
    ap.add_argument("--top", type=int, default=25, help="how many tools to list")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    ap.add_argument("--stitch-gap", type=float, default=180.0,
                    help="stitch session fragments when the gap between calls is under N seconds "
                         "of the same pid (default 60; reconnect creates new session ids)")
    ap.add_argument("--sessions", type=int, default=0,
                    help="show the N busiest sessions as tool sequences (0 = off)")
    args = ap.parse_args(argv)

    base = Path(args.path).expanduser()
    files = audit_files(base)
    if not files:
        print(f"没有找到审计文件：{base}\n"
              f"（服务端默认开启；确认设备已重启，或 FLEET_TOOL_AUDIT_PATH 指到别处）",
              file=sys.stderr)
        return 2

    records = filter_days(load_records(files), args.days)
    if not records:
        print(f"窗口内没有记录（文件：{', '.join(str(f) for f in files)}）", file=sys.stderr)
        return 2
    stats = summarize(records)

    if args.json:
        print(json.dumps({
            "files": [str(f) for f in files],
            "window_days": args.days,
            "total": stats["total"],
            "by_day": dict(sorted(stats["by_day"].items())),
            "by_tool": dict(stats["by_tool"].most_common()),
            "failures": dict(stats["failures"].most_common()),
            "slow_2s": dict(stats["slow"].most_common()),
            "latency": stats["latency"],
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"文件：{', '.join(str(f) for f in files)}")
    print(f"窗口：最近 {args.days:g} 天   调用总数：{stats['total']}\n")
    print("按天：")
    for day, count in sorted(stats["by_day"].items()):
        print(f"  {day}  {count:6d}")
    print(f"\n按工具（前 {args.top}；ms 为墙钟，含排队/争用，排序看 p50 不看 max）：")
    for name, count in stats["by_tool"].most_common(args.top):
        share = count / max(1, stats["total"]) * 100
        lat = stats["latency"].get(name, {})
        marks = [f"p50={lat.get('p50', 0)}ms", f"p95={lat.get('p95', 0)}ms"]
        if stats["failures"].get(name):
            marks.append(f"fail={stats['failures'][name]}")
        print(f"  {count:6d}  {share:5.1f}%  {name:<28s} " + "  ".join(marks))

    # 会话 vs 粘贴单元：差距大 = 重连频繁，跨组率只能当下界
    raw_groups: dict[str, list[dict]] = {}
    for rec in records:
        raw_groups.setdefault(rec.get("session") or "(none)", []).append(rec)
    units = stitch_units(records, gap_s=args.stitch_gap)
    with_holder = sum(1 for r in records if r.get("holder"))
    cuts = cut_pairs(records, args.stitch_gap)
    raw_coupled = sum(1 for g in raw_groups.values() if unit_profile(g)["coupled"])
    unit_coupled = sum(1 for u in units if unit_profile(u)["coupled"])
    print(f"\n会话切分（gap≤{args.stitch_gap:g}s 且同 pid 视为同一工作单元）：")
    print(f"  原始会话数 {len(raw_groups)}（其中跨组 {raw_coupled}，{raw_coupled/max(1,len(raw_groups))*100:.1f}%）")
    print(f"  粘贴后单元 {len(units)}（其中跨组 {unit_coupled}，{unit_coupled/max(1,len(units))*100:.1f}%）")
    print(f"  带 holder 的记录 {with_holder}/{len(records)}"
          + ("　⚠ 无 holder 的记录只能按 pid 归并，可能把不同 agent 缝在一起（跨组率上界）"
             if with_holder < len(records) else "　✅ 全部可归属"))
    print(f"  因超过 {args.stitch_gap:g}s 被切开的相邻对：{cuts} 个"
          + ("　⚠ 偏多说明阈值偏小" if cuts > max(3, len(units)) else ""))
    health = stitch_health(units, len(raw_groups))
    print(f"  自检：单元时长中位数 {health['median_unit_s']/60:.1f} 分钟；"
          f"单元/会话 比值 {len(units)}/{len(raw_groups)} ≈ {health['ratio']:.2f}")
    hist = call_count_histogram(units)
    print("  单元调用数分布: " + ", ".join(f"{k}次={v}" for k, v in hist.items()))
    if len(raw_groups) > len(units):
        print("  ⚠ 存在重连碎片（会话数 > 单元数）⇒ **跨组率是下界**，不能读成精确值。")
    if hist["1"] + hist["2"] > len(units) * 0.5 and units:
        print("  ⚠ 过半单元只有 1–2 次调用：多半是碎片而非真实工作流，跨组率同样不可信。")
    per_holder = health_by_holder(records, args.stitch_gap)
    if len(per_holder) > 1:
        print('  分组自检（按 holder；避免「总体正常、个别人被粘成时间桶」）：')
        for row in per_holder:
            flag = "⛔" if row["health"]["degraded"] else "ok"
            print(f"    {flag} {row['scope']:<28s} 单元 {row['units']:2d} / 会话 {row['sessions']:2d}"
                  f" ≈ {row['health']['ratio']:.2f}；时长中位数 {row['health']['median_unit_s']/60:.1f} 分钟")
            for reason in row["health"]["reasons"]:
                print(f"        - {reason}")

    if health["degraded"]:
        print("  ⛔ 粘法在当前密度下**失效**，本次不输出跨组结论：")
        for reason in health["reasons"]:
            print(f"     - {reason}")
        print("     正确读法：在 holder 落地前，按 session 出报告并注明「本次不能回答跨组问题」；"
              "宁可下界偏保守，也不要上界失真。")
    elif any(row["health"]["degraded"] for row in per_holder):
        bad = [row["scope"] for row in per_holder if row["health"]["degraded"]]
        print(f"  ⛔ 全局看似健康，但分组自检失效：{', '.join(bad)} —— 这些组的跨组率不可用。")

    if args.sessions > 0:
        seqs = session_sequences(records)
        if not seqs:
            print("\n（没有 session 字段：审计来自旧版本或 FLEET_TOOL_AUDIT 关闭期间的记录）")
        else:
            coupled = [s for s in seqs if s["coupled"]]
            print(f"\n会话序列（共 {len(seqs)} 个会话；跨 ≥2 组的 {len(coupled)} 个）：")
            for seq in seqs[: args.sessions]:
                flag = "  ⚠ 跨组" if seq["coupled"] else ""
                shown = " → ".join(seq["tools"][:12])
                more = f" …(+{len(seq['tools']) - 12})" if len(seq["tools"]) > 12 else ""
                print(f"  [{seq['session']}] {len(seq['tools']):3d} calls{flag}: {shown}{more}")
            print("\n读法：单个会话内频繁跨组 ⇒ 拆端点会把它拆成多次连接，"
                  "而 lease 绑定 MCP session、剪贴板/前台窗口只有一份 —— 这类任务不适合拆。")

    if args.profiles:
        wanted = [p.strip() for p in args.profiles.split(",") if p.strip()]
        print("\n候选端点覆盖：")
        for name in wanted:
            tools = PROFILES.get(name)
            if tools is None:
                print(f"  {name:12s} 未知候选（可选：{', '.join(sorted(PROFILES))}）")
                continue
            covered, needed = profile_coverage(stats["by_tool"], tools)
            share = covered / max(1, stats["total"]) * 100
            verdict = "值得单开" if share >= 95 else ("只覆盖多数" if share >= 70 else "覆盖不足，别拆")
            suffix = "（参考：粘法失效时该数不宜作结论）" if health["degraded"] else ""
            print(f"  {name:12s} 覆盖 {share:5.1f}% 的调用，需挂 {needed:2d} 个工具  → {verdict}{suffix}")
        print("\n判定建议：覆盖 ≥95% 且工具数明显更少才单开；换端点要换 URL，"
              "频繁换端点比多几个工具更贵。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
