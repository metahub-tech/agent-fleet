"""批量动作执行器：一次 MCP 调用里按顺序跑多步（借鉴 mobile-mcp 的 `batch_commands`
与 Windows-MCP 的 `MultiEdit`）。

为什么值得：社媒发文这类流程是「填标题 → 粘正文 → 按键 → 点发布」的固定串，
每步一次往返 ⇒ 一个流程几十 turn。把串行步骤挪进**一次工具调用**，turn 数直接按步数下降，
且中间不会因为某一步的推理延迟让页面状态漂移。

安全边界（这是本模块存在的理由）：
* **只允许白名单工具**（`registry` 由调用方给出），绝不反射任意名字；
* **不递归**（`run_actions` 自己不在白名单里）；
* **步数上限**（默认 25），避免一次调用跑失控；
* 每步独立 try/except，`stop_on_error` 决定失败后是否继续；
* 结果必须可 JSON 序列化（截图这类二进制返回被替换成占位，不塞进结果体）。

本模块不 import 任何设备库：`registry` 与 `sleep` 都注入，所以在 Linux 上就能把
「校验 / 截断 / 失败短路 / 延迟」这些判据全部测出来。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Optional

MAX_STEPS = 25
MAX_DELAY_MS = 5_000


class StepError(Exception):
    """单步参数不合法（在真正调用工具之前就拒绝，避免半截执行）。"""


def _json_safe(value: Any) -> Any:
    """把工具返回值压成可 JSON 序列化的形态。

    平台工具里有返回 ``Image`` / ``bytes`` 的（如 take_screenshot）；批量结果要能整体
    JSON 化回给 MCP 客户端，二进制一律换成占位描述，**绝不静默丢弃步**。
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return {"_bytes": len(value)}
    data = getattr(value, "data", None)       # fastmcp Image（截图）：带 bytes .data
    if isinstance(data, (bytes, bytearray)):
        return {"_image": len(data)}
    return {"_repr": type(value).__name__}


def validate_steps(steps: Any, registry: Mapping[str, Callable], max_steps: int = MAX_STEPS) -> list[dict]:
    """把入参规整成 ``[{tool, args, sleep_ms}]``；任何不合法都整体拒绝。

    先整体校验再执行：宁可一步不跑，也不要跑到第 5 步才发现第 6 步拼错。
    """
    if not isinstance(steps, list) or not steps:
        raise StepError("steps must be a non-empty list of {tool, args?} objects")
    if len(steps) > max_steps:
        raise StepError(f"too many steps ({len(steps)} > {max_steps})")
    out: list[dict] = []
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            raise StepError(f"step[{index}] must be an object")
        tool = str(raw.get("tool") or "").strip()
        if not tool:
            raise StepError(f"step[{index}] is missing 'tool'")
        if tool not in registry:
            raise StepError(f"step[{index}]: tool {tool!r} is not allowed in a batch "
                            f"(allowed: {', '.join(sorted(registry))})")
        args = raw.get("args") or {}
        if not isinstance(args, dict):
            raise StepError(f"step[{index}].args must be an object")
        sleep_ms = raw.get("sleep_ms", 0)
        try:
            sleep_ms = int(sleep_ms)
        except (TypeError, ValueError):
            raise StepError(f"step[{index}].sleep_ms must be an integer")
        if sleep_ms < 0 or sleep_ms > MAX_DELAY_MS:
            raise StepError(f"step[{index}].sleep_ms out of range (0..{MAX_DELAY_MS})")
        out.append({"tool": tool, "args": args, "sleep_ms": sleep_ms})
    return out


def make_caller(fn: Callable, extra_kwargs: Mapping[str, Any]) -> Callable:
    """给工具函数包一层"默认参数注入"，**只在函数签名真的接受时才注入**。

    用途：移动端 server 的工具靠 `ctx` 取会话级默认设备；批量执行器调用的是内层
    函数（没有 FastMCP 注入的 ctx），不把 ctx 传下去就会出现"set_default_device 设了、
    但批量和等待里用不上"的静默失效。桌面的工具没有 ctx 参数，所以必须按签名判断，
    不能无脑多传一个 kwarg（否则 TypeError）。
    """
    import inspect

    if not extra_kwargs:
        return fn
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):        # 取不到签名（内置/C 扩展）→ 不注入
        return fn
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    injectable = {k: v for k, v in extra_kwargs.items()
                  if accepts_var_kw or (k in params and params[k].kind in (
                      inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY))}
    if not injectable:
        return fn

    def wrapper(**kwargs):
        merged = {**injectable, **kwargs}   # 调用方显式传的优先
        return fn(**merged)

    return wrapper


def run_steps(
    steps: list[dict],
    registry: Mapping[str, Callable],
    *,
    stop_on_error: bool = True,
    delay_ms: int = 0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """顺序执行 ``steps``，返回 ``{ok, completed, total, steps:[...]}``。

    * ``stop_on_error=True``（默认）：某步抛异常/返回 ``ok:false`` 就停，后面的步标记
      ``skipped``——不让一次失败被后续动作覆盖成"看起来跑完了"；
    * 每步结果原样保留（JSON 安全化后），方便调用方判断是哪一步出的问题；
    * ``delay_ms`` 是**步间**固定间隔，``steps[i].sleep_ms`` 是该步执行后的额外等待。
    """
    delay_ms = max(0, min(int(delay_ms or 0), MAX_DELAY_MS))
    results: list[dict] = []
    completed = 0
    failed_at: Optional[int] = None

    for index, step in enumerate(steps):
        if failed_at is not None and stop_on_error:
            results.append({"index": index, "tool": step["tool"], "status": "skipped"})
            continue
        started = time.monotonic()
        try:
            value = registry[step["tool"]](**step["args"])
            ok = not (isinstance(value, dict) and value.get("ok") is False)
            entry = {
                "index": index,
                "tool": step["tool"],
                "status": "ok" if ok else "failed",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "result": _json_safe(value),
            }
            if not ok:
                entry["reason"] = value.get("reason") if isinstance(value, dict) else None
                failed_at = index
            else:
                completed += 1
        except Exception as exc:  # noqa: BLE001 - 单步失败不应炸掉整批
            entry = {
                "index": index,
                "tool": step["tool"],
                "status": "error",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }
            failed_at = index
        results.append(entry)

        if step.get("sleep_ms"):
            sleep(step["sleep_ms"] / 1000.0)
        if delay_ms:
            sleep(delay_ms / 1000.0)
        if failed_at is not None and stop_on_error:
            continue

    ok = failed_at is None
    payload = {"ok": ok, "completed": completed, "total": len(steps), "steps": results}
    if failed_at is not None:
        payload["failed_at"] = failed_at
        payload["failed_tool"] = steps[failed_at]["tool"]
    return payload
