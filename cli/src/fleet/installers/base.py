from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, TYPE_CHECKING

from ..types import InstallContext, InstallEvent, OSInfo, VerifyResult, GuidanceStep

if TYPE_CHECKING:
    from ..smoke import SmokeTest


class BaseInstaller(ABC):
    role_id: str = ""        # e.g. "mac-device" / "win-device" / "android-device"
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

    def smoke_tests(self) -> list["SmokeTest"]:
        """Representative tool calls to verify the server actually works
        end-to-end (TCC perms, device presence, venv deps).

        Empty list = no smoke tests for this role.  Each test is a SmokeTest
        that the wizard's runner calls via streamable-http MCP client and
        renders pass/fail in a summary table.
        """
        return []
