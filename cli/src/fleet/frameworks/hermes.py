import yaml
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class HermesConfig(BaseFrameworkConfig):
    framework_id = "hermes"
    display_name = "Hermes Agent (Nous Research)"
    config_format = "yaml"
    config_path_template = "~/.hermes/config.yaml"

    def render_entry(self, role: ServerRole) -> dict:
        # Hermes auto-detects transport based on presence of `url` vs `command`.
        return {"url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcp_servers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)

    def notes(self) -> str:
        return ("Hermes uses YAML. After editing config.yaml, run `/reload-mcp` in the Hermes "
                "chat or restart the daemon. Use `hermes mcp test <name>` to verify connectivity.")
