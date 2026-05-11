import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class ClineConfig(BaseFrameworkConfig):
    framework_id = "cline"
    display_name = "Cline (VSCode extension)"
    config_format = "json"
    config_path_template = (
        "VSCode user settings.json (path varies by OS); "
        "merge under cline.mcpServers"
    )

    def render_entry(self, role: ServerRole) -> dict:
        return {"type": "http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def notes(self) -> str:
        return ("Cline reads MCP config from VSCode user settings. "
                "Open Command Palette → 'Preferences: Open User Settings (JSON)' "
                "and add `cline.mcpServers` with the snippet above.")
