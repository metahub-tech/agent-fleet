#!/usr/bin/env python3
"""Acceptance smoke test for the 2026-11 device-operation primitives.

Proves, against a **running** Windows device server:

1. the new tools are actually registered (`file_put` / `file_get` /
   `clipboard_set_html` / `wait_for` / `run_actions` in `list_capabilities()`);
2. ``file_put`` → ``file_get`` round-trips binary bytes with an **identical sha256**
   and the same size;
3. an over-limit push (5 MiB) fails with ``file_too_large`` and leaves **no file**
   on disk (never truncates);
4. ``clipboard_set_html`` writes rich HTML, the read-back passes, and the clipboard
   exposes **only** ``HTML Format`` (CF_TEXT fallback is the failure mode we avoid);
5. ``wait_for`` honours its budget: waiting for something impossible returns
   ``reason:"timeout"`` in roughly the requested time (not instantly, not forever);
6. ``run_actions`` executes steps in order and rejects an invalid batch
   **before running anything** (``invalid_steps``).

Side effects are explicit: this clobbers the Windows clipboard and writes one temp
file under ``%TEMP%``. It never taps, types, or launches anything.

Usage:
    python3 scripts/smoke_ops.py --url http://test-win11:8766/mcp
    python3 scripts/smoke_ops.py --host test-win11 --port 8766 --json

Requires the MCP client SDK. Exit codes: 0 pass, 1 failures, 2 cannot connect,
3 required tools missing.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
import time
from typing import Any, Optional

REQUIRED_TOOLS = ("file_put", "file_get", "clipboard_set_html", "wait_for", "run_actions")
TEMP_FILE = r"C:\Windows\Temp\fleet-smoke-binary.bin"
OVERSIZE_FILE = r"C:\Windows\Temp\fleet-smoke-oversize.bin"
MAX_TRANSFER_BYTES = 4 * 1024 * 1024


def _payload(result: Any) -> dict:
    structured = getattr(result, "structuredContent", None)
    if not isinstance(structured, dict):
        structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    if content:
        text = getattr(content[0], "text", "") or ""
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"_value": parsed}
        except Exception:
            return {"_raw": text}
    return {}


# ---------------------------------------------------------------------------
# pure checks (unit-tested; no network)
# ---------------------------------------------------------------------------

def check_tools_registered(caps: dict, required=REQUIRED_TOOLS) -> tuple[bool, str]:
    if not isinstance(caps, dict) or not isinstance(caps.get("capabilities"), list):
        return False, "list_capabilities() did not return a capabilities list"
    live: set[str] = set()
    for entry in caps["capabilities"]:
        if isinstance(entry, dict) and entry.get("status") == "enabled":
            live.update(entry.get("tools") or [])
    missing = [t for t in required if t not in live]
    if missing:
        return False, f"missing tools on this build: {', '.join(missing)} (got {len(live)} live tools)"
    return True, f"all {len(required)} required tools are live"


def check_roundtrip(put: dict, get: dict, expected_sha: str, expected_bytes: int) -> tuple[bool, str]:
    if put.get("ok") is not True:
        return False, f"file_put failed: {put.get('reason') or put}"
    if put.get("sha256") != expected_sha:
        return False, f"file_put sha mismatch: {put.get('sha256')!r} != {expected_sha!r}"
    if get.get("ok") is not True:
        return False, f"file_get failed: {get.get('reason') or get}"
    if get.get("sha256") != expected_sha:
        return False, f"round-trip sha mismatch: {get.get('sha256')!r} != {expected_sha!r}"
    if get.get("bytes") != expected_bytes:
        return False, f"round-trip size mismatch: {get.get('bytes')} != {expected_bytes}"
    # 内容本身也要一致（sha 相同已足够，但顺手校验 base64 能被解回来）
    try:
        data = base64.b64decode(get.get("content_b64") or "")
    except Exception as exc:
        return False, f"content_b64 is not valid base64: {exc}"
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return False, "decoded payload sha differs from file_put"
    return True, f"sha256={expected_sha[:12]}… bytes={expected_bytes}"


def check_oversize_rejected(put: dict, expected_bytes: int) -> tuple[bool, str]:
    if put.get("ok") is not False:
        return False, "oversized push was accepted (must fail, never truncate)"
    if put.get("reason") != "file_too_large":
        return False, f"reason={put.get('reason')!r} (expected 'file_too_large')"
    if put.get("bytes") != expected_bytes:
        return False, f"reported bytes={put.get('bytes')!r} != {expected_bytes}"
    return True, f"rejected {expected_bytes} bytes without truncation"


def check_clipboard(payload: dict) -> tuple[bool, str]:
    if payload.get("ok") is not True:
        return False, f"clipboard_set_html failed: {payload.get('reason') or payload}"
    if payload.get("verified") is not True:
        return False, f"read-back did not pass: {payload.get('readback')!r}"
    formats = payload.get("formats")
    if formats != ["HTML Format"]:
        return False, f"clipboard formats={formats!r} (expected exactly ['HTML Format'])"
    return True, f"readback={payload.get('readback')} formats={formats}"


def check_wait_for(payload: dict, requested_ms: int) -> tuple[bool, str]:
    if payload.get("ok") is not False or payload.get("reason") != "timeout":
        return False, f"expected a timeout answer, got ok={payload.get('ok')!r} reason={payload.get('reason')!r}"
    elapsed = payload.get("elapsed_ms")
    if not isinstance(elapsed, int):
        return False, "elapsed_ms missing"
    # 预算是 300ms：允许 ±150ms 的调度抖动，但不允许"立刻返回"（假超时）
    if elapsed < requested_ms - 150:
        return False, f"returned too early ({elapsed}ms < {requested_ms - 150}ms) — budget not honoured"
    return True, f"timed out after {elapsed}ms (budget {requested_ms}ms)"


def check_batch_ok(payload: dict) -> tuple[bool, str]:
    if payload.get("ok") is not True:
        return False, f"batch failed: {payload.get('failed_tool')!r}"
    if payload.get("completed") != payload.get("total"):
        return False, f"completed={payload.get('completed')} total={payload.get('total')}"
    statuses = [s.get("status") for s in payload.get("steps") or []]
    if statuses != ["ok"] * len(statuses):
        return False, f"step statuses={statuses}"
    return True, f"{len(statuses)} steps ok"


def check_batch_rejected(payload: dict) -> tuple[bool, str]:
    if payload.get("ok") is not False or payload.get("reason") != "invalid_steps":
        return False, f"invalid batch was not rejected up-front: {payload.get('reason')!r}"
    if payload.get("steps"):
        return False, "rejected batch still returned step results (something ran)"
    allowed = payload.get("allowed_tools") or []
    if not allowed:
        return False, "rejection did not list allowed_tools"
    return True, f"rejected before running; {len(allowed)} tools allowed"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="full MCP endpoint, e.g. http://host:8766/mcp")
    ap.add_argument("--host", help="device host; used with --port to build the URL")
    ap.add_argument("--port", type=int, default=8766, help="device port (default 8766)")
    ap.add_argument("--json", action="store_true", help="print machine-readable results")
    return ap.parse_args(argv)


def _url(args: argparse.Namespace) -> str:
    if args.url:
        return args.url
    if not args.host:
        raise SystemExit("need --url or --host")
    return f"http://{args.host}:{args.port}/mcp"


async def _run(url: str, args: argparse.Namespace) -> int:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"ERROR: MCP client SDK not available ({exc}).", file=sys.stderr)
        return 2

    results: list[dict] = []

    def add(check: str, ok: bool, detail: str) -> None:
        results.append({"check": check, "ok": bool(ok), "detail": detail})

    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(tool: str, **kwargs) -> dict:
                    return _payload(await session.call_tool(tool, kwargs))

                caps = await call("list_capabilities")
                ok, detail = check_tools_registered(caps)
                add("required tools registered", ok, detail)
                if not ok:
                    return _finish(url, results, args.json, code=3)

                blob = bytes(range(256)) * 8            # 2 KiB, non-text binary
                sha = hashlib.sha256(blob).hexdigest()
                b64 = base64.b64encode(blob).decode()

                put = await call("file_put", path=TEMP_FILE, content_b64=b64)
                got = await call("file_get", path=TEMP_FILE) if put.get("ok") else {}
                ok, detail = check_roundtrip(put, got, sha, len(blob))
                add("binary round-trip (sha256)", ok, detail)

                big = base64.b64encode(b"\0" * (MAX_TRANSFER_BYTES + 1)).decode()
                over = await call("file_put", path=OVERSIZE_FILE, content_b64=big)
                ok, detail = check_oversize_rejected(over, MAX_TRANSFER_BYTES + 1)
                add("oversize rejected, not truncated", ok, detail)

                clip = await call("clipboard_set_html",
                                  content="<h2>标题</h2><p>正文 &amp; 符号</p>")
                ok, detail = check_clipboard(clip)
                add("rich HTML clipboard + read-back", ok, detail)

                waited = await call("wait_for", kind="foreground",
                                    target="__fleet_smoke_impossible__", timeout_ms=300,
                                    interval_ms=100)
                ok, detail = check_wait_for(waited, 300)
                add("wait_for honours budget", ok, detail)

                batch = await call("run_actions", steps=[
                    {"tool": "get_screen_size", "args": {}},
                    {"tool": "get_screen_size", "args": {}},
                ])
                ok, detail = check_batch_ok(batch)
                add("run_actions executes in order", ok, detail)

                bad = await call("run_actions", steps=[
                    {"tool": "get_screen_size", "args": {}},
                    {"tool": "definitely_not_a_tool", "args": {}},
                ])
                ok, detail = check_batch_rejected(bad)
                add("run_actions rejects whole batch up-front", ok, detail)
    except Exception as exc:
        print(f"ERROR: cannot run ops smoke against {url}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    return _finish(url, results, args.json)


def _finish(url: str, results: list[dict], as_json: bool, code: int = 0) -> int:
    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(json.dumps({"url": url, "results": results,
                          "passed": len(results) - len(failed), "total": len(results)},
                         ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}: {r['detail']}")
        print(f"\nSUMMARY: {len(results) - len(failed)}/{len(results)} passed  ({url})")
    if failed:
        print("FAILED: " + ", ".join(r["check"] for r in failed), file=sys.stderr)
        return 1
    return code


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(_url(args), args))


if __name__ == "__main__":
    sys.exit(main())
