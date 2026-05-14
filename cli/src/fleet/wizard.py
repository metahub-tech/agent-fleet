"""Wizard orchestration. Interactive prompts are isolated in cli.py for testability."""
from __future__ import annotations

from typing import Literal

from .types import InstallContext, OSInfo, ServerRole


def build_install_context(
    *, repo_root: str, os_info: OSInfo, dry_run: bool,
    network: Literal["lan", "tailscale"], tailscale_hostname: str | None,
    android_mode: str | None = None, android_reuse_config: bool = False,
) -> InstallContext:
    return InstallContext(
        repo_root=repo_root,
        os_info=os_info,
        dry_run=dry_run,
        selected_network=network,
        tailscale_hostname=tailscale_hostname,
        android_mode=android_mode,
        android_reuse_config=android_reuse_config,
    )


def render_install_summary(*, tailscale_hostname: str | None, deployed_roles: list[ServerRole]) -> str:
    lines = ["🎉 Done!", "", "  This machine"]
    if tailscale_hostname:
        lines.append(f"    Tailscale hostname : {tailscale_hostname}")
    lines.append("    Endpoints:")
    for r in deployed_roles:
        lines.append(f"      {r.role_id:<13} →  {r.url}")
    lines.append("")
    lines.append("  Re-run wizard to modify: uvx agent-fleet setup")
    return "\n".join(lines)
