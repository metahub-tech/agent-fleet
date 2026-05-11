import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class OpenClawConfig(BaseFrameworkConfig):
    framework_id = "openclaw"
    display_name = "OpenClaw"
    config_format = "json"
    config_path_template = "~/.openclaw/ (managed via `openclaw mcp` CLI; see openclaw docs)"

    def render_entry(self, role: ServerRole) -> dict:
        return {"transport": "streamable-http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        servers = {e.role.role_id: self.render_entry(e.role) for e in entries}
        body = {"mcp": {"servers": servers}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def cli_alternative(self) -> str | None:
        return ("For each entry, run:\n"
                "  openclaw mcp set <NAME> '{\"transport\":\"streamable-http\",\"url\":\"<URL>\"}'")

    def notes(self) -> str:
        return ("OpenClaw uses `transport: streamable-http` (not `type: http` like Claude Code). "
                "The `openclaw mcp set` CLI is the recommended way to apply each entry.")
