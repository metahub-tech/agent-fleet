import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class ClaudeCodeConfig(BaseFrameworkConfig):
    framework_id = "claude-code"
    display_name = "Claude Code"
    config_format = "json"
    config_path_template = "~/.claude.json"

    def render_entry(self, role: ServerRole) -> dict:
        return {"type": "http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def cli_alternative(self) -> str | None:
        return None

    def notes(self) -> str:
        return ("Merge the mcpServers block into ~/.claude.json (top-level single-file state, "
                "NOT ~/.claude/settings.json). Restart Claude Code after editing.")
