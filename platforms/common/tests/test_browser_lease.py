"""Tests for BrowserLeaseRegistry (_browser_lease.py).

Dependency-free: inject a controllable clock + fake start_fn/close_fn (which just
record calls), so the full lease lifecycle runs without any real browser."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _browser_lease import (  # noqa: E402
    BrowserLeaseRegistry,
    ENGINE_AGENT,
    ENGINE_HUMAN,
    STATE_ACTIVE,
    STATE_DETACHED,
)


class FakeClock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def make_fns():
    """Returns (start_fn, close_fn, calls) — start hands out 'inst-N', close records."""
    calls = {"start": 0, "closed": []}

    def start():
        calls["start"] += 1
        return f"inst-{calls['start']}"

    def close(inst):
        calls["closed"].append(inst)

    return start, close, calls


def fresh(idle_minutes=10):
    clock = FakeClock()
    reg = BrowserLeaseRegistry(idle_timeout=timedelta(minutes=idle_minutes), clock=clock)
    return reg, clock


# --------------------------------------------------------------------------- #
def test_bind_new_starts_instance():
    reg, _ = fresh()
    start, close, calls = make_fns()
    r = reg.bind("P", ENGINE_AGENT, "a1", start, close)
    assert r["bound"] is True and r["reused"] is False
    assert calls["start"] == 1
    assert reg.get_instance("P", "a1") == "inst-1"


def test_bind_same_holder_engine_reuses_without_restart():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    r = reg.bind("P", ENGINE_AGENT, "a1", start, close)
    assert r["bound"] is True and r["reused"] is True
    assert calls["start"] == 1  # not restarted


def test_bind_held_by_other_holder_refuses():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    r = reg.bind("P", ENGINE_AGENT, "a2", start, close)
    assert r["bound"] is False
    assert r["current_holder"] == "a1"
    assert "auto_release_in_seconds" in r
    assert calls["start"] == 1  # no second instance started


def test_cross_engine_mutual_exclusion():
    """human and agent share the registry: same profile can't be held by both."""
    reg, _ = fresh()
    start, close, _ = make_fns()
    reg.bind("P", ENGINE_HUMAN, "h1", start, close)
    r = reg.bind("P", ENGINE_AGENT, "a1", start, close)
    assert r["bound"] is False
    assert r["current_engine"] == ENGINE_HUMAN


def test_different_profiles_parallel():
    reg, _ = fresh()
    start, close, calls = make_fns()
    r1 = reg.bind("P1", ENGINE_AGENT, "a1", start, close)
    r2 = reg.bind("P2", ENGINE_AGENT, "a1", start, close)
    assert r1["bound"] and r2["bound"]
    assert calls["start"] == 2
    assert reg.get_instance("P1", "a1") == "inst-1"
    assert reg.get_instance("P2", "a1") == "inst-2"


def test_release_keeps_process_detached():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    r = reg.release("P", "a1")
    assert r["released"] is True and r["kept_alive"] is True
    assert calls["closed"] == []  # process NOT closed
    assert reg.status()["leases"][0]["state"] == STATE_DETACHED


def test_detached_same_engine_warm_reuse():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    reg.release("P", "a1")
    r = reg.bind("P", ENGINE_AGENT, "a2", start, close)  # different holder reattaches
    assert r["bound"] is True and r["reused"] is True
    assert calls["start"] == 1 and calls["closed"] == []  # warm reuse, no restart/close


def test_detached_different_engine_replaces():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_HUMAN, "h1", start, close)
    reg.release("P", "h1")
    r = reg.bind("P", ENGINE_AGENT, "a1", start, close)
    assert r["bound"] is True and r["reused"] is False
    assert calls["closed"] == ["inst-1"]  # old human process closed
    assert calls["start"] == 2  # new agent process started


def test_release_holder_mismatch():
    reg, _ = fresh()
    start, close, _ = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    r = reg.release("P", "someone-else")
    assert r["released"] is False and r["current_holder"] == "a1"


def test_close_drops_and_closes():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    r = reg.close("P", "a1")
    assert r["closed"] is True
    assert calls["closed"] == ["inst-1"]
    assert reg.status()["leases"] == []


def test_idle_timeout_closes_and_drops():
    reg, clock = fresh(idle_minutes=10)
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    clock.advance(minutes=11)
    # any access lazily expires it
    assert reg.get_instance("P", "a1") is None
    assert calls["closed"] == ["inst-1"]
    assert reg.status()["leases"] == []


def test_idle_timeout_closes_detached_too():
    reg, clock = fresh(idle_minutes=10)
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    reg.release("P", "a1")
    clock.advance(minutes=11)
    assert reg.status()["leases"] == []
    assert calls["closed"] == ["inst-1"]


def test_touch_refreshes_idle():
    reg, clock = fresh(idle_minutes=10)
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    clock.advance(minutes=9)
    assert reg.touch("P", "a1")["ok"] is True
    clock.advance(minutes=9)  # 9 after touch, still < 10 since touch
    assert reg.get_instance("P", "a1") == "inst-1"
    assert calls["closed"] == []


def test_touch_detached_fails():
    reg, _ = fresh()
    start, close, _ = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    reg.release("P", "a1")
    assert reg.touch("P", "a1")["ok"] is False


def test_get_instance_holder_mismatch_returns_none():
    reg, _ = fresh()
    start, close, _ = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    assert reg.get_instance("P", "a2") is None


def test_bind_validates_args():
    reg, _ = fresh()
    start, close, _ = make_fns()
    with pytest.raises(ValueError):
        reg.bind("", ENGINE_AGENT, "a1", start, close)
    with pytest.raises(ValueError):
        reg.bind("P", ENGINE_AGENT, "", start, close)
    with pytest.raises(ValueError):
        reg.bind("P", "bogus", "a1", start, close)


def test_close_fn_exception_is_swallowed():
    reg, _ = fresh()

    def start():
        return "inst"

    def boom(inst):
        raise RuntimeError("close failed")

    reg.bind("P", ENGINE_AGENT, "a1", start, boom)
    r = reg.close("P", "a1")  # must not raise
    assert r["closed"] is True
    assert reg.status()["leases"] == []


def test_release_clears_holder():
    reg, _ = fresh()
    start, close, _ = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    reg.release("P", "a1")
    snap = reg.status()["leases"][0]
    assert snap["state"] == STATE_DETACHED
    assert snap["holder"] == ""  # detached = ownerless


def test_close_detached_allowed_any_caller():
    reg, _ = fresh()
    start, close, calls = make_fns()
    reg.bind("P", ENGINE_AGENT, "a1", start, close)
    reg.release("P", "a1")
    r = reg.close("P", "anyone")  # detached is ownerless -> any caller may close
    assert r["closed"] is True
    assert calls["closed"] == ["inst-1"]


def test_parallel_profiles_idle_isolation():
    reg, clock = fresh(idle_minutes=10)
    start, close, calls = make_fns()
    reg.bind("P1", ENGINE_AGENT, "a1", start, close)
    clock.advance(minutes=6)
    reg.bind("P2", ENGINE_AGENT, "a1", start, close)
    clock.advance(minutes=6)  # P1 idle 12min (expired), P2 idle 6min (alive)
    assert reg.get_instance("P2", "a1") == "inst-2"   # P2 survives
    assert reg.get_instance("P1", "a1") is None        # P1 lazily expired
    assert calls["closed"] == ["inst-1"]
    assert len(reg.status()["leases"]) == 1


def test_start_fn_exception_leaves_no_lease():
    reg, _ = fresh()

    def boom():
        raise RuntimeError("launch failed")

    with pytest.raises(RuntimeError):
        reg.bind("P", ENGINE_AGENT, "a1", boom, lambda inst: None)
    assert reg.status()["leases"] == []  # no residual lease on failed start
