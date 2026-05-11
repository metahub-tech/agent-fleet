from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..types import InstallContext, InstallEvent, OSInfo, VerifyResult, GuidanceStep


class BaseInstaller(ABC):
    role_id: str = ""        # e.g. "macbox-gui" / "android-gui-win"
    display_name: str = ""
    port: int = 0

    @abstractmethod
    def is_supported_on(self, os_info: OSInfo) -> bool: ...

    @abstractmethod
    def preflight(self) -> list[str]:
        """Return human-readable list of missing prerequisites (empty = ready)."""

    @abstractmethod
    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        """Drive the per-platform setup script; yield events as install progresses."""

    @abstractmethod
    def verify(self) -> VerifyResult:
        """Probe the server and confirm it's serving MCP."""

    @abstractmethod
    def guidance_steps(self) -> list[GuidanceStep]:
        """Post-install operation guidance (permissions / authorization)."""
