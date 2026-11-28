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
    assert set(rec) <= {"ts", "started_at", "tool", "ms", "ok", "pid", "session", "holder", "build", "dirty"}
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
    assert set(rec) <= {"ts", "started_at", "tool", "ms", "ok", "pid", "session", "holder", "build", "dirty"}
    assert "started_at" in rec      # 用于区分排队/争用与工具本身耗时


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


# --- build 字段：让"跑的是哪份代码"可断言 -------------------------------

def test_build_id_is_cached_and_env_overridable(monkeypatch):
    import _tool_audit as ta
    ta._BUILD_CACHE.clear()
    monkeypatch.setenv("FLEET_BUILD_ID", "deadbee")
    assert ta.build_id() == "deadbee"          # 环境变量优先（CI/非 git 部署也能定版）
    monkeypatch.setenv("FLEET_BUILD_DIRTY", "true")
    ta._BUILD_CACHE.clear()
    info = ta.build_info()
    assert info == {"build": "deadbee", "dirty": True}
    monkeypatch.delenv("FLEET_BUILD_ID"); monkeypatch.delenv("FLEET_BUILD_DIRTY")
    ta._BUILD_CACHE.clear()
    first = ta.build_id()
    assert first == ta.build_id()              # 有缓存，不会每条记录都 fork git


def test_record_carries_build(tmp_path):
    path = tmp_path / "audit.jsonl"
    ta.append_record("tap", 1, True, path=path)
    rec = _lines(path)[0]
    assert rec["build"]


# --- dirty 的作用域：代码目录里的新增文件也算脏，本地资料不算 -------------

def _git_repo(path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "platforms").mkdir(); (path / "scripts").mkdir()
    (path / "platforms" / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_dirty_false_on_clean_code_dirs(tmp_path, monkeypatch):
    import _tool_audit as ta
    _git_repo(tmp_path)
    monkeypatch.setattr(ta, "repo_root", lambda: tmp_path)
    ta._BUILD_CACHE.clear()
    assert ta.build_info()["dirty"] is False


def test_untracked_local_notes_do_not_mark_dirty(tmp_path, monkeypatch):
    """.dsh/ 这类本地资料不该让设备判脏。"""
    import _tool_audit as ta
    _git_repo(tmp_path)
    (tmp_path / ".dsh").mkdir(); (tmp_path / ".dsh" / "notes.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ta, "repo_root", lambda: tmp_path)
    ta._BUILD_CACHE.clear()
    assert ta.build_info()["dirty"] is False


def test_untracked_new_py_in_code_dir_is_dirty(tmp_path, monkeypatch):
    """代码目录里新增未跟踪 .py（可能被 import）必须算脏 —— 这是 operator 指出的盲点。"""
    import _tool_audit as ta
    _git_repo(tmp_path)
    (tmp_path / "scripts" / "new_helper.py").write_text("y = 2\n", encoding="utf-8")
    monkeypatch.setattr(ta, "repo_root", lambda: tmp_path)
    ta._BUILD_CACHE.clear()
    assert ta.build_info()["dirty"] is True


def test_modified_tracked_file_is_dirty(tmp_path, monkeypatch):
    import _tool_audit as ta
    _git_repo(tmp_path)
    (tmp_path / "platforms" / "a.py").write_text("x = 2\n", encoding="utf-8")
    monkeypatch.setattr(ta, "repo_root", lambda: tmp_path)
    ta._BUILD_CACHE.clear()
    assert ta.build_info()["dirty"] is True
