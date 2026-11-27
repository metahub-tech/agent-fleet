"""`_wait` 单测：命中即返回、超时边界、探测异常容错、间隔与预算封顶。"""
import pytest

from _wait import MAX_TIMEOUT_S, wait_until


class FakeClock:
    """可推进的单调时钟：sleep 推进时间，便于确定性地测预算。"""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_returns_immediately_when_probe_matches():
    clock = FakeClock()
    out = wait_until(lambda: (True, {"title": "微信"}), clock=clock, sleep=clock.sleep)
    assert out["ok"] is True and out["matched"] is True
    assert out["attempts"] == 1 and out["elapsed_ms"] == 0


def test_polls_until_match():
    clock = FakeClock()
    state = {"n": 0}

    def probe():
        state["n"] += 1
        return (state["n"] >= 3, {"n": state["n"]})

    out = wait_until(probe, timeout_s=5, interval_s=0.2, clock=clock, sleep=clock.sleep)
    assert out["ok"] is True and out["attempts"] == 3
    assert out["elapsed_ms"] >= 400          # 两次 200ms 间隔
    assert out["detail"] == {"n": 3}


def test_timeout_returns_structured_failure():
    clock = FakeClock()
    called = {"n": 0}

    def probe():
        called["n"] += 1
        return (False, {"count": 0})

    out = wait_until(probe, timeout_s=0.5, interval_s=0.2, clock=clock, sleep=clock.sleep)
    assert out["ok"] is False and out["reason"] == "timeout"
    assert out["timeout_ms"] == 500
    assert called["n"] >= 2
    assert out["elapsed_ms"] >= 500


def test_probe_exceptions_do_not_abort_the_wait():
    clock = FakeClock()
    state = {"n": 0}

    def probe():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("window recreating")
        return (True, "ok")

    out = wait_until(probe, timeout_s=5, interval_s=0.1, clock=clock, sleep=clock.sleep)
    assert out["ok"] is True and out["attempts"] == 3


def test_last_error_is_reported_on_timeout():
    clock = FakeClock()

    def probe():
        raise ConnectionError("uia gone")

    out = wait_until(probe, timeout_s=0.3, interval_s=0.1, clock=clock, sleep=clock.sleep)
    assert out["ok"] is False and "ConnectionError" in out["last_error"]


def test_zero_budget_still_probes_once():
    clock = FakeClock()
    out = wait_until(lambda: (True, None), timeout_s=0, clock=clock, sleep=clock.sleep)
    assert out["ok"] is True and out["attempts"] == 1


def test_interval_floor_and_budget_cap():
    clock = FakeClock()
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock.sleep(seconds)

    wait_until(lambda: (False, None), timeout_s=10_000, interval_s=0.0001,
               clock=clock, sleep=sleep)
    # 预算被压到 MAX_TIMEOUT_S；单次间隔不低于 0.02s
    assert clock.now - 1000.0 >= MAX_TIMEOUT_S - 1e-6
    assert min(slept) >= 0.02
