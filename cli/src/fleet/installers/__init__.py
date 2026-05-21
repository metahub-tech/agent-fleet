"""Per-(OS, role) installers — auto-discovered from platform manifests."""
from __future__ import annotations

import sys
from pathlib import Path

from .base import BaseInstaller
from ._manifest_installer import ManifestInstaller
from ._hooks import ROLE_HOOKS
from ..types import OSInfo

# Resolve the repo root and make platforms/common importable.
# cli/src/fleet/installers/__init__.py:
#   parents[0] = installers/  parents[1] = fleet/  parents[2] = src/
#   parents[3] = cli/         parents[4] = repo-root  (agent-fleet/)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLATFORMS_DIR = _REPO_ROOT / "platforms"
_PLATFORMS_COMMON = str(_PLATFORMS_DIR)
if _PLATFORMS_COMMON not in sys.path:
    sys.path.insert(0, _PLATFORMS_COMMON)

from common._manifest import discover_manifests  # type: ignore[import]  # noqa: E402


def discover_installers(platforms_dir: "str | Path | None" = None) -> "list[BaseInstaller]":
    """Build the installer list by scanning all platform manifests.

    For each manifest × each host_os it declares, one :class:`ManifestInstaller`
    is created and wired with the role's preflight/smoke hooks (from
    :data:`ROLE_HOOKS`).

    Args:
        platforms_dir: Path to the ``platforms/`` directory.  Defaults to the
            repo's ``platforms/`` folder (resolved relative to this file).
    """
    if platforms_dir is None:
        platforms_dir = _PLATFORMS_DIR
    out: list[BaseInstaller] = []
    for m in discover_manifests(platforms_dir):
        hooks = ROLE_HOOKS.get(m.id, {})
        for host_os in m.host_os:
            out.append(ManifestInstaller(
                m, host_os,
                preflight_hook=hooks.get("preflight_hook"),
                smoke_hook=hooks.get("smoke_hook"),
            ))
    return out


INSTALLER_REGISTRY: list[BaseInstaller] = discover_installers()


def filter_for_os(os_info: OSInfo) -> list[BaseInstaller]:
    return [i for i in INSTALLER_REGISTRY if i.is_supported_on(os_info)]


__all__ = [
    "BaseInstaller", "ManifestInstaller", "INSTALLER_REGISTRY",
    "discover_installers", "filter_for_os",
]
