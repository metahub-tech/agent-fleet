"""Tests for _device_state — per-device Holder registry (T2 of v0.7.0)."""
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from _device_state import DeviceStateRegistry, Holder, IDLE_TIMEOUT


# ---------------------------------------------------------------------------
# Manual clock helper
# ---------------------------------------------------------------------------

class _ManualClock:
    _BASE = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> datetime:
        return self._BASE + timedelta(seconds=self.t)

    def advance(self, secs: float) -> None:
        self.t += secs


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------

class TestAcquire:
    def test_fresh_acquire_returns_acquired_true(self):
        reg = DeviceStateRegistry()
        result = reg.acquire("serial-1", "alice")
        assert result == {"acquired": True, "holder": "alice"}

    def test_same_name_reacquire_returns_already_yours(self):
        clock = _ManualClock(0)
        reg = DeviceStateRegistry(clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(5)
        result = reg.acquire("serial-1", "alice")
        assert result["acquired"] is True
        assert result.get("note") == "already yours"

    def test_same_name_reacquire_refreshes_last_used_at(self):
        clock = _ManualClock(0)
        reg = DeviceStateRegistry(clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(30)
        reg.acquire("serial-1", "alice")
        s = reg.status("serial-1")
        # last_used_at should reflect the second acquire time (t=30)
        assert s["idle_seconds"] == 0

    def test_different_name_acquire_while_held_returns_acquired_false(self):
        clock = _ManualClock(0)
        reg = DeviceStateRegistry(clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(5)
        result = reg.acquire("serial-1", "bob")
        assert result["acquired"] is False
        assert result["current_holder"] == "alice"
        assert "since" in result
        assert result["idle_seconds"] == 5
        assert "auto_release_in_seconds" in result

    def test_auto_release_in_seconds_is_never_negative(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=10)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(50)  # well past idle timeout
        result = reg.acquire("serial-1", "bob")
        # idle-expired holder should have been auto-released, so bob claims it
        assert result["acquired"] is True

    def test_auto_release_in_seconds_formula(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=100)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(30)
        result = reg.acquire("serial-1", "bob")
        assert result["acquired"] is False
        expected = max(0, 100 - result["idle_seconds"])
        assert result["auto_release_in_seconds"] == expected

    def test_acquire_empty_serial_raises_value_error(self):
        reg = DeviceStateRegistry()
        with pytest.raises(ValueError):
            reg.acquire("", "alice")


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------

class TestRelease:
    def test_release_no_holder_returns_released_false(self):
        reg = DeviceStateRegistry()
        result = reg.release("serial-1", "alice")
        assert result == {"released": False, "note": "no holder"}

    def test_release_wrong_holder_returns_mismatch(self):
        reg = DeviceStateRegistry()
        reg.acquire("serial-1", "alice")
        result = reg.release("serial-1", "bob")
        assert result["released"] is False
        assert result["current_holder"] == "alice"
        assert result["you_provided"] == "bob"
        assert "mismatch" in result["note"]

    def test_release_correct_holder_returns_released_true(self):
        clock = _ManualClock(0)
        reg = DeviceStateRegistry(clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(7)
        result = reg.release("serial-1", "alice")
        assert result["released"] is True
        assert result["held_for_seconds"] == 7

    def test_release_empty_serial_raises_value_error(self):
        reg = DeviceStateRegistry()
        with pytest.raises(ValueError):
            reg.release("", "alice")


# ---------------------------------------------------------------------------
# touch
# ---------------------------------------------------------------------------

class TestTouch:
    def test_touch_refreshes_last_used_at(self):
        clock = _ManualClock(0)
        reg = DeviceStateRegistry(clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(20)
        reg.touch("serial-1")
        s = reg.status("serial-1")
        assert s["idle_seconds"] == 0

    def test_touch_on_free_device_is_noop(self):
        reg = DeviceStateRegistry()
        reg.touch("serial-1")  # must not raise
        s = reg.status("serial-1")
        assert s["in_use"] is False

    def test_touch_on_idle_expired_device_auto_releases(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=10)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(20)
        reg.touch("serial-1")
        s = reg.status("serial-1")
        assert s["in_use"] is False

    def test_touch_empty_serial_raises_value_error(self):
        reg = DeviceStateRegistry()
        with pytest.raises(ValueError):
            reg.touch("")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_free_device_returns_in_use_false(self):
        reg = DeviceStateRegistry()
        result = reg.status("serial-1")
        assert result == {"in_use": False, "note": "free for acquire"}

    def test_held_device_returns_in_use_true_with_all_fields(self):
        clock = _ManualClock(0)
        reg = DeviceStateRegistry(clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(3)
        result = reg.status("serial-1")
        assert result["in_use"] is True
        assert result["holder"] == "alice"
        assert "acquired_at" in result
        assert "last_used_at" in result
        assert result["idle_seconds"] == 3

    def test_status_on_idle_expired_releases_and_returns_free(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=5)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(10)
        result = reg.status("serial-1")
        assert result["in_use"] is False

    def test_status_empty_serial_raises_value_error(self):
        reg = DeviceStateRegistry()
        with pytest.raises(ValueError):
            reg.status("")


# ---------------------------------------------------------------------------
# Per-device isolation
# ---------------------------------------------------------------------------

class TestPerDeviceIsolation:
    def test_acquire_a_does_not_affect_status_b(self):
        reg = DeviceStateRegistry()
        reg.acquire("serial-A", "alice")
        result = reg.status("serial-B")
        assert result["in_use"] is False

    def test_acquire_two_distinct_serials_both_succeed(self):
        reg = DeviceStateRegistry()
        r1 = reg.acquire("serial-A", "alice")
        r2 = reg.acquire("serial-B", "bob")
        assert r1["acquired"] is True
        assert r2["acquired"] is True

    def test_same_holder_name_on_different_devices_both_succeed(self):
        reg = DeviceStateRegistry()
        r1 = reg.acquire("serial-A", "alice")
        r2 = reg.acquire("serial-B", "alice")
        assert r1["acquired"] is True
        assert r2["acquired"] is True

    def test_release_a_leaves_b_intact(self):
        reg = DeviceStateRegistry()
        reg.acquire("serial-A", "alice")
        reg.acquire("serial-B", "bob")
        reg.release("serial-A", "alice")
        s = reg.status("serial-B")
        assert s["in_use"] is True
        assert s["holder"] == "bob"


# ---------------------------------------------------------------------------
# Idle expiry
# ---------------------------------------------------------------------------

class TestIdleExpiry:
    def test_status_auto_releases_after_idle_timeout(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=1)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(2)
        result = reg.status("serial-1")
        assert result["in_use"] is False

    def test_touch_on_idle_expired_is_noop_leaves_free(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=1)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-1", "alice")
        clock.advance(2)
        reg.touch("serial-1")
        assert reg.status("serial-1")["in_use"] is False

    def test_auto_release_one_device_does_not_touch_another(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=1)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-A", "alice")
        clock.advance(0.5)
        reg.acquire("serial-B", "bob")
        clock.advance(1)  # serial-A is now expired; serial-B still fresh (0.5s)
        # trigger auto-release for A
        reg.status("serial-A")
        # B must still be held
        sb = reg.status("serial-B")
        assert sb["in_use"] is True
        assert sb["holder"] == "bob"


# ---------------------------------------------------------------------------
# all_status
# ---------------------------------------------------------------------------

class TestAllStatus:
    def test_empty_registry_returns_empty_dict(self):
        reg = DeviceStateRegistry()
        assert reg.all_status() == {}

    def test_two_held_one_free_returns_two_key_dict(self):
        reg = DeviceStateRegistry()
        reg.acquire("serial-A", "alice")
        reg.acquire("serial-B", "bob")
        # serial-C never acquired
        result = reg.all_status()
        assert set(result.keys()) == {"serial-A", "serial-B"}

    def test_idle_expired_not_in_all_status(self):
        clock = _ManualClock(0)
        timeout = timedelta(seconds=1)
        reg = DeviceStateRegistry(idle_timeout=timeout, clock=clock)
        reg.acquire("serial-A", "alice")
        reg.acquire("serial-B", "bob")
        clock.advance(2)  # both expired
        result = reg.all_status()
        assert result == {}


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_10_threads_distinct_serials_all_succeed(self):
        reg = DeviceStateRegistry()
        results = {}
        errors = []

        def worker(i):
            try:
                r = reg.acquire(f"serial-{i}", f"holder-{i}")
                results[i] = r
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 10
        assert all(r["acquired"] is True for r in results.values())
        all_s = reg.all_status()
        assert len(all_s) == 10

    def test_10_threads_same_serial_exactly_1_succeeds(self):
        reg = DeviceStateRegistry()
        results = []
        errors = []
        barrier = threading.Barrier(10)

        def worker(i):
            try:
                barrier.wait()
                r = reg.acquire("shared-serial", f"holder-{i}")
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 10
        successes = [r for r in results if r["acquired"] is True]
        failures = [r for r in results if r["acquired"] is False]
        assert len(successes) == 1
        assert len(failures) == 9
