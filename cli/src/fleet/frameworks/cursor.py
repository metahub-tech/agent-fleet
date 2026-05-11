import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class CursorConfig(BaseFrameworkConfig):
    framework_id = "cursor"
    display_name = "Cursor"
    config_format = "json"
    config_path_template = "~/.cursor/mcp.json"

    def render_entry(self, role: ServerRole) -> dict:
        return {"type": "http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def notes(self) -> str:
        return "Write the snippet to ~/.cursor/mcp.json (create parent dirs if missing)."
