#!/usr/bin/env python3
"""Acceptance smoke test for the opt-in ``devtools`` capability (CDP primitives).

Runs against a *running* device server and proves the contract device-operator
asked for, without touching click/type paths:

1. ``list_capabilities()`` reports ``devtools`` as ``enabled``;
2. ``cdp_port`` reports a live port with a real ``probe_ms`` (or an actionable
   ``reason`` — ``port_file_missing`` means "open the browser first");
3. ``list_tabs`` returns the object shape, valid ``visibility`` enum, full URLs,
   and answers **within 1s** (the "must not hang on a frozen tab" criterion);
4. ``eval_in_profile`` can read ``document.visibilityState``;
5. an oversized result comes back as ``result_too_large`` and is **never
   truncated** (no ``value`` key in the failure);
6. ``activate_tab`` on a known URL succeeds and a follow-up ``list_tabs`` sees it.

Deliberately **read-only**: it never opens/closes tabs and never types. The
"background frozen tab" negative case needs two tabs, so it is not automated
here — it is a manual step in docs/platforms/windows.md §7.8.

Usage:
    python3 scripts/smoke_devtools.py --url http://test-win11:8766/mcp --profile "~/.fleet/op-xxx"
    python3 scripts/smoke_devtools.py --host test-win11 --port 8766 --profile "~/.fleet/op-xxx" --json

Requires the MCP client SDK (`pip install mcp` or the server venv).
Exit code: 0 = passed, 1 = failures, 2 = could not connect,
3 = capability not enabled on the device.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Optional

VISIBILITY_VALUES = ("visible", "hidden", "unknown")
LIST_TABS_HANG_LIMIT_MS = 1000


# --------------------------------------------------------------------------- #
# transport helpers (import-light so the checks stay unit-testable)
# --------------------------------------------------------------------------- #

def _payload(result: Any) -> dict:
    """Normalise a CallToolResult into the tool's dict payload."""
    structured = getattr(result, "structuredContent", None)
    if not isinstance(structured, dict):
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


# --------------------------------------------------------------------------- #
# pure checks: (ok, detail) — no network, unit-tested
# --------------------------------------------------------------------------- #

def check_capability_enabled(caps: dict) -> tuple[bool, str]:
    if not isinstance(caps, dict) or not isinstance(caps.get("capabilities"), list):
        return False, "list_capabilities() did not return a capabilities list"
    for entry in caps["capabilities"]:
        if isinstance(entry, dict) and entry.get("id") == "devtools":
            status = entry.get("status")
            if status == "enabled":
                tools = entry.get("tools") or []
                return True, f"devtools enabled with {len(tools)} tool(s)"
            return False, (f"devtools is {status!r} on this host — add \"devtools\" to "
                           "[capabilities].enabled (platform.toml or .fleet/config.toml) "
                           "and restart the server")
    return False, "devtools is not registered on this device (older server build?)"


def check_cdp_port(payload: dict) -> tuple[bool, str]:
    reason = payload.get("reason")
    if payload.get("ok") is True and payload.get("alive") is True:
        port = payload.get("port")
        if not isinstance(port, int) or port <= 0:
            return False, f"alive=true but port={port!r}"
        if not str(payload.get("ws_url") or "").startswith("ws://"):
            return False, f"alive=true but ws_url={payload.get('ws_url')!r}"
        if not isinstance(payload.get("probe_ms"), int):
            return False, "probe_ms missing (must be reported on success too)"
        return True, f"port={port} browser={payload.get('browser')!r} probe_ms={payload['probe_ms']}"
    if reason == "port_file_missing":
        return False, "no browser for this profile — run human_browser_open(profile=…) first"
    if reason == "version_probe_failed":
        age = payload.get("port_file_age_ms")
        note = payload.get("note")
        return False, f"version probe failed (port_file_age_ms={age!r} note={note!r})"
    if reason == "handshake_timeout":
        return False, "endpoint alive but no reachable ws_url (starting up? retry)"
    return False, f"unexpected payload: {payload}"


def check_list_tabs(payload: dict, hang_limit_ms: int = LIST_TABS_HANG_LIMIT_MS) -> tuple[bool, str]:
    if payload.get("ok") is not True:
        return False, f"list_tabs failed: reason={payload.get('reason')!r}"
    tabs = payload.get("tabs")
    if not isinstance(tabs, list):
        return False, "tabs is not a list (contract says object with `tabs`)"
    if not tabs:
        return False, "no page tabs — open a page in this profile first"
    for tab in tabs:
        if not isinstance(tab, dict):
            return False, f"tab entry is not an object: {tab!r}"
        missing = {"target_id", "url", "title", "visibility"} - set(tab)
        if missing:
            return False, f"tab entry missing keys {sorted(missing)}: {tab}"
        if tab["visibility"] not in VISIBILITY_VALUES:
            return False, f"visibility={tab['visibility']!r} not in {VISIBILITY_VALUES}"
        if "frozen" in tab:
            return False, "tab entry exposes `frozen` (contract forbids guessing it)"
    duration = payload.get("duration_ms")
    if not isinstance(duration, int):
        return False, "duration_ms missing"
    if duration > hang_limit_ms:
        return False, f"took {duration}ms > {hang_limit_ms}ms (would look like a hang)"
    unknown = sum(1 for t in tabs if t["visibility"] == "unknown")
    return True, f"{len(tabs)} tab(s), {unknown} unknown, duration_ms={duration}, probe_ms={payload.get('probe_ms')}"


def check_eval_visibility(payload: dict) -> tuple[bool, str]:
    if payload.get("ok") is not True:
        return False, f"eval failed: reason={payload.get('reason')!r} error={payload.get('error')!r}"
    value = payload.get("value")
    if value not in ("visible", "hidden"):
        return False, f"document.visibilityState returned {value!r}"
    if payload.get("activated") is not True:
        return False, "activated=false although activate defaults to true"
    return True, f"visibilityState={value!r} size_bytes={payload.get('size_bytes')}"


def check_oversize_is_rejected(payload: dict, requested_bytes: int) -> tuple[bool, str]:
    if payload.get("ok") is not False:
        return False, "oversized result was accepted (must fail, never truncate)"
    if payload.get("reason") != "result_too_large":
        return False, f"reason={payload.get('reason')!r} (expected 'result_too_large')"
    if "value" in payload:
        return False, "failure payload still carries a (truncated?) `value`"
    size = payload.get("size_bytes")
    if not isinstance(size, int) or size <= requested_bytes:
        return False, f"size_bytes={size!r} not > requested {requested_bytes}"
    return True, f"rejected size_bytes={size} (> {requested_bytes}) without truncation"


def check_activate(payload: dict) -> tuple[bool, str]:
    if payload.get("ok") is True:
        if not payload.get("target_id"):
            return False, "activate_tab ok but no target_id"
        return True, f"target_id={payload['target_id']} url={payload.get('url')}"
    reason = payload.get("reason")
    if reason == "PAGE_AMBIGUOUS":
        candidates = payload.get("candidates") or []
        return False, f"PAGE_AMBIGUOUS with {len(candidates)} candidate(s) — pass a unique url_part"
    return False, f"activate failed: reason={reason!r}"


def check_tab_visible_after_activate(payload: dict, target_id: str) -> tuple[bool, str]:
    if payload.get("ok") is not True:
        return False, f"list_tabs failed after activate: reason={payload.get('reason')!r}"
    for tab in payload.get("tabs") or []:
        if isinstance(tab, dict) and tab.get("target_id") == target_id:
            visibility = tab.get("visibility")
            if visibility == "visible":
                return True, f"{target_id} is visible after activate"
            if visibility == "unknown":
                return True, f"{target_id} reached the probe budget (unknown) — not a hang"
            return False, f"{target_id} is {visibility!r} after activate"
    return False, f"target {target_id} disappeared from list_tabs"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="full MCP endpoint, e.g. http://host:8766/mcp")
    ap.add_argument("--host", help="device host; used with --port to build the URL")
    ap.add_argument("--port", type=int, default=8766, help="device port (default 8766)")
    ap.add_argument("--profile", default="",
                    help="Chrome profile string (same value as human_browser_open; "
                         "empty = the server's 'isolated' default)")
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
        print(f"ERROR: MCP client SDK not available ({exc}). Use the server venv or `pip install mcp`.",
              file=sys.stderr)
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
                ok, detail = check_capability_enabled(caps)
                add("devtools capability enabled", ok, detail)
                if not ok:
                    if args.json:
                        print(json.dumps({"url": url, "results": results}, ensure_ascii=False, indent=2))
                    else:
                        print(f"FAIL  devtools capability enabled: {detail}")
                    return 3

                port_payload = await call("cdp_port", profile=args.profile)
                ok, detail = check_cdp_port(port_payload)
                add("cdp_port", ok, detail)
                if not ok:
                    # 后续检查都依赖一个活端口，直接收尾并给出可操作原因
                    if args.json:
                        print(json.dumps({"url": url, "results": results}, ensure_ascii=False, indent=2))
                    else:
                        for r in results:
                            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}: {r['detail']}")
                    return 1

                tabs_payload = await call("list_tabs", profile=args.profile)
                ok, detail = check_list_tabs(tabs_payload)
                add("list_tabs shape + latency", ok, detail)

                eval_payload = await call("eval_in_profile", profile=args.profile,
                                          js="document.visibilityState")
                ok, detail = check_eval_visibility(eval_payload)
                add("eval_in_profile read", ok, detail)

                oversize_payload = await call("eval_in_profile", profile=args.profile,
                                              js="'x'.repeat(4096)", max_result_bytes=1024)
                ok, detail = check_oversize_is_rejected(oversize_payload, 1024)
                add("oversize rejected, not truncated", ok, detail)

                first_url = ""
                for tab in tabs_payload.get("tabs") or []:
                    if isinstance(tab, dict) and tab.get("url", "").startswith("http"):
                        first_url = tab["url"]
                        break
                if first_url:
                    act_payload = await call("activate_tab", profile=args.profile, url_part=first_url)
                    ok, detail = check_activate(act_payload)
                    add("activate_tab", ok, detail)
                    if ok and act_payload.get("target_id"):
                        after = await call("list_tabs", profile=args.profile)
                        ok2, detail2 = check_tab_visible_after_activate(after, act_payload["target_id"])
                        add("tab visible after activate", ok2, detail2)
                else:
                    add("activate_tab", False, "no http(s) tab in this profile — open a page first")
    except Exception as exc:
        print(f"ERROR: cannot run devtools smoke against {url}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    failed = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps({"url": url, "profile": args.profile, "results": results,
                          "passed": len(results) - len(failed), "total": len(results)},
                         ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}: {r['detail']}")
        print(f"\nSUMMARY: {len(results) - len(failed)}/{len(results)} passed  ({url}, profile={args.profile!r})")
    if failed:
        print("FAILED: " + ", ".join(r["check"] for r in failed), file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(_url(args), args))


if __name__ == "__main__":
    sys.exit(main())
