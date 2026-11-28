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
            "slow": slow, "failures": failures}


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


def stitch_units(records: list[dict], gap_s: float = 60.0) -> list[list[dict]]:
    """按 ``pid`` + 相邻调用间隔把会话碎片粘回"真实工作单元"。

    为什么必须粘：审计里的 ``session`` 是**连接级**标识，客户端重连就会换新 id
    （2026-11-28 win 上重启后实测如此）。于是一条真实工作流会被切成两个"单组会话"，
    **跨组耦合被系统性低估**——而低估的方向恰好指向"可以拆"，是最危险的偏差。

    ``pid`` 在进程生命周期内不变，所以"同一 pid + 相邻调用间隔 < gap_s"近似一份工作流。
    粘出来的单元数一定 **≤** 原始会话数；两者差距大说明重连频繁，跨组率只能当下界看。
    """
    by_pid: dict[str, list[dict]] = {}
    for rec in records:
        by_pid.setdefault(str(rec.get("pid") or "?"), []).append(rec)

    units: list[list[dict]] = []
    for pid, recs in by_pid.items():
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
    ap.add_argument("--stitch-gap", type=float, default=60.0,
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
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"文件：{', '.join(str(f) for f in files)}")
    print(f"窗口：最近 {args.days:g} 天   调用总数：{stats['total']}\n")
    print("按天：")
    for day, count in sorted(stats["by_day"].items()):
        print(f"  {day}  {count:6d}")
    print(f"\n按工具（前 {args.top}）：")
    for name, count in stats["by_tool"].most_common(args.top):
        share = count / max(1, stats["total"]) * 100
        marks = []
        if stats["failures"].get(name):
            marks.append(f"fail={stats['failures'][name]}")
        if stats["slow"].get(name):
            marks.append(f"slow≥2s={stats['slow'][name]}")
        extra = ("  [" + ", ".join(marks) + "]") if marks else ""
        print(f"  {count:6d}  {share:5.1f}%  {name}{extra}")

    # 会话 vs 粘贴单元：差距大 = 重连频繁，跨组率只能当下界
    raw_groups: dict[str, list[dict]] = {}
    for rec in records:
        raw_groups.setdefault(rec.get("session") or "(none)", []).append(rec)
    units = stitch_units(records, gap_s=args.stitch_gap)
    raw_coupled = sum(1 for g in raw_groups.values() if unit_profile(g)["coupled"])
    unit_coupled = sum(1 for u in units if unit_profile(u)["coupled"])
    print(f"\n会话切分（gap≤{args.stitch_gap:g}s 且同 pid 视为同一工作单元）：")
    print(f"  原始会话数 {len(raw_groups)}（其中跨组 {raw_coupled}，{raw_coupled/max(1,len(raw_groups))*100:.1f}%）")
    print(f"  粘贴后单元 {len(units)}（其中跨组 {unit_coupled}，{unit_coupled/max(1,len(units))*100:.1f}%）")
    hist = call_count_histogram(units)
    print("  单元调用数分布: " + ", ".join(f"{k}次={v}" for k, v in hist.items()))
    if len(raw_groups) > len(units):
        print("  ⚠ 存在重连碎片（会话数 > 单元数）⇒ **跨组率是下界**，不能读成精确值。")
    if hist["1"] + hist["2"] > len(units) * 0.5 and units:
        print("  ⚠ 过半单元只有 1–2 次调用：多半是碎片而非真实工作流，跨组率同样不可信。")

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
            print(f"  {name:12s} 覆盖 {share:5.1f}% 的调用，需挂 {needed:2d} 个工具  → {verdict}")
        print("\n判定建议：覆盖 ≥95% 且工具数明显更少才单开；换端点要换 URL，"
              "频繁换端点比多几个工具更贵。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
