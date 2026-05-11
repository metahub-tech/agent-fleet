import pytest
from fleet.frameworks.base import BaseFrameworkConfig, ServerRoleEntry


class DummyFramework(BaseFrameworkConfig):
    framework_id = "dummy"
    display_name = "Dummy"
    config_format = "json"
    config_path_template = "~/.dummy.json"

    def render_entry(self, role):
        return {"url": role.url}

    def render_full_snippet(self, entries):
        import json
        d = {"servers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(d, indent=2)


def test_base_framework_required_fields():
    with pytest.raises(TypeError):
        BaseFrameworkConfig()  # abstract


def test_dummy_render():
    from fleet.types import ServerRole
    role = ServerRole(role_id="x", display_name="X", hostname="h", port=1234)
    fw = DummyFramework()
    entry = fw.render_entry(role)
    assert entry["url"] == "http://h:1234/mcp"
