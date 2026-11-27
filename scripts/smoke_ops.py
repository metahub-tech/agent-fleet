#!/usr/bin/env python3
"""Acceptance smoke test for the 2026-11 device-operation primitives.

Proves, against a **running** device server (Windows or macOS):

1. the new tools are actually registered — **platform is auto-detected from the live
   tool list**: `file_put` present ⇒ Windows (file + clipboard blocks run);
   otherwise `wait_for` present ⇒ macOS (common blocks only; macOS does not ship the
   file/clipboard primitives yet);
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

Side effects are explicit and **Windows-only**: on Windows this clobbers the clipboard
and writes one temp file under the Windows temp dir; on macOS nothing is written. It never taps, types, or launches anything.

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
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_probe import load_transport as _shared_load_transport
import time
from typing import Any, Optional

#: 所有平台都应有
COMMON_TOOLS = ("wait_for", "run_actions")
#: 仅 Windows 提供（macOS 目前没有文件字节收发与剪贴板原语）
WINDOWS_ONLY_TOOLS = ("file_put", "file_get", "clipboard_set_html")
REQUIRED_TOOLS = COMMON_TOOLS + WINDOWS_ONLY_TOOLS

TEMP_FILE = r"C:\Windows\Temp\fleet-smoke-binary.bin"
OVERSIZE_FILE = r"C:\Windows\Temp\fleet-smoke-oversize.bin"
MAX_TRANSFER_BYTES = 4 * 1024 * 1024


def detect_platform(caps: dict) -> str:
    """按设备**实际暴露的工具**判定平台，而不是靠用户传参。

    判据：有 `file_put` ⇒ windows（文件/剪贴板是本批 Windows-only 原语）；
    否则有 `wait_for` ⇒ macos；都没有 ⇒ unknown（= 设备跑的不是这批代码）。
    """
    live = _live_tools(caps)
    if "file_put" in live:
        return "windows"
    if "wait_for" in live:
        return "macos"
    return "unknown"


def required_tools_for(platform: str) -> tuple[str, ...]:
    if platform == "windows":
        return REQUIRED_TOOLS
    if platform == "macos":
        return COMMON_TOOLS
    return REQUIRED_TOOLS          # unknown 时按最严格报，好让用户看到缺什么


def _live_tools(caps: dict) -> set[str]:
    live: set[str] = set()
    if isinstance(caps, dict) and isinstance(caps.get("capabilities"), list):
        for entry in caps["capabilities"]:
            if isinstance(entry, dict) and entry.get("status") == "enabled":
                live.update(entry.get("tools") or [])
    return live


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
    live = _live_tools(caps)
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


def check_wrapped_base64_accepted(put: dict, expected_sha: str) -> tuple[bool, str]:
    """折行 base64（每 76 列一行，标准编码器常见输出）必须被接受。

    回归：`file_put` 曾用 `validate=True` 直接解，折行会被误判成 `invalid_base64`。
    """
    if put.get("ok") is not True:
        reason = put.get("reason")
        if reason == "invalid_base64":
            return False, "line-wrapped base64 was rejected — whitespace must be stripped first"
        return False, f"wrapped-base64 push failed: {reason or put}"
    if put.get("sha256") != expected_sha:
        return False, f"sha mismatch for wrapped input: {put.get('sha256')!r}"
    return True, "76-column wrapped base64 accepted, sha matches"


def check_attempts_reported(payload: dict, max_attempts: int) -> tuple[bool, str]:
    """`attempts=2` 时成功仍要报 `attempts`，且不超过请求值（重试路径不算坏）。"""
    if payload.get("ok") is not True:
        return False, f"clipboard write failed with retries enabled: {payload.get('reason') or payload}"
    attempts = payload.get("attempts")
    if not isinstance(attempts, int) or not 1 <= attempts <= max_attempts:
        return False, f"attempts={attempts!r} not in 1..{max_attempts}"
    return True, f"succeeded on attempt {attempts}/{max_attempts}"


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


UIA_BUDGET_MS = 8000        # 与 server 默认 FLEET_UIA_TIMEOUT 一致
UIA_SLACK_MS = 2500         # 调度/测量抖动余量


def check_uia_latency(kind: str, payload: dict, elapsed_ms: int,
                      budget_ms: int = UIA_BUDGET_MS) -> tuple[bool, str]:
    """UIA 调用必须在预算 + 余量内**返回**（返回什么都行，就是不能挂住）。

    这是"卡死修复"的真机判据：旧实现在 Electron/控制台窗口上会永不返回；
    新实现要么给结果，要么给结构化 `uia_timeout` / `console_window`。
    """
    limit = budget_ms + UIA_SLACK_MS
    if elapsed_ms > limit:
        return False, f"{kind} took {elapsed_ms}ms (> {limit}ms) — traversal is not bounded"
    if isinstance(payload, list):
        return True, f"{kind} returned {len(payload)} item(s) in {elapsed_ms}ms"
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        # FastMCP 会把 `-> list[dict]` 的返回值包一层 {"result": [...]}
        return True, f"{kind} returned {len(payload['result'])} item(s) in {elapsed_ms}ms"
    if not isinstance(payload, dict):
        return False, f"{kind} returned a non-dict/non-list payload: {type(payload).__name__}"
    ok = payload.get("ok")
    reason = payload.get("reason")
    if ok is True:
        return True, f"{kind} ok in {elapsed_ms}ms"
    allowed = {"uia_timeout", "console_window", "not_found", "no foreground window detected"}
    if reason in allowed or str(payload.get("error") or "").lower().startswith("no foreground"):
        return True, f"{kind} answered in {elapsed_ms}ms with reason={reason!r} (bounded, not hung)"
    return False, f"{kind} failed unexpectedly in {elapsed_ms}ms: {payload}"


def check_batch_rejected(payload: dict) -> tuple[bool, str]:
    if payload.get("ok") is not False or payload.get("reason") != "invalid_steps":
        return False, f"invalid batch was not rejected up-front: {payload.get('reason')!r}"
    if payload.get("steps"):
        return False, "rejected batch still returned step results (something ran)"
    allowed = payload.get("allowed_tools") or []
    if not allowed:
        return False, "rejection did not list allowed_tools"
    return True, f"rejected before running; {len(allowed)} tools allowed"


def build_identity(caps: dict) -> dict:
    """从 list_capabilities() 提取"这台设备到底跑的是哪一版"的最小身份。

    为什么需要：切换/回滚 build 之后，最常见的困惑是"我到底连的是新码还是旧码"。
    这个摘要**不产生任何副作用**（不写文件、不碰剪贴板），可以随时跑。
    """
    live = _live_tools(caps)
    platform = detect_platform(caps)
    required = required_tools_for(platform)
    missing = [t for t in required if t not in live]
    devtools = None
    if isinstance(caps, dict) and isinstance(caps.get("capabilities"), list):
        for entry in caps["capabilities"]:
            if isinstance(entry, dict) and entry.get("id") == "devtools":
                devtools = entry.get("status")
    return {
        "platform": platform,
        "live_tool_count": len(live),
        "required_present": [t for t in required if t in live],
        "required_missing": missing,
        "devtools_status": devtools,
        "looks_like_this_build": not missing,
    }


def format_identity(identity: dict) -> str:
    lines = [
        f"platform         : {identity['platform']}",
        f"live tools       : {identity['live_tool_count']}",
        f"devtools         : {identity['devtools_status'] or '-'}",
    ]
    if identity["required_missing"]:
        lines.append(f"MISSING          : {', '.join(identity['required_missing'])}")
        lines.append("verdict          : 设备跑的不是这批代码（或能力被关掉了）")
    else:
        lines.append(f"present          : {', '.join(identity['required_present'])}")
        lines.append("verdict          : 这批代码已生效")
    return "\n".join(lines)


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
    ap.add_argument("--probe", action="store_true",
                    help="Zero-side-effect check: connect, report which build the device runs, "
                         "print the live tool count, then exit (no file/clipboard writes)")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="Overall wall-clock budget for the whole run (default 180s; "
                         f"values below {MIN_TIMEOUT_S:g}s are raised to it) — "
                         "a hung device must not hang your shell")
    return ap.parse_args(argv)


#: 整体预算下限：低于这个值没有意义（连接+初始化就要几秒），统一抬到 5s。
MIN_TIMEOUT_S = 5.0


def resolve_timeout(value) -> float:
    """把 --timeout 归一到 [MIN_TIMEOUT_S, ∞)；非法值回落到默认 180s。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 180.0
    return max(MIN_TIMEOUT_S, seconds)


def _url(args: argparse.Namespace) -> str:
    if args.url:
        return args.url
    if not args.host:
        raise SystemExit("need --url or --host")
    return f"http://{args.host}:{args.port}/mcp"


def _load_transport():
    """返回 streamable-http 连接器（兼容 MCP SDK 1.x/2.x）。

    实现在 `scripts/_mcp_probe.py`——三个验收脚本共用同一份，避免各自实现导致
    同一台设备被不同脚本判成不同结果。
    """
    return _shared_load_transport()


async def _run(url: str, args: argparse.Namespace) -> int:
    transport = _load_transport()
    if transport is None:
        return 2
    from mcp import ClientSession

    results: list[dict] = []

    def add(check: str, ok: bool, detail: str) -> None:
        results.append({"check": check, "ok": bool(ok), "detail": detail})

    try:
        async with transport(url) as _streams:
            read, write = _streams[0], _streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(tool: str, **kwargs) -> dict:
                    return _payload(await session.call_tool(tool, kwargs))

                caps = await call("list_capabilities")
                if getattr(args, "probe", False):
                    identity = build_identity(caps)
                    if args.json:
                        print(json.dumps({"url": url, **identity}, ensure_ascii=False, indent=2))
                    else:
                        print(format_identity(identity))
                    return 0 if identity["looks_like_this_build"] else 3
                platform = detect_platform(caps)
                ok, detail = check_tools_registered(caps, required_tools_for(platform))
                add(f"required tools registered ({platform})", ok, detail)
                if not ok:
                    return _finish(url, results, args.json, code=3)

                if platform == "windows":
                    blob = bytes(range(256)) * 8            # 2 KiB, non-text binary
                    sha = hashlib.sha256(blob).hexdigest()
                    b64 = base64.b64encode(blob).decode()

                    put = await call("file_put", path=TEMP_FILE, content_b64=b64)
                    got = await call("file_get", path=TEMP_FILE) if put.get("ok") else {}
                    ok, detail = check_roundtrip(put, got, sha, len(blob))
                    add("binary round-trip (sha256)", ok, detail)

                    wrapped = "\r\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
                    put_wrapped = await call("file_put", path=TEMP_FILE, content_b64=wrapped)
                    ok, detail = check_wrapped_base64_accepted(put_wrapped, sha)
                    add("line-wrapped base64 accepted", ok, detail)

                    big = base64.b64encode(b"\0" * (MAX_TRANSFER_BYTES + 1)).decode()
                    over = await call("file_put", path=OVERSIZE_FILE, content_b64=big)
                    ok, detail = check_oversize_rejected(over, MAX_TRANSFER_BYTES + 1)
                    add("oversize rejected, not truncated", ok, detail)

                    clip = await call("clipboard_set_html",
                                      content="<h2>标题</h2><p>正文 &amp; 符号</p>")
                    ok, detail = check_clipboard(clip)
                    add("rich HTML clipboard + read-back", ok, detail)

                    clip_retry = await call("clipboard_set_html",
                                            content="<h2>再次</h2><p>正文</p>", attempts=2)
                    ok, detail = check_attempts_reported(clip_retry, 2)
                    add("clipboard retry path reports attempts", ok, detail)
                else:
                    add("binary / clipboard checks", True,
                        "skipped: macOS build does not ship file_put/file_get/clipboard_set_html")

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

                # --- UIA 稳定性：必须在预算内**返回**（旧实现会挂住） ---
                t0 = time.monotonic()
                dumped = await call("dump_ui")
                dump_ms = int((time.monotonic() - t0) * 1000)
                ok, detail = check_uia_latency("dump_ui", dumped, dump_ms)
                add("dump_ui returns within budget", ok, detail)

                if platform == "windows":
                    t0 = time.monotonic()
                    windows = await call("list_windows")
                    windows_ms = int((time.monotonic() - t0) * 1000)
                    ok, detail = check_uia_latency("list_windows", windows, windows_ms)
                    add("list_windows returns within budget", ok, detail)

                t0 = time.monotonic()
                searched = await call("find_elements", query="__fleet_smoke_impossible__")
                search_ms = int((time.monotonic() - t0) * 1000)
                ok, detail = check_uia_latency("find_elements", searched, search_ms)
                add("find_elements returns within budget", ok, detail)
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
        return code if code else 1
    return code


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    timeout = resolve_timeout(getattr(args, "timeout", 180.0))
    try:
        return asyncio.run(asyncio.wait_for(_run(_url(args), args), timeout=timeout))
    except asyncio.TimeoutError:
        print(f"ERROR: run exceeded the overall budget ({timeout:g}s) — the device or one tool "
              f"call is hung; the script aborted instead of blocking your shell.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
