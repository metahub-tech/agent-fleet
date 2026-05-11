import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class AntigravityConfig(BaseFrameworkConfig):
    framework_id = "antigravity"
    display_name = "Google Antigravity"
    config_format = "json"
    config_path_template = "~/.gemini/antigravity/mcp_config.json"

    def render_entry(self, role: ServerRole) -> dict:
        # Antigravity (Gemini CLI lineage) uses httpUrl field for streamable-http,
        # no explicit `type` / `transport`.
        return {"httpUrl": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def notes(self) -> str:
        return ("Antigravity → MCP Store → 'Manage MCP Servers' → 'View raw config' "
                "opens the mcp_config.json file. Merge the snippet above.")
