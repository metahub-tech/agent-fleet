"""Session audit for streamable-http MCP servers (one JSONL line per /mcp request).

Why this exists
---------------
When a client reports ``Not Found: Invalid or expired session ID``, the uvicorn
access log only has ``IP:port - "POST /mcp" 404`` — no timestamp, no session id,
no hint whether the client created a new session or reused a dead one. That made
"did agent X reconnect or reuse yesterday's session?" unanswerable from logs.

This middleware records, per /mcp request:

    {"ts":"2026-11-25T13:05:11+08:00","method":"POST","client":"100.79.163.65",
     "session":"a1b2c3d4","status":200,"event":"reused"}

Events: ``created`` / ``reused`` / ``expired_or_unknown`` / ``init_failed`` /
``bad_request`` / ``stream_open`` / ``stream_fail`` / ``terminated`` / ``other``.

Storage: ``%USERPROFILE%\\.agent-fleet\\session-audit.log`` (or
``$FLEET_SESSION_AUDIT`` to override). Rotated at 5 MB (one ``.1`` backup).
Failures are swallowed: auditing must never break a tool call.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

_MAX_BYTES = 5 * 1024 * 1024
_WRITE_LOCK = threading.Lock()


def audit_path() -> Path:
    override = os.environ.get("FLEET_SESSION_AUDIT")
    if override:
        return Path(override)
    return Path.home() / ".agent-fleet" / "session-audit.log"


def classify(method: str, had_session: bool, status: int) -> str:
    """Classify one /mcp request from method + session-header presence + status."""
    method = (method or "").upper()
    if method == "DELETE":
        return "terminated"
    if method == "GET":
        return "stream_open" if status == 200 else "stream_fail"
    if method == "POST":
        if not had_session:
            return "created" if status in (200, 202) else "init_failed"
        if status in (200, 202):
            return "reused"
        if status == 404:
            return "expired_or_unknown"
        if status == 400:
            return "bad_request"
    return "other"


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            if backup.exists():
                backup.unlink()
            path.rename(backup)
    except OSError:
        pass


def write_event(record: dict) -> None:
    """Append one JSON line. Never raises (auditing is best-effort)."""
    path = audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> str:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


class SessionAuditMiddleware:
    """Pure-ASGI middleware: logs one line per /mcp request, nothing else."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).endswith("/mcp"):
            await self.app(scope, receive, send)
            return

        session_id = _header(scope.get("headers") or [], b"mcp-session-id")
        client = scope.get("client") or ("?", 0)
        state: dict = {"status": 0}

        async def send_wrapper(message: dict) -> None:
            if message.get("type") == "http.response.start":
                state["status"] = int(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if state["status"]:
                write_event({
                    "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "method": scope.get("method", ""),
                    "client": client[0],
                    "session": session_id[:8],
                    "status": state["status"],
                    "event": classify(scope.get("method", ""), bool(session_id), state["status"]),
                })
