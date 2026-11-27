"""`_batch` 单测：整体校验、失败短路、跳过标记、延迟与二进制返回的安全化。

任何平台可跑（注册表与 sleep 都是注入的）。
"""
import pytest

from _batch import MAX_STEPS, StepError, run_steps, validate_steps


def _registry(calls, *, fail_on=None, boom_on=None):
    def make(name):
        def tool(**kwargs):
            calls.append((name, kwargs))
            if name == boom_on:
                raise RuntimeError("boom")
            if name == fail_on:
                return {"ok": False, "reason": "not_found"}
            return {"ok": True, "name": name, "kwargs": kwargs}
        return tool
    return {n: make(n) for n in ("tap", "type_text", "press_key", "clipboard_set_html")}


# --- 校验 -----------------------------------------------------------------

def test_validate_accepts_well_formed_steps():
    reg = _registry([])
    steps = validate_steps([{"tool": "tap", "args": {"x": 1, "y": 2}},
                            {"tool": "press_key", "args": {"keys": "ctrl+v"}, "sleep_ms": 120}], reg)
    assert [s["tool"] for s in steps] == ["tap", "press_key"]
    assert steps[1]["sleep_ms"] == 120


def test_validate_rejects_unknown_tool_before_running_anything():
    reg = _registry([])
    with pytest.raises(StepError, match="not allowed"):
        validate_steps([{"tool": "tap", "args": {}}, {"tool": "run_shell", "args": {}}], reg)


def test_validate_rejects_bad_shapes():
    reg = _registry([])
    with pytest.raises(StepError):
        validate_steps([], reg)
    with pytest.raises(StepError):
        validate_steps([{"args": {}}], reg)
    with pytest.raises(StepError):
        validate_steps([{"tool": "tap", "args": "x"}], reg)
    with pytest.raises(StepError):
        validate_steps([{"tool": "tap", "sleep_ms": -1}], reg)
    with pytest.raises(StepError):
        validate_steps([{"tool": "tap"}] * (MAX_STEPS + 1), reg)


# --- 执行 -----------------------------------------------------------------

def test_runs_steps_in_order():
    calls = []
    reg = _registry(calls)
    out = run_steps(validate_steps([{"tool": "tap", "args": {"x": 1, "y": 2}},
                                    {"tool": "type_text", "args": {"text": "hi"}}], reg), reg,
                    sleep=lambda s: None)
    assert out["ok"] is True and out["completed"] == 2
    assert calls == [("tap", {"x": 1, "y": 2}), ("type_text", {"text": "hi"})]


def test_stops_and_marks_skipped_on_ok_false():
    calls = []
    reg = _registry(calls, fail_on="tap")
    out = run_steps(validate_steps([{"tool": "tap", "args": {}},
                                    {"tool": "press_key", "args": {"keys": "enter"}}], reg), reg,
                    sleep=lambda s: None)
    assert out["ok"] is False and out["failed_at"] == 0 and out["failed_tool"] == "tap"
    assert out["steps"][0]["status"] == "failed" and out["steps"][0]["reason"] == "not_found"
    assert out["steps"][1]["status"] == "skipped"
    assert calls == [("tap", {})]                     # 失败后不再执行下一步


def test_stop_on_error_false_keeps_going():
    calls = []
    reg = _registry(calls, fail_on="tap")
    out = run_steps(validate_steps([{"tool": "tap", "args": {}},
                                    {"tool": "press_key", "args": {"keys": "enter"}}], reg), reg,
                    stop_on_error=False, sleep=lambda s: None)
    assert out["ok"] is False and out["completed"] == 1
    assert [s["status"] for s in out["steps"]] == ["failed", "ok"]


def test_exception_is_recorded_not_raised():
    calls = []
    reg = _registry(calls, boom_on="type_text")
    out = run_steps(validate_steps([{"tool": "type_text", "args": {}}], reg), reg, sleep=lambda s: None)
    assert out["ok"] is False
    assert out["steps"][0]["status"] == "error" and "RuntimeError" in out["steps"][0]["error"]


def test_delays_are_applied_between_steps():
    slept = []
    reg = _registry([])
    steps = validate_steps([{"tool": "tap", "args": {}, "sleep_ms": 100},
                            {"tool": "tap", "args": {}, "sleep_ms": 0}], reg)
    run_steps(steps, reg, delay_ms=50, sleep=slept.append)
    # 第一步后 sleep_ms(0.1) + 步间 delay(0.05)；第二步后只有 delay(0.05)
    assert slept == pytest.approx([0.1, 0.05, 0.05])


def test_binary_results_are_made_json_safe():
    class FakeImage:
        data = b"png-bytes"

    reg = {"take_screenshot": lambda **k: FakeImage(), "paste": lambda **k: b"\x00\x01"}
    out = run_steps(validate_steps([{"tool": "take_screenshot"}, {"tool": "paste"}], reg), reg,
                    sleep=lambda s: None)
    assert out["ok"] is True
    assert out["steps"][0]["result"] == {"_image": 9}
    assert out["steps"][1]["result"] == {"_bytes": 2}
    # 结果必须能 JSON 化
    import json
    json.dumps(out)
