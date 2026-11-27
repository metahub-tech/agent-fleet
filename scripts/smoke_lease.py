#!/usr/bin/env python3
"""Two-session smoke test for the enforced, session-bound device lease.

Runs against a *running* device server (streamable-http) and proves:

1. A acquires; B's `acquire` is refused with A as `current_holder`;
2. B's core tool call is refused with ``{ok: false, reason: "device_leased"}``;
3. A's core call works and **auto-renews** the lease (``last_used_at`` 前进；
   不能用 `idle_seconds == 0`——慢调用返回后 idle 必然大于 0);
4. B's *capability* tool call (e.g. ``human_dom_status`` / ``browser_status``) is
   refused too — capabilities are gated and renew through the same path;
5. A's release frees the device for B immediately.

Read-only by design: only ``get_screen_size`` / ``get_status`` and one light
capability tool are called; nothing is tapped, typed or launched.

Usage:
    python scripts/smoke_lease.py --url http://test-win11:8766/mcp
    python scripts/smoke_lease.py --host test-win11 --port 8766 --json
    python scripts/smoke_lease.py --url http://phone-host:8768/mcp --device <serial>

Requires an environment that has the MCP client SDK (``pip install mcp`` or the
server venv). Exit code: 0 = all checks passed, 1 = failures, 2 = could not connect.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_probe import load_transport as _shared_load_transport
import uuid
from typing import Any, Awaitable, Callable, Optional

CANDIDATE_CAPABILITY_TOOLS = ("human_dom_status", "browser_status")


# --------------------------------------------------------------------------- #
# transport helpers (kept import-light so the pure checks are unit-testable)
# --------------------------------------------------------------------------- #

def _payload(result: Any) -> dict:
    """Normalise a CallToolResult into the tool's dict payload."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    if content:
        text = getattr(content[0], "text", "")
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"_value": parsed}
        except Exception:
            return {"_raw": text}
    return {}


def _renewed(current, baseline) -> bool:
    """判断租约是否被刷新：**比较 last_used_at 是否前进**，而不是 `idle_seconds == 0`。

    真机教训：`human_dom_status` 在有 34 个 profile 时单次调用要 ~4 秒，返回后立刻读
    status，`idle_seconds` 已经是 4 —— 用 "idle==0" 会把**正常续租**判成失败。
    """
    if not current or not baseline:
        return False
    return str(current) > str(baseline)


def _denied(payload: dict) -> bool:
    return payload.get("ok") is False and payload.get("reason") == "device_leased"


async def _pick_capability_tool(call: Callable[..., Awaitable[dict]], explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    caps = await call("list_capabilities")
    available: set[str] = set()
    for cap in caps.get("capabilities", []) or []:
        available.update(cap.get("tools", []) or [])
    for name in CANDIDATE_CAPABILITY_TOOLS:
        if name in available:
            return name
    return None


# --------------------------------------------------------------------------- #
# the checks (pure w.r.t. a `call(session, tool, **args)` coroutine)
# --------------------------------------------------------------------------- #

async def run_checks(
    call_a: Callable[..., Awaitable[dict]],
    call_b: Callable[..., Awaitable[dict]],
    capability_tool: Optional[str],
    holder_prefix: str,
) -> list[dict]:
    holder_a = f"{holder_prefix}-A"
    holder_b = f"{holder_prefix}-B"
    results: list[dict] = []

    def check(name: str, ok: bool, detail: Any) -> None:
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    acquired = await call_a("acquire", holder_name=holder_a)
    check("A acquire", acquired.get("acquired") is True, acquired)

    refused = await call_b("acquire", holder_name=holder_b)
    check(
        "B acquire refused (holder reported)",
        refused.get("acquired") is False and refused.get("current_holder") == holder_a,
        refused,
    )

    denied = await call_b("get_screen_size")
    check("B core tool denied", _denied(denied), denied)

    renew_baseline = (await call_a("get_status")).get("last_used_at")
    allowed = await call_a("get_screen_size")
    check("A core tool allowed", "width" in allowed and "height" in allowed, allowed)

    status_a = await call_a("get_status")
    check("A core call auto-renewed", _renewed(status_a.get("last_used_at"), renew_baseline),
          {"last_used_at": status_a.get("last_used_at"), "baseline": renew_baseline,
           "idle_seconds": status_a.get("idle_seconds")})

    if capability_tool:
        denied_cap = await call_b(capability_tool)
        check(f"B capability tool denied ({capability_tool})", _denied(denied_cap), denied_cap)

        renew_baseline_b = (await call_a("get_status")).get("last_used_at")
        allowed_cap = await call_a(capability_tool)
        check(f"A capability tool allowed ({capability_tool})", not _denied(allowed_cap), {"ok": allowed_cap.get("ok")})

        status_cap = await call_a("get_status")
        check("A capability call auto-renewed", _renewed(status_cap.get("last_used_at"), renew_baseline_b),
              {"last_used_at": status_cap.get("last_used_at"), "baseline": renew_baseline_b,
               "idle_seconds": status_cap.get("idle_seconds")})
    else:
        check("capability-tool assertions", True, "skipped: no gated capability tool on this platform")

    released = await call_a("release", holder_name=holder_a)
    check("A release", released.get("released") is True, released)

    after = await call_b("get_screen_size")
    check("B allowed after release", "width" in after and "height" in after, after)

    b_acquired = await call_b("acquire", holder_name=holder_b)
    check("B acquire after release", b_acquired.get("acquired") is True, b_acquired)

    b_released = await call_b("release", holder_name=holder_b)
    check("B cleanup release", b_released.get("released") is True, b_released)

    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="full MCP endpoint, e.g. http://host:8766/mcp")
    ap.add_argument("--host", help="device host; used with --port to build the URL")
    ap.add_argument("--port", type=int, default=8766, help="device port (default 8766)")
    ap.add_argument("--device", help="serial/alias for multi-device servers (android/ios); passed to core tools")
    ap.add_argument("--capability-tool", help="capability tool to probe (default: auto-detect)")
    ap.add_argument("--holder-prefix", default=f"lease-smoke-{uuid.uuid4().hex[:6]}",
                    help="holder_name prefix for the two test sessions")
    ap.add_argument("--json", action="store_true", help="print machine-readable results")
    return ap.parse_args(argv)


def _url(args: argparse.Namespace) -> str:
    if args.url:
        return args.url
    if not args.host:
        raise SystemExit("need --url or --host")
    return f"http://{args.host}:{args.port}/mcp"


async def _run(url: str, args: argparse.Namespace) -> int:
    transport = _load_transport()
    if transport is None:  # pragma: no cover - environment dependent
        print('ERROR: MCP client SDK not available. Use the server venv, or '
              '`uv run --with "mcp<2" python scripts/smoke_lease.py`.', file=sys.stderr)
        return 2
    from mcp import ClientSession

    def make_call(session):
        async def call(tool: str, **kwargs):
            if args.device and tool not in ("acquire", "release", "list_capabilities", "get_status"):
                kwargs.setdefault("device", args.device)
            return _payload(await session.call_tool(tool, kwargs))
        return call

    try:
        async with transport(url) as _streams1:
            r1, w1 = _streams1[0], _streams1[1]
            async with ClientSession(r1, w1) as s1:
                await s1.initialize()
                call_a = make_call(s1)
                capability = await _pick_capability_tool(call_a, args.capability_tool)
                async with transport(url) as _streams2:
                    r2, w2 = _streams2[0], _streams2[1]
                    async with ClientSession(r2, w2) as s2:
                        await s2.initialize()
                        results = await run_checks(call_a, make_call(s2), capability, args.holder_prefix)
    except Exception as exc:
        print(f"ERROR: cannot run lease smoke against {url}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    failed = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps({"url": url, "capability_tool": capability, "results": results,
                          "passed": len(results) - len(failed), "total": len(results)}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}: {r['detail']}")
        print(f"\nSUMMARY: {len(results) - len(failed)}/{len(results)} passed  ({url})")
    if failed:
        print("FAILED: " + ", ".join(r["check"] for r in failed), file=sys.stderr)
        return 1
    return 0


def _load_transport():
    """返回 streamable-http 连接器（兼容 MCP SDK 1.x/2.x）。

    实现在 `scripts/_mcp_probe.py`——三个验收脚本共用同一份，避免各自实现导致
    同一台设备被不同脚本判成不同结果。
    """
    return _shared_load_transport()


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(_url(args), args))


if __name__ == "__main__":
    sys.exit(main())
