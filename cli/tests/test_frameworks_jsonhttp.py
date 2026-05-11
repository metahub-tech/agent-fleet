import json
from fleet.types import ServerRole
from fleet.frameworks.base import ServerRoleEntry
from fleet.frameworks.claude_code import ClaudeCodeConfig
from fleet.frameworks.cursor import CursorConfig


def _role(name, port):
    return ServerRole(role_id=name, display_name=name, hostname="test-host", port=port)


def test_claude_code_single_entry():
    fw = ClaudeCodeConfig()
    role = _role("mac-device", 8767)
    e = fw.render_entry(role)
    assert e == {"type": "http", "url": "http://test-host:8767/mcp"}


def test_claude_code_full_snippet():
    fw = ClaudeCodeConfig()
    entries = [ServerRoleEntry(role=_role("mac-device", 8767)),
               ServerRoleEntry(role=_role("android-device", 8768))]
    out = json.loads(fw.render_full_snippet(entries))
    assert "mcpServers" in out
    assert set(out["mcpServers"].keys()) == {"mac-device", "android-device"}
    assert out["mcpServers"]["mac-device"]["type"] == "http"


def test_cursor_same_shape_as_claude():
    fw = CursorConfig()
    role = _role("mac-device", 8767)
    e = fw.render_entry(role)
    assert e == {"type": "http", "url": "http://test-host:8767/mcp"}


def test_cursor_path():
    assert "~/.cursor/mcp.json" in CursorConfig().config_path_template
