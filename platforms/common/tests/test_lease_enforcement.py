"""Tests for enforced, session-bound device leases and the FastMCP gate."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from _device_state import DeviceStateRegistry
from _lease_gate import EXEMPT_TOOLS, LeaseGate, ctx_session_id, deny_payload


class _ManualClock:
    _BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self._BASE + timedelta(seconds=self.t)

    def advance(self, secs):
        self.t += secs


def _registry():
    return DeviceStateRegistry(clock=_ManualClock())


# --------------------------- registry: session binding ---------------------------

def test_free_device_allows_anyone_without_auto_acquire():
    reg = _registry()
    decision = reg.guard("serial-1", "session-A")
    assert decision == {"ok": True, "leased": False}
    assert reg.status("serial-1")["in_use"] is False


def test_holder_session_allowed_and_renewed():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-A")
    reg._clock.advance(60)  # type: ignore[attr-defined]

    decision = reg.guard("serial-1", "session-A")

    assert decision["ok"] is True and decision["renewed"] is True
    assert reg.status("serial-1")["idle_seconds"] == 0


def test_other_session_denied_with_backoff_info():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-A")
    reg._clock.advance(90)  # type: ignore[attr-defined]

    decision = reg.guard("serial-1", "session-B")

    assert decision["ok"] is False
    assert decision["current_holder"] == "alice"
    assert decision["idle_seconds"] == 90
    assert decision["auto_release_in_seconds"] == 600 - 90


def test_denied_call_does_not_renew_the_holders_lease():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-A")
    reg._clock.advance(300)  # type: ignore[attr-defined]

    reg.guard("serial-1", "session-B")

    assert reg.status("serial-1")["idle_seconds"] == 300


def test_idle_expiry_frees_the_device_for_others():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-A")
    reg._clock.advance(601)  # type: ignore[attr-defined]

    assert reg.guard("serial-1", "session-B")["ok"] is True
    assert reg.acquire("serial-1", "bob", session_id="session-B")["acquired"] is True


def test_reacquire_by_same_name_rebinds_after_reconnect():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-old")

    result = reg.acquire("serial-1", "alice", session_id="session-new")

    assert result["acquired"] is True and result.get("note") == "already yours"
    assert reg.guard("serial-1", "session-old")["ok"] is False
    assert reg.guard("serial-1", "session-new")["ok"] is True


def test_release_from_another_session_is_refused():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-A")

    result = reg.release("serial-1", "alice", session_id="session-B")

    assert result["released"] is False
    assert result["reason"] == "session_mismatch"
    assert reg.status("serial-1")["in_use"] is True


def test_release_from_holder_session_succeeds():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id="session-A")

    result = reg.release("serial-1", "alice", session_id="session-A")

    assert result["released"] is True
    assert reg.status("serial-1")["in_use"] is False


def test_sessionless_clients_are_treated_as_legacy_and_allowed():
    reg = _registry()
    reg.acquire("serial-1", "alice", session_id=None)

    assert reg.guard("serial-1", "session-B")["ok"] is True


# --------------------------- FastMCP gate policy ---------------------------

def _gate():
    reg = _registry()
    gate = LeaseGate(reg, serial_for=lambda _ctx, _args: "serial-1")
    return reg, gate


def test_gate_exempts_lease_and_discovery_tools():
    reg, gate = _gate()
    assert "acquire" in EXEMPT_TOOLS and "get_status" in EXEMPT_TOOLS
    assert gate.check("acquire", "serial-1", "session-B") is None  # free anyway
    reg.acquire("serial-1", "alice", session_id="session-A")
    assert gate.check("get_status", "serial-1", "session-B") is None
    assert gate.check("list_capabilities", "serial-1", "session-B") is None


def test_gate_blocks_other_session_and_explains_next_step():
    reg, gate = _gate()
    reg.acquire("serial-1", "alice", session_id="session-A")

    denial = gate.check("tap", "serial-1", "session-B")

    assert denial is not None
    assert denial["reason"] == "device_leased"
    assert denial["current_holder"] == "alice"
    assert denial["tool"] == "tap" and denial["device"] == "serial-1"
    assert "acquire" in denial["next_step"]


def test_gate_allows_holder_and_auto_renews_for_capability_tools():
    reg, gate = _gate()
    reg.acquire("serial-1", "alice", session_id="session-A")
    reg._clock.advance(500)  # type: ignore[attr-defined]

    # capability tools go through the same gate -> they renew the lease
    assert gate.check("human_dom_fill", "serial-1", "session-A") is None
    assert reg.status("serial-1")["idle_seconds"] == 0


def test_gate_skips_unknown_device():
    reg, gate = _gate()
    reg.acquire("serial-1", "alice", session_id="session-A")
    gate_unresolved = LeaseGate(reg, serial_for=lambda _ctx, _args: None)

    assert gate_unresolved.check("tap", None, "session-B") is None


def test_deny_payload_shape():
    payload = deny_payload({"current_holder": "alice", "idle_seconds": 5,
                            "auto_release_in_seconds": 595}, tool="tap", device="d1")
    assert payload["ok"] is False and payload["reason"] == "device_leased"
    assert payload["auto_release_in_seconds"] == 595


def test_ctx_session_id_handles_missing_session():
    assert ctx_session_id(None) is None
    assert ctx_session_id(SimpleNamespace(session_id="s1")) == "s1"

    class _Boom:
        @property
        def session_id(self):
            raise RuntimeError("no session")

    assert ctx_session_id(_Boom()) is None


def test_on_call_tool_denial_returns_payload_without_calling_the_tool():
    reg, gate = _gate()
    reg.acquire("serial-1", "alice", session_id="session-A")
    called = []

    async def call_next(_ctx):
        called.append(True)
        return "TOOL-RAN"

    ctx = SimpleNamespace(
        message=SimpleNamespace(name="tap", arguments={"x": 1, "y": 2}),
        fastmcp_context=SimpleNamespace(session_id="session-B"),
    )
    try:
        asyncio.run(gate.on_call_tool(ctx, call_next))
    except RuntimeError as exc:  # fastmcp absent in stripped test envs
        assert "device_leased" in str(exc)
    assert called == []


def test_on_call_tool_allows_holder_and_invokes_tool():
    reg, gate = _gate()
    reg.acquire("serial-1", "alice", session_id="session-A")

    async def call_next(_ctx):
        return "TOOL-RAN"

    ctx = SimpleNamespace(
        message=SimpleNamespace(name="tap", arguments={}),
        fastmcp_context=SimpleNamespace(session_id="session-A"),
    )
    assert asyncio.run(gate.on_call_tool(ctx, call_next)) == "TOOL-RAN"
