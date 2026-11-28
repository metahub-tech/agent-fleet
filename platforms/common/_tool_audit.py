"""工具调用审计 —— 只回答一个问题的遥测：**哪些工具真的在被用？**

背景：2026-11 讨论"要不要把工具面拆成多个 MCP 端点（例如 `/human/mcp`）"时，发现
**没有任何工具级遥测**——设备侧 `session-audit.log` 只记会话事件（method/status），
调用方日志又只有各自视角。于是先用最小代价把"工具名 + 耗时 + 成败"记下来，
几天后就能用真实数据决定怎么拆，而不是拍脑袋。

**隐私与代价边界**（有意为之）：

- **不记录参数、不记录返回值、不记录异常消息**——只记工具名、耗时、成败；
  **`ms` 是从进入中间件到返回的墙钟，包含排队与事件循环争用**（真机见过毫秒级操作记 48–68s），
  所以不能拿单条最大值当"工具慢"，排序请用 p50/p95；
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


_BUILD_CACHE: dict[str, dict] = {}


def repo_root() -> Path:
    """`platforms/common/_tool_audit.py` → 仓库根。"""
    return Path(__file__).resolve().parents[2]


def build_info() -> dict:
    """返回 `{"build": <短HEAD>, "dirty": bool}`，进程内缓存。

    **为什么要有 `dirty`**：`build` 只说 HEAD，不说工作区脏不脏。若有人在部署目录里
    直接改了文件却没提交，HEAD 不变但跑的代码已经不是那个提交了 —— 此时 `--expect-build`
    会**通过**，而实际代码不对。这正是"读数看起来对、其实验的是别的东西"。

    `dirty` 在进程启动后第一次调用时算一次（**只看 `platforms/` `scripts/` `cli/`**，含新增的未跟踪文件；`.dsh/` 这类本地资料不计），
    之后缓存；`FLEET_BUILD_ID` / `FLEET_BUILD_DIRTY` 可覆盖（非 git 部署用）。
    """
    root = str(repo_root())
    if root not in _BUILD_CACHE:
        build, dirty = "unknown", False
        env_id = os.environ.get("FLEET_BUILD_ID")
        if env_id:
            build = env_id.strip()[:40]
            dirty = os.environ.get("FLEET_BUILD_DIRTY", "").strip().lower() in {"1", "true", "yes"}
        else:
            try:
                import subprocess
                head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                                      capture_output=True, text=True, timeout=5)
                if head.returncode == 0:
                    build = head.stdout.strip()[:40] or "unknown"
                # 收窄到**代码目录**再看：`.dsh/` 这类本地资料不应让设备判脏，
                # 但 `platforms/ scripts/ cli/` 里**新增的未跟踪文件**（例如新加的 .py 被 import）
                # 同样会改变运行行为，必须被抓到 —— 所以用 `--untracked-files=all` + pathspec。
                status = subprocess.run(
                    ["git", "-C", root, "status", "--porcelain", "--untracked-files=all",
                     "--", "platforms", "scripts", "cli"],
                    capture_output=True, text=True, timeout=5)
                dirty = status.returncode == 0 and bool(status.stdout.strip())
            except Exception:
                pass
        _BUILD_CACHE[root] = {"build": build, "dirty": dirty}
    return _BUILD_CACHE[root]


def build_id() -> str:
    """当前代码的构建标识（git 短 HEAD），**用于断言"跑的到底是哪份代码"**。

    为什么要这个：之前只能靠"审计里出现 holder 字段"**间接推断**跑的是新码——那是代理指标，
    不是事实（今天已经因为"拿时长推因果"栽过一次）。这里把 build 直接写进每条记录，
    重启后就能断言 `新 pid 的 build == 期望 commit`。

    取值顺序：`FLEET_BUILD_ID` 环境变量 → `git rev-parse --short HEAD` → `"unknown"`（非 git 部署）。
    结果按仓库根缓存，不会每条记录都 fork 一次 git。
    """
    return str(build_info()["build"])


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
    started_at: Optional[datetime] = None,
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
            **({"started_at": started_at.isoformat(timespec="seconds")} if started_at else {}),
            "tool": tool or "?",
            "ms": int(ms),
            "ok": bool(ok),
            "pid": os.getpid(),
            "build": build_info()["build"],
            "dirty": bool(build_info()["dirty"]),
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
        started_at = datetime.now(timezone.utc)
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
                started_at=started_at,
            )
