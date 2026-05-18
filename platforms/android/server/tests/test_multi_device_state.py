"""Integration tests for the 6 core multi-device tools (T3a of v0.7.0).

Uses the real DeviceStateRegistry; mocks _detect_devices so no adb is invoked.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SERVER_DIR))

if not os.environ.get("ATB_ANDROID_ADB"):
    _fake = Path(tempfile.gettempdir()) / "fake_adb_for_tests"
    if not _fake.exists():
        _fake.write_text("#!/bin/sh\nexit 0\n")
        _fake.chmod(0o755)
    os.environ["ATB_ANDROID_ADB"] = str(_fake)

import android_device_mcp as m  # noqa: E402
from _aliases import DeviceInfo  # noqa: E402
from _device_state import DeviceStateRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def two_devices(monkeypatch):
    """Two devices visible to the server."""
    devices = [
        DeviceInfo("AAA111", "google", "Pixel_7"),
        DeviceInfo("BBB222", "samsung", "SM_S908U"),
    ]
    monkeypatch.setattr(m, "_detect_devices", lambda: list(devices))
    monkeypatch.setattr(m, "_load_alias_overrides", lambda: {})
    return devices


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Fresh registry + empty session-default map for every test."""
    monkeypatch.setattr(m, "_state_registry", DeviceStateRegistry())
    monkeypatch.setattr(m, "_session_defaults", {})


class FakeCtx:
    """Stand-in for fastmcp.Context — just exposes a stable session_id."""
    def __init__(self, sid: str = "session-1"):
        self.session_id = sid


# ---------------------------------------------------------------------------
# Two-device acquire — isolated state
# ---------------------------------------------------------------------------

class TestTwoDeviceAcquire:
    def test_each_device_can_be_acquired_by_different_holder(self, two_devices):
        r1 = m.acquire_android(device="AAA111", holder_name="alice", ctx=None)
        r2 = m.acquire_android(device="BBB222", holder_name="bob", ctx=None)

        assert r1["acquired"] is True
        assert r1["holder"] == "alice"
        assert r1["device"] == "AAA111"

        assert r2["acquired"] is True
        assert r2["holder"] == "bob"
        assert r2["device"] == "BBB222"

    def test_holders_isolated_per_serial(self, two_devices):
        m.acquire_android(device="AAA111", holder_name="alice", ctx=None)
        m.acquire_android(device="BBB222", holder_name="bob", ctx=None)

        s1 = m.get_android_status(device="AAA111", ctx=None)
        s2 = m.get_android_status(device="BBB222", ctx=None)

        assert s1["holder"] == "alice"
        assert s2["holder"] == "bob"
        # And status echoes the device
        assert s1["device"] == "AAA111"
        assert s2["device"] == "BBB222"

    def test_release_one_does_not_affect_the_other(self, two_devices):
        m.acquire_android(device="AAA111", holder_name="alice", ctx=None)
        m.acquire_android(device="BBB222", holder_name="bob", ctx=None)

        rel = m.release_android(device="AAA111", holder_name="alice", ctx=None)
        assert rel["released"] is True
        assert rel["device"] == "AAA111"

        # BBB222 still held by bob
        s2 = m.get_android_status(device="BBB222", ctx=None)
        assert s2["in_use"] is True
        assert s2["holder"] == "bob"

    def test_acquire_by_alias(self, two_devices):
        r = m.acquire_android(device="google-pixel-7", holder_name="alice", ctx=None)
        assert r["acquired"] is True
        assert r["device"] == "AAA111"

    def test_acquire_without_device_raises_when_multiple(self, two_devices):
        with pytest.raises(m.MultipleDevicesError):
            m.acquire_android(device=None, holder_name="alice", ctx=None)


# ---------------------------------------------------------------------------
# list_devices output shape
# ---------------------------------------------------------------------------

class TestListDevices:
    def test_list_devices_two_phones_one_held(self, two_devices):
        m.acquire_android(device="AAA111", holder_name="alice", ctx=None)

        result = m.list_devices(ctx=None)
        assert result["count"] == 2

        by_serial = {d["serial"]: d for d in result["devices"]}
        held = by_serial["AAA111"]
        free = by_serial["BBB222"]

        # held device
        assert held["alias"] == "google-pixel-7"
        assert held["brand"] == "google"
        assert held["model"] == "Pixel_7"
        assert held["in_use"] is True
        assert held["holder"] == "alice"
        # no session → default_for_session is always False
        assert held["default_for_session"] is False

        # free device
        assert free["alias"] == "samsung-sm-s908u"
        assert free["in_use"] is False
        assert free["holder"] is None
        assert free["default_for_session"] is False

    def test_list_devices_marks_session_default(self, two_devices):
        ctx = FakeCtx("session-X")
        m.set_default_device(device="BBB222", ctx=ctx)

        result = m.list_devices(ctx=ctx)
        by_serial = {d["serial"]: d for d in result["devices"]}
        assert by_serial["AAA111"]["default_for_session"] is False
        assert by_serial["BBB222"]["default_for_session"] is True

    def test_list_devices_empty_when_none_attached(self, monkeypatch):
        monkeypatch.setattr(m, "_detect_devices", lambda: [])
        monkeypatch.setattr(m, "_load_alias_overrides", lambda: {})
        result = m.list_devices(ctx=None)
        assert result == {"count": 0, "devices": []}


# ---------------------------------------------------------------------------
# Sticky default lifecycle
# ---------------------------------------------------------------------------

class TestSessionDefault:
    def test_set_then_get_default_device(self, two_devices):
        ctx = FakeCtx("session-A")
        r = m.set_default_device(device="BBB222", ctx=ctx)
        assert r == {"set": True, "device": "BBB222", "alias": "samsung-sm-s908u"}

        g = m.get_default_device(ctx=ctx)
        assert g == {"device": "BBB222", "alias": "samsung-sm-s908u"}

    def test_set_default_via_alias(self, two_devices):
        ctx = FakeCtx("session-A")
        r = m.set_default_device(device="samsung-sm-s908u", ctx=ctx)
        assert r["device"] == "BBB222"

    def test_get_default_when_none_set(self, two_devices):
        ctx = FakeCtx("session-A")
        assert m.get_default_device(ctx=ctx) == {"device": None, "alias": None}

    def test_session_default_routes_acquire_without_device(self, two_devices):
        ctx = FakeCtx("session-A")
        m.set_default_device(device="BBB222", ctx=ctx)

        # No device arg → resolver consults session default
        r = m.acquire_android(device=None, holder_name="bob", ctx=ctx)
        assert r["acquired"] is True
        assert r["device"] == "BBB222"

    def test_clearing_session_default_restores_autoselect_failure(self, two_devices):
        ctx = FakeCtx("session-A")
        m.set_default_device(device="BBB222", ctx=ctx)
        assert m._get_session_default(ctx) == "BBB222"

        # Explicit clear via helper (no public clear tool in this version,
        # but the resolver path is what matters).
        m._set_session_default(ctx, None)
        assert m._get_session_default(ctx) is None

        with pytest.raises(m.MultipleDevicesError):
            m.acquire_android(device=None, holder_name="bob", ctx=ctx)

    def test_set_default_unknown_device_raises(self, two_devices):
        ctx = FakeCtx("session-A")
        with pytest.raises(RuntimeError, match="unknown device"):
            m.set_default_device(device="GHOST", ctx=ctx)

    def test_session_defaults_isolated_per_session(self, two_devices):
        ctx_a = FakeCtx("session-A")
        ctx_b = FakeCtx("session-B")
        m.set_default_device(device="AAA111", ctx=ctx_a)
        m.set_default_device(device="BBB222", ctx=ctx_b)

        assert m.get_default_device(ctx=ctx_a)["device"] == "AAA111"
        assert m.get_default_device(ctx=ctx_b)["device"] == "BBB222"
