#!/usr/bin/env python3
"""重启后验证：证明"**新代码真的进了内存**"，而不只是"服务还活着"。

为什么需要它：`/health` 200、工具数 91、审计有新增行 —— 这三条**旧进程全都满足**
（health 本来 200、工具数本来就是 91、审计本来就在写）。它们只能证明"有个进程在服务"，
证明不了"重启后跑的是新码"。

**唯一定性判据是 pid 变了**：审计每行都带 `pid`，重启会换进程号。所以：

| # | 检查 | 证明什么 |
|---|---|---|
| 1 | `/health` 返回 200 | 服务在监听 |
| 2 | `list_capabilities()` 工具数 == 期望 | 功能面完整 |
| 3 | 审计文件有新行 | 审计中间件在写 |
| 4 | **新行 pid ≠ 重启前 pid** | **新代码进了内存**（关键） |

用法::

    # 重启前先记下 pid 与 git HEAD（回滚要有据可查）
    python3 scripts/probe_multi.py --url http://<host>:<port>/mcp \
        --cases <(echo '[{"tool":"run_shell","args":{"script":"..."}}]')

    # 重启后
    python3 scripts/verify_restart.py --url http://test-win11:8766/mcp \
        --old-pid 266180 --expect-tools 91 --expect-holder

退出码：0 全通过；1 有检查失败；2 连不上/用法错。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_probe import load_transport, payload_of  # noqa: E402

#: 读审计尾部的 PowerShell 片段（设备是 Windows；mac/linux 用 --audit-cmd 覆盖）
WIN_TAIL = ('$p = "$env:USERPROFILE\\.agent-fleet\\tool-audit.jsonl"; '
            'if (Test-Path $p) { Get-Content $p -Tail 5 } else { "" }')


def parse_audit_lines(stdout: str) -> list[dict]:
    """从 `Get-Content -Tail` 的纯文本里解析出审计记录（坏行跳过）。"""
    out: list[dict] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("tool"):
            out.append(rec)
    return out


def latest_pid(records: list[dict]) -> Optional[int]:
    """最后一条记录的 pid（没有则 None）。"""
    for rec in reversed(records):
        pid = rec.get("pid")
        if isinstance(pid, int):
            return pid
    return None


def count_tools(caps: dict) -> int:
    return sum(len(c.get("tools") or []) for c in (caps.get("capabilities") or []))


def health_ok(url: str, timeout_s: float = 5.0) -> tuple[bool, str]:
    """`/health` 探活（把 MCP 路径换掉）。"""
    base = url.rstrip("/")
    if base.endswith("/mcp"):
        base = base[: -len("/mcp")]
    try:
        with urllib.request.urlopen(base + "/health", timeout=timeout_s) as resp:  # noqa: S310
            return resp.status == 200, f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def _read_audit(call, audit_cmd: str) -> str:
    """`call` 已经做过 payload 归一化；**不要**再包一层 payload_of（会把 dict 变成 []）。"""
    payload = await call("run_shell", {"script": audit_cmd})
    if isinstance(payload, dict):
        return str(payload.get("stdout") or "")
    return ""


async def run_checks(url: str, old_pid: Optional[int], expect_tools: Optional[int],
                     expect_holder: bool, audit_cmd: str) -> list[dict]:
    results: list[dict] = []

    def add(check: str, ok: bool, detail: str) -> None:
        results.append({"check": check, "ok": bool(ok), "detail": detail})

    ok, detail = health_ok(url)
    add("/health 200", ok, detail)

    transport = load_transport()
    if transport is None:
        add("list_capabilities", False, "MCP client SDK 不可用")
        return results
    from mcp import ClientSession

    async with transport(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool: str, args: dict) -> Any:
                return payload_of(await session.call_tool(tool, args))

            caps = await call("list_capabilities", {})
            tools = count_tools(caps if isinstance(caps, dict) else {})
            add("工具数", expect_tools is None or tools == expect_tools,
                f"{tools}（期望 {expect_tools if expect_tools is not None else '任意'}）")

            # 触发一次调用，保证有"新行"
            await call("get_status", {})
            stdout = await _read_audit(call, audit_cmd)
            records = parse_audit_lines(stdout)
            pid = latest_pid(records)
            add("审计有新行", bool(records), f"{len(records)} 行（tail 5）")
            add("新码进内存（pid 变化）", old_pid is None or (pid is not None and pid != old_pid),
                f"重启后 pid={pid}，重启前 pid={old_pid}")
            if expect_holder:
                has_holder = any("holder" in r for r in records)
                add("holder 字段落地", has_holder,
                    "已出现" if has_holder else "未出现——说明跑的仍是旧码或该会话未 acquire")
    return results


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a device restart actually loaded new code")
    ap.add_argument("--url", required=True, help="e.g. http://test-win11:8766/mcp")
    ap.add_argument("--old-pid", type=int, default=None,
                    help="pid observed BEFORE the restart (the key evidence)")
    ap.add_argument("--expect-tools", type=int, default=None, help="expected tool count, e.g. 91")
    ap.add_argument("--expect-holder", action="store_true",
                    help="require the holder field in the new audit lines")
    ap.add_argument("--audit-cmd", default=WIN_TAIL,
                    help="command run on the device to print the audit tail")
    args = ap.parse_args(argv)

    try:
        results = asyncio.run(asyncio.wait_for(
            run_checks(args.url, args.old_pid, args.expect_tools,
                       args.expect_holder, args.audit_cmd), timeout=120))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    for row in results:
        print(("PASS" if row["ok"] else "FAIL"), row["check"], "|", row["detail"])
    failed = [r for r in results if not r["ok"]]
    print(f"\nSUMMARY: {len(results) - len(failed)}/{len(results)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
