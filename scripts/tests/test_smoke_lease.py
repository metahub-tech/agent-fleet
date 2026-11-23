"""Tests for scripts/smoke_lease.py (pure check logic, no live server)."""
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import smoke_lease  # noqa: E402


# --------------------------------------------------------------------------- #
# _payload
# --------------------------------------------------------------------------- #

class _Res:
    def __init__(self, structured=None, text=None):
        self.structured_content = structured
        if text is not None:
            self.content = [type("C", (), {"text": text})()]
        else:
            self.content = []


def test_payload_prefers_structured_content():
    assert smoke_lease._payload(_Res(structured={"ok": True})) == {"ok": True}


def test_payload_parses_text_json():
    assert smoke_lease._payload(_Res(text='{"ok": false, "reason": "device_leased"}')) == {
        "ok": False, "reason": "device_leased"
    }


def test_payload_keeps_raw_text():
    assert smoke_lease._payload(_Res(text="boom")) == {"_raw": "boom"}


def test_denied_only_for_device_leased():
    assert smoke_lease._denied({"ok": False, "reason": "device_leased"})
    assert not smoke_lease._denied({"ok": False, "reason": "not_found"})
    assert not smoke_lease._denied({"ok": True})


# --------------------------------------------------------------------------- #
# run_checks against a miniature lease server
# --------------------------------------------------------------------------- #

class _FakeLease:
    """Mirrors the enforced semantics: free -> anyone, held -> holder only, calls renew."""

    def __init__(self, capability=True):
        self.holder = None
        self.idle = 0
        self.capability = capability

    def caller(self, name):
        mine = {"holder": None}  # the holder_name this session acquired with

        async def call(tool, **kw):
            if tool == "list_capabilities":
                tools = ["get_screen_size", "get_status", "acquire", "release"]
                if self.capability:
                    tools.append("human_dom_status")
                return {"capabilities": [{"id": "core", "tools": tools},
                                         {"id": "human_dom", "tools": ["human_dom_status"]}]}
            if tool == "acquire":
                who = kw.get("holder_name", name)
                if self.holder in (None, who):
                    self.holder = who
                    mine["holder"] = who
                    return {"acquired": True, "holder": who}
                return {"acquired": False, "current_holder": self.holder}
            if tool == "release":
                if self.holder == kw.get("holder_name", name):
                    self.holder = None
                    mine["holder"] = None
                    return {"released": True}
                return {"released": False}
            if self.holder not in (None, mine["holder"]):
                return {"ok": False, "reason": "device_leased", "current_holder": self.holder}
            self.idle = 0
            if tool == "get_screen_size":
                return {"width": 1920, "height": 1080}
            if tool == "get_status":
                return {"in_use": self.holder is not None, "idle_seconds": self.idle}
            return {"ok": True, "tool": tool}
        return call


def test_run_checks_all_pass_with_capability():
    srv = _FakeLease(capability=True)
    results = asyncio.run(smoke_lease.run_checks(srv.caller("A"), srv.caller("B"), "human_dom_status", "t"))
    failed = [r["check"] for r in results if not r["ok"]]
    assert not failed, failed
    assert len(results) == 12
    assert srv.holder is None  # cleaned up


def test_run_checks_skips_capability_when_absent():
    srv = _FakeLease(capability=False)
    results = asyncio.run(smoke_lease.run_checks(srv.caller("A"), srv.caller("B"), None, "t"))
    names = [r["check"] for r in results]
    assert any("skipped" in r["detail"] for r in results if "capability-tool" in r["check"])
    assert not [r for r in results if not r["ok"]]
    assert len(names) == 10


def test_run_checks_detects_enforcement_regression():
    class _NoEnforcement(_FakeLease):
        def caller(self, name):
            async def call(tool, **kw):
                if tool == "acquire" and self.holder is None:
                    self.holder = kw.get("holder_name", name)
                    return {"acquired": True, "holder": self.holder}
                if tool == "acquire":
                    return {"acquired": False, "current_holder": self.holder}
                if tool == "release":
                    self.holder = None
                    return {"released": True}
                if tool == "get_screen_size":
                    return {"width": 1, "height": 1}          # never denied
                if tool == "get_status":
                    return {"idle_seconds": 0}
                return {"ok": True}
            return call

    srv = _NoEnforcement()
    results = asyncio.run(smoke_lease.run_checks(srv.caller("A"), srv.caller("B"), "human_dom_status", "t"))
    failed = [r["check"] for r in results if not r["ok"]]
    assert "B core tool denied" in failed
    assert "B capability tool denied (human_dom_status)" in failed


# --------------------------------------------------------------------------- #
# CLI plumbing
# --------------------------------------------------------------------------- #

def test_url_from_host_and_port():
    args = smoke_lease._parse_args(["--host", "test-win11", "--port", "8766"])
    assert smoke_lease._url(args) == "http://test-win11:8766/mcp"


def test_url_from_full_url():
    args = smoke_lease._parse_args(["--url", "http://x:8769/mcp"])
    assert smoke_lease._url(args) == "http://x:8769/mcp"


def test_json_output_shape(tmp_path, monkeypatch, capsys):
    srv = _FakeLease()
    monkeypatch.setattr(smoke_lease, "_run", smoke_lease._run)  # keep import side effects none

    async def fake_run(url, args):
        results = await smoke_lease.run_checks(srv.caller("A"), srv.caller("B"), "human_dom_status", "t")
        print(json.dumps({"passed": sum(1 for r in results if r["ok"]), "total": len(results)}))
        return 0

    monkeypatch.setattr(smoke_lease, "_run", fake_run)
    assert smoke_lease.main(["--url", "http://x/mcp", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out == {"passed": 12, "total": 12}
