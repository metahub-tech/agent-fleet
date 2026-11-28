"""工具调用审计 —— 只回答一个问题的遥测：**哪些工具真的在被用？**

背景：2026-11 讨论"要不要把工具面拆成多个 MCP 端点（例如 `/human/mcp`）"时，发现
**没有任何工具级遥测**——设备侧 `session-audit.log` 只记会话事件（method/status），
调用方日志又只有各自视角。于是先用最小代价把"工具名 + 耗时 + 成败"记下来，
几天后就能用真实数据决定怎么拆，而不是拍脑袋。

**隐私与代价边界**（有意为之）：

- **不记录参数、不记录返回值、不记录异常消息**——只记工具名、耗时、成败；
- 每个调用只多一次 `open(..., "a")` + 一行 JSON（约 120 字节），失败**绝不**影响工具调用；
- 文件超过 `FLEET_TOOL_AUDIT_MAX_BYTES`（默认 8 MiB）自动轮转一份 `.1`，不会无限涨。

开关与位置：

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `FLEET_TOOL_AUDIT` | 开 | 设为 `0` 关闭 |
| `FLEET_TOOL_AUDIT_PATH` | `~/.agent-fleet/tool-audit.jsonl` | 落盘位置 |
| `FLEET_TOOL_AUDIT_MAX_BYTES` | `8388608` | 单文件上限，超过即轮转 |

分析用 `scripts/analyze_tool_audit.py`（按天/按工具/按能力分组，并给出候选端点的覆盖率）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:  # 纯逻辑测试不需要 fastmcp
    from fastmcp.server.middleware import Middleware
except Exception:  # pragma: no cover - 仅在不含 fastmcp 的测试环境
    class Middleware:  # type: ignore[no-redef]
        """fastmcp 不可用时的占位基类。"""


DEFAULT_PATH = "~/.agent-fleet/tool-audit.jsonl"
DEFAULT_MAX_BYTES = 8 * 1024 * 1024

_write_lock = threading.Lock()


def audit_enabled() -> bool:
    """审计默认开启；`FLEET_TOOL_AUDIT=0/false/off/no` 可关。"""
    return os.environ.get("FLEET_TOOL_AUDIT", "").strip().lower() not in {
        "0", "false", "off", "no",
    }


def audit_path() -> Path:
    return Path(os.path.expanduser(os.environ.get("FLEET_TOOL_AUDIT_PATH") or DEFAULT_PATH))


def audit_max_bytes() -> int:
    try:
        return max(64 * 1024, int(os.environ.get("FLEET_TOOL_AUDIT_MAX_BYTES") or DEFAULT_MAX_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_MAX_BYTES


def _rotate(path: Path, max_bytes: int) -> None:
    """超过上限就把当前文件改名为 `.1`（覆盖旧的 `.1`）。调用方已持锁。"""
    try:
        if path.exists() and path.stat().st_size >= max_bytes:
            backup = path.with_suffix(path.suffix + ".1")
            os.replace(path, backup)
    except OSError:
        pass


def append_record(
    tool: str,
    ms: int,
    ok: bool,
    path: Optional[Path] = None,
    max_bytes: Optional[int] = None,
    now: Optional[datetime] = None,
    session: str = "",
    holder: str = "",
) -> None:
    """追加一行审计记录。**任何异常都吞掉**——审计绝不能影响工具调用本身。"""
    if not audit_enabled():
        return
    target = path or audit_path()
    limit = max_bytes if max_bytes is not None else audit_max_bytes()
    moment = now or datetime.now(timezone.utc)
    line = json.dumps(
        {
            "ts": moment.isoformat(timespec="seconds"),
            "tool": tool or "?",
            "ms": int(ms),
            "ok": bool(ok),
            "pid": os.getpid(),
            **({"session": session} if session else {}),
            **({"holder": holder} if holder else {}),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            _rotate(target, limit)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass


def _tool_name(context: Any) -> str:
    try:
        return getattr(context.message, "name", "") or ""
    except Exception:
        return ""


def _session_hint(context: Any) -> str:
    """会话 id 的前 8 位（便于把一次批量操作归到同一会话，不含任何内容）。"""
    try:
        ctx = getattr(context, "fastmcp_context", None)
        session = getattr(ctx, "session_id", None) if ctx is not None else None
        if session is None:
            request = getattr(ctx, "request_context", None)
            session = getattr(request, "session_id", None) if request is not None else None
        return str(session)[:8] if session else ""
    except Exception:
        return ""


class ToolAuditLog(Middleware):
    """FastMCP 中间件：在每个工具调用前后记一行（工具名 / 耗时 / 成败）。

    放在 `on_call_tool` 这一层是有意的——它覆盖 core 工具**和**所有可选能力
    （browser / vision / human_dom / devtools），不需要改任何工具签名。
    """

    #: 只缓存最近的会话→holder 映射大小，避免长跑进程无限增长
    _MAX_TRACKED_SESSIONS = 512

    def __init__(self, path: Optional[Path] = None, max_bytes: Optional[int] = None) -> None:
        self._path = path
        self._max_bytes = max_bytes
        #: session_id -> holder_name（**唯一**从参数里取的字段；见模块 docstring）
        self._holders: dict[str, str] = {}

    def _holder_for(self, session: str) -> str:
        return self._holders.get(session, "")

    def _note_acquire(self, session: str, arguments: Any) -> str:
        """记录 `acquire` 声明的 holder_name，并绑定到该会话，供后续调用归属。"""
        holder = ""
        try:
            if isinstance(arguments, dict):
                raw = arguments.get("holder_name")
                if isinstance(raw, str):
                    holder = raw[:64]
        except Exception:
            holder = ""
        if holder and session:
            if len(self._holders) >= self._MAX_TRACKED_SESSIONS:
                # 丢最旧的（dict 保序）
                self._holders.pop(next(iter(self._holders)), None)
            self._holders[session] = holder
        return holder

    async def on_call_tool(self, context: Any, call_next: Callable) -> Any:
        name = _tool_name(context)
        session = _session_hint(context)
        holder = ""
        if name == "acquire":
            holder = self._note_acquire(session, getattr(context.message, "arguments", None))
        if not holder:
            holder = self._holder_for(session)
        started = time.perf_counter()
        ok = True
        try:
            return await call_next(context)
        except BaseException:
            ok = False
            raise
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            append_record(
                name, elapsed_ms, ok,
                path=self._path, max_bytes=self._max_bytes,
                session=session, holder=holder,
            )
