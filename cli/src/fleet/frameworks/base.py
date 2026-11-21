from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

from ..types import ServerRole


@dataclass
class ServerRoleEntry:
    role: ServerRole


class BaseFrameworkConfig(ABC):
    framework_id: str = ""
    display_name: str = ""
    config_format: Literal["json", "yaml"] = "json"
    config_path_template: str = ""   # ~/.foo/bar.json
    # Directory this client loads agent skills from, when it supports on-disk
    # skills (Claude Code, DeepSeek Harness, ...). None = no skill directory:
    # the wizard then prints the manual `scripts/install_skills.py` command.
    skills_dir: Optional[str] = None

    @abstractmethod
    def render_entry(self, role: ServerRole) -> dict:
        """Return the framework-specific dict for a single MCP server entry."""

    @abstractmethod
    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        """Return the complete snippet (including the outer mcpServers / mcp.servers / etc. wrapper)."""

    def cli_alternative(self) -> Optional[str]:
        """Return an equivalent CLI command string, if the framework offers one."""
        return None

    def notes(self) -> str:
        """Free-text notes printed to the user. Subclasses override."""
        return ""
