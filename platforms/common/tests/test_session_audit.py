"""Tests for _session_audit — the JSONL session log behind "did it reconnect?"."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import _session_audit as audit


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _scope(method="POST", path="/mcp", session=None, client=("100.79.163.65", 5555)):
    headers = []
    if session:
        headers.append((b"mcp-session-id", session.encode()))
    return {"type": "http", "method": method, "path": path, "headers": headers, "client": client}


def _app(status):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    return app


async def _noop_receive():
    return {"type": "http.request", "body": b""}


def _run(status, scope):
    async def collector(_message):
        return None

    asyncio.run(audit.SessionAuditMiddleware(_app(status))(scope, _noop_receive, collector))


def test_classify_matrix():
    c = audit.classify
    assert c("POST", False, 200) == "created"
    assert c("POST", False, 202) == "created"
    assert c("POST", False, 400) == "init_failed"
    assert c("POST", True, 200) == "reused"
    assert c("POST", True, 202) == "reused"
    assert c("POST", True, 404) == "expired_or_unknown"
    assert c("POST", True, 400) == "bad_request"
    assert c("GET", True, 200) == "stream_open"
    assert c("GET", True, 406) == "stream_fail"
    assert c("DELETE", True, 200) == "terminated"
    assert c("POST", True, 500) == "other"


def test_middleware_records_created_and_reused(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("FLEET_SESSION_AUDIT", str(log))

    _run(200, _scope())
    _run(200, _scope(session="abcdef123456"))

    rows = _read(log)
    assert [r["event"] for r in rows] == ["created", "reused"]
    assert rows[0]["client"] == "100.79.163.65"
    assert rows[1]["session"] == "abcdef12"      # truncated to 8 chars
    assert rows[0]["ts"]                          # timestamp present


def test_middleware_records_expired_session(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("FLEET_SESSION_AUDIT", str(log))

    _run(404, _scope(session="deadbeef00"))

    row = _read(log)[0]
    assert (row["status"], row["event"]) == (404, "expired_or_unknown")


def test_middleware_ignores_non_mcp_paths(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("FLEET_SESSION_AUDIT", str(log))

    _run(200, _scope(path="/health"))

    assert not log.exists()


def test_write_swallows_errors(tmp_path, monkeypatch):
    # Point at a path whose parent is a *file*, so mkdir/open must fail.
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("FLEET_SESSION_AUDIT", str(blocker / "sub" / "audit.log"))

    audit.write_event({"event": "created"})  # must not raise


def test_rotation_keeps_one_backup(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("FLEET_SESSION_AUDIT", str(log))
    monkeypatch.setattr(audit, "_MAX_BYTES", 10)

    audit.write_event({"event": "created"})
    audit.write_event({"event": "reused"})

    assert (tmp_path / "audit.log.1").exists()
    assert _read(log)[0]["event"] == "reused"
