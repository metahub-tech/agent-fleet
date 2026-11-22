"""Session-bound, enforced device leases — FastMCP tool-call gate.

Enforcement model (see `_device_state.py`):

* **free device** → any session may use it (claiming stays explicit: no auto-acquire);
* **held device** → only the acquiring MCP session may use it; other sessions get a
  structured denial ``{ok: false, reason: "device_leased", current_holder, ...}``;
* **auto-renew** → every allowed call refreshes the holder's idle timer, including
  capability tools (browser / human_dom / vision), so long browser work never
  expires a lease it is actively using;
* **10 idle minutes** release the lease (lazy, on the next call).

The gate lives at the tool-call entry point so no individual tool signature has to
change (and capability modules are covered automatically).
"""
from __future__ import annotations

import json
from typing import Any, Callable, FrozenSet, Optional

try:  # the pure-logic tests run without fastmcp installed
    from fastmcp.server.middleware import Middleware, MiddlewareContext  # noqa: F401
    from mcp.types import CallToolResult, TextContent
except Exception:  # pragma: no cover - exercised only in stripped test envs
    class Middleware:  # type: ignore[no-redef]
        """Stand-in base class when fastmcp is unavailable (tests)."""

    MiddlewareContext = Any  # type: ignore[assignment,misc]
    CallToolResult = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]


#: Tools that never touch the device and must stay callable by anyone:
#: lease bookkeeping + discovery. Everything else (core device tools and every
#: optional capability tool) is gated and auto-renews.
EXEMPT_TOOLS: FrozenSet[str] = frozenset({
    "acquire",
    "release",
    "get_status",
    "list_devices",
    "get_default_device",
    "set_default_device",
    "list_capabilities",
})


def ctx_session_id(ctx: Any) -> Optional[str]:
    """Best-effort MCP session id for a fastmcp Context (None when unavailable)."""
    if ctx is None:
        return None
    try:
        return ctx.session_id
    except Exception:
        return None


def deny_payload(decision: dict, *, tool: str, device: str) -> dict:
    """Structured body returned to a session that does not hold the lease."""
    return {
        "ok": False,
        "reason": "device_leased",
        "tool": tool,
        "device": device,
        "current_holder": decision.get("current_holder"),
        "auto_release_in_seconds": decision.get("auto_release_in_seconds"),
        "idle_seconds": decision.get("idle_seconds"),
        "next_step": (
            "Another session holds this device. Retry after auto_release_in_seconds, "
            "or ask the holder to release, or call acquire with a different holder_name "
            "once it is free."
        ),
    }


def _denial_result(payload: dict):
    """Wrap the payload as a normal (non-isError) tool result carrying JSON text."""
    if CallToolResult is None or TextContent is None:  # pragma: no cover
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        isError=False,
    )


class LeaseGate(Middleware):
    """FastMCP middleware enforcing the session-bound device lease."""

    def __init__(
        self,
        registry: Any,
        serial_for: Callable[[Any, dict], Optional[str]],
        exempt: FrozenSet[str] = EXEMPT_TOOLS,
    ) -> None:
        self._registry = registry
        self._serial_for = serial_for
        self._exempt = frozenset(exempt)

    def _resolve(self, context: Any, arguments: dict) -> Optional[str]:
        try:
            return self._serial_for(context, arguments)
        except Exception:
            # unknown/ambiguous device: let the tool itself produce the precise error
            return None

    def check(self, name: str, serial: Optional[str], session_id: Optional[str]) -> Optional[dict]:
        """Pure decision: None = allow, dict = denial payload.

        Kept separate from ``on_call_tool`` so the policy is testable without a
        running FastMCP server.
        """
        if not name or name in self._exempt or serial is None:
            return None
        decision = self._registry.guard(serial, session_id)
        if decision.get("ok"):
            return None
        return deny_payload(decision, tool=name, device=serial)

    async def on_call_tool(self, context: Any, call_next: Callable):
        params = context.message
        name = getattr(params, "name", "") or ""
        if name in self._exempt:
            return await call_next(context)

        arguments = getattr(params, "arguments", None) or {}
        serial = self._resolve(context, arguments)
        if serial is None:
            return await call_next(context)

        denial = self.check(name, serial, ctx_session_id(getattr(context, "fastmcp_context", None)))
        if denial is None:
            return await call_next(context)
        return _denial_result(denial)
