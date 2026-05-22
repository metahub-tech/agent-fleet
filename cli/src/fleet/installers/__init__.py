"""Per-(OS, role) installers — auto-discovered from platform manifests."""
from __future__ import annotations

import sys
from pathlib import Path

from .base import BaseInstaller
from ._manifest_installer import ManifestInstaller
from ._hooks import ROLE_HOOKS
from ..types import OSInfo

def _resolve_platforms_dir(start: "Path | None" = None, cwd: "Path | None" = None) -> Path:
    """Locate the repo's ``platforms/`` dir (holds the ``common`` package + each
    platform's manifest).

    Dev checkout: this file is ``cli/src/fleet/installers/__init__.py`` so the repo
    root is ``parents[4]``. When the CLI is pip/uvx-installed, ``__file__`` lands in
    ``site-packages`` and no longer points at the repo, so fall back to the current
    working directory (and its parents) — the CLI is always run from the repo root,
    same assumption ``cli.py`` makes with ``repo_root=Path.cwd()``.
    """
    start = (start or Path(__file__)).resolve()
    cwd = (cwd or Path.cwd()).resolve()
    candidates: list[Path] = []
    if len(start.parents) > 4:
        candidates.append(start.parents[4] / "platforms")          # dev checkout (parents[4] valid iff >=5 parents)
    candidates += [base / "platforms" for base in (cwd, *cwd.parents)]  # installed, run from repo (or a subdir)
    for c in candidates:
        if (c / "common" / "_manifest.py").is_file():
            return c
    raise ModuleNotFoundError(
        "agent-fleet: could not locate the 'platforms/' directory (which holds the "
        "'common' package + platform manifests). Run the installer from inside an "
        f"agent-fleet checkout. Tried __file__={start} and cwd={cwd}."
    )


_PLATFORMS_DIR = _resolve_platforms_dir()
if str(_PLATFORMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORMS_DIR))

from common._manifest import discover_manifests  # type: ignore[import]  # noqa: E402


def discover_installers(platforms_dir: "str | Path | None" = None) -> "list[BaseInstaller]":
    """Build the installer list by scanning all platform manifests.

    For each manifest × each host_os it declares, one :class:`ManifestInstaller`
    is created and wired with the role's preflight/smoke hooks (from
    :data:`ROLE_HOOKS`).

    Args:
        platforms_dir: Path to the ``platforms/`` directory.  Defaults to
            ``_PLATFORMS_DIR`` (located at import time from ``__file__`` in a dev
            checkout, else from the current working directory).
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
