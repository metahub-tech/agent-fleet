"""Post-install smoke tests: call representative tools on each MCP server
to surface TCC/permission/device-availability issues BEFORE the user
restarts their agent host.

Each installer declares its own list of SmokeTest via BaseInstaller.smoke_tests()
— the runner here is generic.

vs. verify.py (port + initialize handshake + count tools): smoke.py
actually invokes tools, which catches deeper failures like:
  - Screen Recording TCC not granted on macOS    → take_screenshot raises
  - No Android device plugged in                  → list_devices empty
  - venv missing pyobjc-framework-ApplicationServices → list_ui_elements crashes
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class SmokeTest:
    tool_name: str
    args: dict = field(default_factory=dict)
    description: str = ""        # human-readable, e.g. "Screen Recording TCC"
    timeout: float = 8.0
    optional: bool = False       # True → failure shows as SKIP, not FAIL
    hint_on_failure: str = ""    # actionable hint shown when this test fails
    success_predicate: Optional[Callable[[Any], bool]] = None  # custom success check on tool result


@dataclass
class SmokeResult:
    test: SmokeTest
    ok: bool
    skipped: bool = False
    duration_ms: int = 0
    error: str = ""
    note: str = ""               # extra context shown next to pass mark (e.g. "1080×2340")
    connection_error: bool = False  # True when the failure was at connect time, not test time
                                    # (lets the wizard render one connection-error line
                                    # instead of N copies + N misleading per-test hints)


def _unwrap_exception(e: BaseException) -> str:
    """Walk down an ExceptionGroup chain to surface the real underlying error.

    Python 3.11+ asyncio.TaskGroup wraps failures in ExceptionGroup, which
    `str()` prints as "unhandled errors in a TaskGroup (1 sub-exception)"
    with the actual cause buried.  This recurses through `.exceptions` to
    return something like "ConnectionRefusedError: [Errno 61] Connection refused".
    """
    inner = getattr(e, "exceptions", None)
    if inner:
        return _unwrap_exception(inner[0])
    return f"{type(e).__name__}: {e}"


def run_smoke_tests(host: str, port: int, tests: list[SmokeTest]) -> list[SmokeResult]:
    """Sync wrapper around the async runner — wizard calls this directly."""
    return asyncio.run(_run_async(host, port, tests))


async def _run_async(host: str, port: int, tests: list[SmokeTest]) -> list[SmokeResult]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = f"http://{host}:{port}/mcp"
    results: list[SmokeResult] = []
    try:
        async with streamablehttp_client(url) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                for test in tests:
                    results.append(await _run_one(session, test))
    except Exception as e:
        # Connection-level failure: mark every test FAIL with `connection_error=True`
        # so the wizard can render ONE consolidated "server not reachable" line
        # instead of N copies of the same error plus N misleading per-test hints.
        unwrapped = _unwrap_exception(e)
        for test in tests:
            results.append(SmokeResult(
                test=test, ok=False,
                error=f"MCP connection failed: {unwrapped}",
                connection_error=True,
            ))
    return results


async def _run_one(session, test: SmokeTest) -> SmokeResult:
    import time
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            session.call_tool(test.tool_name, test.args),
            timeout=test.timeout,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        if getattr(result, "isError", False):
            # MCP tool returned isError=True (server-side application error)
            err_text = ""
            for item in getattr(result, "content", []) or []:
                if hasattr(item, "text"):
                    err_text = item.text
                    break
            return SmokeResult(
                test=test,
                ok=False,
                skipped=test.optional,
                duration_ms=duration_ms,
                error=err_text or "tool returned isError=True",
            )
        if test.success_predicate and not test.success_predicate(result):
            return SmokeResult(
                test=test, ok=False, skipped=test.optional,
                duration_ms=duration_ms,
                error="custom success_predicate returned False",
            )
        return SmokeResult(test=test, ok=True, duration_ms=duration_ms)
    except asyncio.TimeoutError:
        return SmokeResult(
            test=test, ok=False, skipped=test.optional,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=f"timeout after {test.timeout}s",
        )
    except Exception as e:
        return SmokeResult(
            test=test, ok=False, skipped=test.optional,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=_unwrap_exception(e),
        )
