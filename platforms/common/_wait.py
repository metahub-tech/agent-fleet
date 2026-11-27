"""服务端等待原语：把「睡一会儿再看」从调用方挪到设备侧（借鉴 Windows-MCP 的 `WaitFor`）。

为什么值得单独做：agent 侧的 `sleep` + 重试是**盲目**的——短了没等到、长了白等，
而且每次重试都是一个新的 round-trip。放到设备侧做条件轮询：

* 一条件一调用，返回真实 `elapsed_ms` / `attempts`，调用方不用猜；
* 超时统一返回结构化 `{ok:false, reason:"timeout"}`，不会把 MCP 请求拖成"看起来卡死"；
* 轮询间隔与总预算都可控（默认 200ms / 10s，封顶 60s）。

本模块只有纯逻辑（probe 与 sleep 都是注入的），Linux 上就能把
「命中即返回 / 超时边界 / 间隔与预算」这些判据测出来。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional, Tuple

MAX_TIMEOUT_S = 60.0
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_INTERVAL_S = 0.2
MIN_INTERVAL_S = 0.02
_EPSILON = 1e-9


def negate_probe(probe: Callable[[], Tuple[bool, Any]]) -> Callable[[], Tuple[bool, Any]]:
    """把"条件成立"翻成"条件消失"（用于 `*_gone` 这类等待）。

    典型场景：文件选择对话框用完要等它**关掉**再继续，否则后续点击会打到对话框上。
    只翻转 matched，detail 原样带出（方便看到"最后一次仍看到什么"）。
    """
    def inverted() -> Tuple[bool, Any]:
        matched, detail = probe()
        return (not matched), detail

    return inverted


def wait_until(
    probe: Callable[[], Tuple[bool, Any]],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    interval_s: float = DEFAULT_INTERVAL_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """反复调用 ``probe()``（返回 ``(matched, detail)``）直到命中或超时。

    返回 ``{ok, matched, elapsed_ms, attempts, detail?}``：

    * ``ok=True`` 表示**在预算内命中**；``ok=False`` 表示超时（``reason:"timeout"``）；
    * ``probe`` 抛异常不视为致命：记一次 ``attempts`` 并继续轮询（探测本身可能因为
      窗口正在重建而失败），最后一次异常放进 ``last_error`` 供排查；
    * 至少探测 **1 次**（``timeout_s=0`` 时也立即探一次，避免"零预算"变成假超时）。
    """
    budget = max(0.0, min(float(timeout_s), MAX_TIMEOUT_S))
    interval = max(MIN_INTERVAL_S, float(interval_s))
    started = clock()
    attempts = 0
    last_error: Optional[str] = None
    last_detail: Any = None

    while True:
        attempts += 1
        try:
            matched, detail = probe()
            last_detail = detail
            if matched:
                return {
                    "ok": True,
                    "matched": True,
                    "elapsed_ms": int((clock() - started) * 1000),
                    "attempts": attempts,
                    "detail": detail,
                }
        except Exception as exc:  # noqa: BLE001 - 探测失败不等于超时
            last_error = f"{type(exc).__name__}: {exc}"
        elapsed = clock() - started
        # 浮点护栏：budget 可能是 0.3，而 3×0.1 累加得到 0.29999999999995 —— 不吸收这点误差会
        # 在最后一步 sleep(~1e-14)、永远跨不过预算，变成忙等死循环（本单测抓到的真实缺陷）。
        if elapsed + _EPSILON >= budget:
            payload = {
                "ok": False,
                "matched": False,
                "reason": "timeout",
                "elapsed_ms": int(elapsed * 1000),
                "attempts": attempts,
                "timeout_ms": int(budget * 1000),
                "detail": last_detail,
            }
            if last_error:
                payload["last_error"] = last_error
            return payload
        sleep(min(interval, max(MIN_INTERVAL_S, budget - elapsed)))
