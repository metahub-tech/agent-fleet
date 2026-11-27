"""`_wait` 单测：命中即返回、超时边界、探测异常容错、间隔与预算封顶。"""
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


# --- negate_probe：等条件消失（对话框关闭等）------------------------------

def test_negate_probe_inverts_match_and_keeps_detail():
    from _wait import negate_probe

    probe = negate_probe(lambda: (True, {"title": "打开"}))
    matched, detail = probe()
    assert matched is False and detail == {"title": "打开"}

    probe2 = negate_probe(lambda: (False, None))
    assert probe2()[0] is True


def test_negate_probe_works_with_wait_until():
    from _wait import negate_probe

    clock = FakeClock()
    state = {"n": 0}

    def exists():
        state["n"] += 1
        return (state["n"] < 3, {"n": state["n"]})   # 前两次还在，第三次消失

    out = wait_until(negate_probe(exists), timeout_s=5, interval_s=0.1,
                     clock=clock, sleep=clock.sleep)
    assert out["ok"] is True and out["attempts"] == 3


def test_timeout_attempts_are_bounded():
    """预算 0.3s / 间隔 0.1s 时，探测次数必须有界（正常路径 ~4 次）。

    ⚠️ 诚实说明：这条**不能**复现历史上那个浮点忙等（`time.monotonic` 真时钟 + 4.5e-14
    的 sleep 才会永不跨过预算）。FakeClock 的加法会因 ULP 舍入而前进，所以去掉
    `_EPSILON` 护栏这条测试**仍然会绿**（已实测）。它守的是"次数不会失控"这一较弱性质；
    屏障本身靠 `_EPSILON` 的代码注释说明，没有确定性回归用例。
    """
    clock = FakeClock()
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        if calls["n"] > 50:
            raise AssertionError("wait_until 未在预算边界终止（浮点忙等回归）")
        return (False, None)

    out = wait_until(probe, timeout_s=0.3, interval_s=0.1, clock=clock, sleep=clock.sleep)
    assert out["ok"] is False and out["reason"] == "timeout"
    assert calls["n"] <= 10, f"probed {calls['n']} times — looks like a busy loop"
