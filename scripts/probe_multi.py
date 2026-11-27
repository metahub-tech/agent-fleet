#!/usr/bin/env python3
"""在**一个** MCP 会话里按顺序打 N 个工具调用，把原始 payload 原样吐出来。

**它不做事判断**：不断言、不判定成功/失败、不设退出码分级。它只负责"问一句、拿回来"。
所以它和 `smoke_ops` / `smoke_devtools` **不是二选一**：

| 目的 | 用哪个 |
|---|---|
| 验收（有判据、要 exit code、要进 CI） | `scripts/smoke_ops.py` / `scripts/smoke_devtools.py` |
| 定位（这条到底返回什么形状 / 某个工具在现场什么表现） | **本脚本** |

为什么需要它：B 组那些读数（`cdp_port` / `list_tabs` / `eval_in_profile` / `clipboard_set_html` /
`dump_ui` / `find_elements` …）都需要"同一会话里连着做几件事"；一例一进程会丢掉会话状态
（租约、session default、CDP 连接）。而且**输出是 ASCII JSON**，PowerShell 的 GBK 控制台
不会把中文 payload 重新编码成乱码。

用法（在**设备上**跑；CDP 类结果要连设备本地的 `127.0.0.1` 调试端口）::

    python scripts/probe_multi.py --url http://127.0.0.1:8767/mcp --cases cases.json
    python scripts/probe_multi.py --url … --cases cases.json --out out.json

`cases.json`（数组；每条一个工具调用）::

    [
      {"label": "cdp_port", "tool": "cdp_port", "args": {"profile": "~/.fleet/publisher"}},
      {"label": "background eval", "tool": "eval_in_profile",
       "args": {"profile": "~/.fleet/publisher", "js": "1",
                "url_part": "appmsgid=100000037", "activate": false}}
    ]

每个用例打印一行 JSON；`--out` 另存整份列表（UTF-8、不转义）。`--sample` 可生成一份示例 cases。

出处：本工具由 `agent:device-operator-lead` 在
`labs/2026-11-28-win-p0p1-acceptance` 中首先实现（该 lab §15 有说明），此处按仓库脚本规范
做了零依赖化（复用 `_mcp_probe`）与 CLI 补齐。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_probe import TRANSPORT_HINT, load_transport, payload_of  # noqa: E402

#: `--sample` 生成的最小可用 cases（不触碰真账号状态：只读类调用）
SAMPLE_CASES = [
    {"label": "build identity", "tool": "list_capabilities", "args": {}},
    {"label": "screen size", "tool": "get_screen_size", "args": {}},
]


def resolve_timeout(value: Any) -> float:
    """整体超时（秒）：非法值回落 180s，小于 5s 抬到 5s。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 180.0
    return max(5.0, seconds)


async def run_cases(url: str, cases: list[dict]) -> list[dict]:
    """一个会话里按顺序执行；每条记录 `{label, tool, ms, payload|error}`。"""
    transport = load_transport()
    if transport is None:
        raise RuntimeError(TRANSPORT_HINT)

    from mcp import ClientSession

    results: list[dict] = []
    async with transport(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            for case in cases:
                tool = case.get("tool") or ""
                label = case.get("label") or tool
                started = time.monotonic()
                try:
                    raw = await session.call_tool(tool, case.get("args") or {})
                    results.append({
                        "label": label, "tool": tool,
                        "ms": int((time.monotonic() - started) * 1000),
                        "payload": payload_of(raw),
                    })
                except Exception as exc:  # noqa: BLE001 - 探测工具要如实记录，不中断后续用例
                    results.append({
                        "label": label, "tool": tool,
                        "ms": int((time.monotonic() - started) * 1000),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
    return results


def load_cases(path: str) -> list[dict]:
    """读 cases 文件；只接受"数组，元素是带 tool 的对象"。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("cases 必须是非空数组")
    for index, case in enumerate(data):
        if not isinstance(case, dict) or not case.get("tool"):
            raise ValueError(f"cases[{index}] 缺少 tool")
    return data


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Run several MCP tool calls in ONE session and dump raw payloads "
                    "(no assertions, no exit-code grading).",
    )
    ap.add_argument("--url", default="", help="e.g. http://127.0.0.1:8767/mcp")
    ap.add_argument("--cases", default="", help="JSON file: [{label, tool, args}]")
    ap.add_argument("--out", default="", help="optional path for the full result list (UTF-8)")
    ap.add_argument("--sample", action="store_true",
                    help="print a minimal sample cases file and exit")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="overall wall-clock budget in seconds (default 180; min 5)")
    ap.add_argument("--json", action="store_true", help="print the whole list instead of one line per case")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.sample:
        print(json.dumps(SAMPLE_CASES, ensure_ascii=False, indent=1))
        return 0
    if not args.url:
        print("ERROR: --url is required (e.g. http://127.0.0.1:8767/mcp)", file=sys.stderr)
        return 2
    if not args.cases:
        print("ERROR: --cases is required (or use --sample to see the shape)", file=sys.stderr)
        return 2

    try:
        cases = load_cases(args.cases)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: bad --cases file: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    timeout = resolve_timeout(args.timeout)
    try:
        results = asyncio.run(asyncio.wait_for(run_cases(args.url, cases), timeout=timeout))
    except asyncio.TimeoutError:
        print(f"ERROR: run exceeded the overall budget ({timeout:g}s)", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cannot run probe against {args.url}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, ensure_ascii=True, default=str, indent=1))
    else:
        for row in results:
            print(json.dumps(row, ensure_ascii=True, default=str))
    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
