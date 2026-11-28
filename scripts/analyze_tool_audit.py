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
