"""工具审计：只记 工具名/耗时/成败，任何失败都不能影响工具调用。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _tool_audit as ta  # noqa: E402


class _Ctx:
    class message:  # noqa: N801 - 模拟 fastmcp 的上下文形状
        name = "take_screenshot"


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_TOOL_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("FLEET_TOOL_AUDIT", raising=False)
    yield


def test_records_tool_ms_ok(tmp_path):
    path = tmp_path / "audit.jsonl"
    ta.append_record("take_screenshot", 12, True, path=path)
    rec = _lines(path)[0]
    assert rec["tool"] == "take_screenshot"
    assert rec["ms"] == 12
    assert rec["ok"] is True
    assert "ts" in rec and "pid" in rec


def test_record_has_no_arguments_or_result_fields(tmp_path):
    """隐私边界：只允许固定几个字段，绝不含 args/result/error。"""
    path = tmp_path / "audit.jsonl"
    ta.append_record("tap", 3, False, path=path, session="abcd1234")
    rec = _lines(path)[0]
    assert set(rec) <= {"ts", "tool", "ms", "ok", "pid", "session"}
    assert rec["session"] == "abcd1234"


def test_disabled_by_env(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("FLEET_TOOL_AUDIT", "0")
    ta.append_record("tap", 1, True, path=path)
    assert not path.exists()


def test_append_failure_never_raises(tmp_path):
    """路径不可写时必须静默（审计不能把工具调用带崩）。"""
    ta.append_record("tap", 1, True, path=tmp_path)  # 传目录 → OSError


def test_middleware_records_success(tmp_path):
    import asyncio
    mw = ta.ToolAuditLog(path=tmp_path / "audit.jsonl")

    async def call_next(_ctx):
        return {"ok": True}

    out = asyncio.run(mw.on_call_tool(_Ctx(), call_next))
    assert out == {"ok": True}
    rec = _lines(tmp_path / "audit.jsonl")[0]
    assert rec["tool"] == "take_screenshot" and rec["ok"] is True


def test_middleware_records_failure_and_reraises(tmp_path):
    import asyncio
    mw = ta.ToolAuditLog(path=tmp_path / "audit.jsonl")

    async def call_next(_ctx):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(mw.on_call_tool(_Ctx(), call_next))
    rec = _lines(tmp_path / "audit.jsonl")[0]
    assert rec["ok"] is False


def test_rotation_keeps_one_backup(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("x" * 200 + "\n", encoding="utf-8")
    ta.append_record("tap", 1, True, path=path, max_bytes=100)
    assert path.with_suffix(path.suffix + ".1").exists()
    assert path.stat().st_size < 200


def test_audit_enabled_default_on(monkeypatch):
    monkeypatch.delenv("FLEET_TOOL_AUDIT", raising=False)
    assert ta.audit_enabled() is True


# --- holder 归属：只记 acquire 声明的名字，且绑定到会话 --------------------

def test_middleware_records_holder_from_acquire(tmp_path):
    import asyncio

    class _Ctx:
        class message:
            name = "acquire"
            arguments = {"holder_name": "agent-A"}

    mw = ta.ToolAuditLog(path=tmp_path / "audit.jsonl")

    async def call_next(_ctx):
        return {"ok": True}

    asyncio.run(mw.on_call_tool(_Ctx(), call_next))
    rec = _lines(tmp_path / "audit.jsonl")[0]
    assert rec["holder"] == "agent-A"
    assert set(rec) <= {"ts", "tool", "ms", "ok", "pid", "session", "holder"}


def _ctx(name, args=None, session="sess-1"):
    """构造带 session 的上下文（形状与 fastmcp 一致）。"""
    class _Inner:
        pass
    inner = _Inner()
    inner.session_id = session

    class _Ctx:
        class message:
            pass
    _Ctx.message.name = name
    _Ctx.message.arguments = args or {}
    _Ctx.fastmcp_context = inner
    return _Ctx


def test_middleware_uses_cached_holder_for_later_calls(tmp_path):
    """acquire 声明的 holder 要绑定到该会话，后续调用继承它（否则无法把多 agent 分开）。"""
    import asyncio

    mw = ta.ToolAuditLog(path=tmp_path / "audit.jsonl")

    async def call_next(_ctx):
        return {"ok": True}

    asyncio.run(mw.on_call_tool(_ctx("acquire", {"holder_name": "agent-B"}), call_next))
    asyncio.run(mw.on_call_tool(_ctx("get_screen_size"), call_next))
    recs = _lines(tmp_path / "audit.jsonl")
    assert recs[0]["holder"] == "agent-B"
    assert recs[1]["holder"] == "agent-B"      # 继承
    assert recs[0]["session"] == recs[1]["session"] == "sess-1"


def test_holder_is_scoped_per_session(tmp_path):
    """不同会话不共享 holder：A 的 acquire 不能让 B 的调用也带上 A 的名字。"""
    import asyncio

    mw = ta.ToolAuditLog(path=tmp_path / "audit.jsonl")

    async def call_next(_ctx):
        return {"ok": True}

    asyncio.run(mw.on_call_tool(_ctx("acquire", {"holder_name": "agent-A"}, session="s1"), call_next))
    asyncio.run(mw.on_call_tool(_ctx("get_screen_size", session="s2"), call_next))
    recs = _lines(tmp_path / "audit.jsonl")
    assert recs[0]["holder"] == "agent-A"
    assert "holder" not in recs[1]
