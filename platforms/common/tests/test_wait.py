"""`_wait` 单测：命中即返回、超时边界、探测异常容错、间隔与预算封顶。"""
from _wait import MAX_TIMEOUT_S, wait_until


class FakeClock:
    """可推进的单调时钟：sleep 推进时间，便于确定性地测预算。

    `max_sleeps` 是**忙等熔断**：一旦循环在预算边界上原地打转（sleep 不再推进有效时间），
    从 sleep 抛 AssertionError，让测试**快速失败**而不是挂死——否则一个回归会让整个
    测试套件卡住而不是变红。
    """

    def __init__(self, max_sleeps: int = 100_000):
        self.now = 1000.0
        self._max_sleeps = max_sleeps
        self.sleeps = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > self._max_sleeps:
            raise AssertionError(f"FakeClock.sleep 被调用 {self.sleeps} 次 —— 疑似忙等")
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
    """预算 0.3s / 间隔 0.1s 时，探测次数必须有界（正常路径 ~4 次）。"""
    clock = FakeClock()
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        if calls["n"] > 50:
            raise AssertionError("wait_until 未在预算边界终止（疑似忙等）")
        return (False, None)

    out = wait_until(probe, timeout_s=0.3, interval_s=0.1, clock=clock, sleep=clock.sleep)
    assert out["ok"] is False and out["reason"] == "timeout"
    assert calls["n"] <= 10, f"probed {calls['n']} times — looks like a busy loop"


class QuantizedClock:
    """模拟真实单调时钟：**读数有分辨率**，睡不足一个量化步长时读数不变。

    这正是 `_EPSILON` 要防的场景：budget=0.3 与 3×0.1 累加得到 0.29999999999995，
    剩余 4.5e-14 的 sleep 推不动微秒级读数 ⇒ 若没有护栏就会原地忙等（实测 83 万次）。
    纯浮点 FakeClock 因为 ULP 舍入会前进，反而复现不出来。
    """

    def __init__(self, resolution_s: float = 1e-9, max_sleeps: int = 50):
        self._now = 1000.0
        self._resolution = resolution_s
        self._max_sleeps = max_sleeps
        self.sleeps = 0

    def __call__(self):
        return self._now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > self._max_sleeps:
            # 从 sleep 里抛：wait_until 的 try/except 只包 probe()，所以这里不会被吞，
            # 让"忙等"以**快速失败**呈现，而不是把整个测试挂死。
            raise AssertionError("wait_until 在浮点边界上忙等（护栏失效？）")
        # 关键：小于时间源分辨率的睡眠**推不动时钟**（真 sleep(4.5e-14) 就是这样）
        if seconds >= self._resolution:
            self._now += seconds


def test_timeout_terminates_on_quantized_clock():
    """回归（确定性）：量化时钟下，浮点边界必须靠 `_EPSILON` 收敛，不能忙等。"""
    clock = QuantizedClock()
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        if calls["n"] > 50:
            raise AssertionError("wait_until 在浮点边界上忙等（_EPSILON 护栏失效？）")
        return (False, None)

    out = wait_until(probe, timeout_s=0.3, interval_s=0.1, clock=clock, sleep=clock.sleep)
    assert out["ok"] is False and out["reason"] == "timeout"
    assert calls["n"] <= 10, f"probed {calls['n']} times — busy loop"
    assert clock.sleeps <= 10, f"slept {clock.sleeps} times — busy loop"
