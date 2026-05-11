import json
import yaml as pyyaml
from fleet.types import ServerRole
from fleet.frameworks.base import ServerRoleEntry
from fleet.frameworks.cline import ClineConfig
from fleet.frameworks.openclaw import OpenClawConfig
from fleet.frameworks.antigravity import AntigravityConfig
from fleet.frameworks.hermes import HermesConfig


def _role(name, port):
    return ServerRole(role_id=name, display_name=name, hostname="test-host", port=port)


def test_cline_renders_type_http():
    fw = ClineConfig()
    e = fw.render_entry(_role("mac-device", 8767))
    assert e == {"type": "http", "url": "http://test-host:8767/mcp"}


def test_openclaw_uses_transport_field():
    fw = OpenClawConfig()
    e = fw.render_entry(_role("mac-device", 8767))
    assert e == {"transport": "streamable-http", "url": "http://test-host:8767/mcp"}


def test_openclaw_snippet_uses_mcp_servers_nesting():
    fw = OpenClawConfig()
    out = json.loads(fw.render_full_snippet([ServerRoleEntry(role=_role("x", 1))]))
    assert "mcp" in out and "servers" in out["mcp"]


def test_openclaw_cli_alt_present():
    fw = OpenClawConfig()
    assert fw.cli_alternative()
    assert "openclaw mcp set" in fw.cli_alternative()


def test_antigravity_uses_httpUrl():
    fw = AntigravityConfig()
    e = fw.render_entry(_role("mac-device", 8767))
    assert e == {"httpUrl": "http://test-host:8767/mcp"}


def test_hermes_yaml_output():
    fw = HermesConfig()
    out = fw.render_full_snippet([ServerRoleEntry(role=_role("mac-device", 8767))])
    parsed = pyyaml.safe_load(out)
    assert "mcp_servers" in parsed
    assert parsed["mcp_servers"]["mac-device"]["url"] == "http://test-host:8767/mcp"
