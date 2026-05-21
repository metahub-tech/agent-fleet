"""Generic ManifestInstaller — drives install/verify/preflight/smoke from a
PlatformManifest (platforms/*/platform.toml).  Platform-specific preflight and
smoke_tests come from the per-role hooks table in _hooks.py.

This is a **behaviour-preserving refactor** of the six hand-written installer
classes.  No existing behaviour should change; only the delivery mechanism is
generalised.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterator, TYPE_CHECKING

from .base import BaseInstaller
from ._env import setup_env
from ..guidance import load_guidance_yaml
from ..types import GuidanceStep, InstallContext, InstallEvent, OSInfo, VerifyResult

if TYPE_CHECKING:
    from ..smoke import SmokeTest

# Resolve the repo root relative to this file:
#   cli/src/fleet/installers/_manifest_installer.py → up 5 levels → repo root
_REPO_ROOT = Path(__file__).resolve().parents[5]


def _run_bash(ctx: InstallContext, script_path: Path, role_id: str) -> Iterator[InstallEvent]:
    """Run *script_path* with bash and stream lines as InstallEvents.

    Reproduces the exact subprocess pattern used by MacosDesktop.install(),
    MacosAndroidBridge.install(), MacosIosBridge.install(), and
    LinuxAndroidBridge.install().
    """
    if ctx.dry_run:
        yield InstallEvent(role_id, "deps", f"[DRY RUN] would run {script_path}")
        return
    if not script_path.exists():
        yield InstallEvent(role_id, "preflight", f"setup script missing at {script_path}", level="error")
        return
    proc = subprocess.Popen(
        ["bash", str(script_path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, encoding="utf-8", errors="replace",
        env=setup_env(ctx, role_id),
    )
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if not line:
            continue
        yield InstallEvent(role_id, "install", line)
    proc.wait()
    if proc.returncode != 0:
        yield InstallEvent(role_id, "install",
                           f"{script_path.name} exited rc={proc.returncode}", level="error")


# Import the PowerShell runner directly from windows.py so we share the
# identical UTF-8-encoding wrapper and never diverge.
from .windows import _run_setup_ps1  # noqa: E402


class ManifestInstaller(BaseInstaller):
    """A generic installer driven entirely by a :class:`PlatformManifest`.

    Args:
        manifest: The loaded platform manifest (``platforms/*/platform.toml``).
        host_os: The host OS string this instance targets — one of
            ``manifest.host_os`` (e.g. ``"macos"``, ``"windows"``, ``"linux"``).
        preflight_hook: Optional callable ``(host_os: str) -> list[str]``
            returning missing-prerequisite messages.  Replaces the old
            per-platform ``preflight()`` implementation.
        smoke_hook: Optional callable ``() -> list[SmokeTest]`` returning the
            smoke-test suite.  Replaces the old per-platform ``smoke_tests()``.
    """

    def __init__(
        self,
        manifest,  # PlatformManifest — avoid circular import at class-body level
        host_os: str,
        preflight_hook: "Callable[[str], list[str]] | None" = None,
        smoke_hook: "Callable[[], list[SmokeTest]] | None" = None,
    ) -> None:
        self._manifest = manifest
        self._host_os = host_os
        self._preflight_hook = preflight_hook
        self._smoke_hook = smoke_hook

        # Expose as class-level attributes so BaseInstaller consumers work
        self.role_id: str = manifest.id
        self.display_name: str = manifest.display_name
        self.port: int = manifest.port

    # ------------------------------------------------------------------
    # BaseInstaller abstract interface
    # ------------------------------------------------------------------

    def is_supported_on(self, os_info: OSInfo) -> bool:
        """True when ``os_info.kind`` is one of the manifest's ``host_os`` list."""
        return os_info.kind in self._manifest.host_os

    def preflight(self) -> list[str]:
        """Delegate to the role-specific hook; return [] if none registered."""
        if self._preflight_hook is not None:
            return self._preflight_hook(self._host_os)
        return []

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        """Run the host-OS-specific setup script.

        Script resolution: ``manifest.setup_script_for(host_os)`` → relative
        path from the platform directory → absolute via repo root.

        Runner selection: ``windows`` → PowerShell wrapper (same as
        ``WindowsDesktop``/``WindowsAndroidBridge``); anything else → bash
        (same as ``MacosDesktop``/``LinuxAndroidBridge``/…).
        """
        rel_script = self._manifest.setup_script_for(self._host_os)
        # The path stored in the manifest is relative to the platform directory
        # (e.g. "scripts/setup-android-linux.sh"), so resolve it from there.
        script_path = self._manifest.dir / rel_script

        if self._host_os == "windows":
            yield from _run_setup_ps1(ctx, script_path, self.role_id)
        else:
            yield from _run_bash(ctx, script_path, self.role_id)

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        return [load_guidance_yaml(name) for name in self._manifest.guidance]

    def smoke_tests(self) -> "list[SmokeTest]":
        if self._smoke_hook is not None:
            return self._smoke_hook()
        return []

    # ------------------------------------------------------------------
    # Generic option collection (replaces _select_android_config + the
    # android-specific option-collection block in cli.py)
    # ------------------------------------------------------------------

    def collect_options(self, ctx: InstallContext) -> dict[str, str]:
        """Collect user choices for all manifest ``[install.options]`` entries.

        Reproduces the UX of ``_select_android_config()`` in a generic way:

        1. If ``manifest.config_reuse`` has a ``check_path`` that EXISTS
           (expanded via ``~``): display its contents in a Rich Panel, then ask
           a questionary ``confirm`` "Reuse this config?".
           - **Yes** → return ``{reuse_env: "1"}`` immediately (skip options).
           - **No** → accumulate ``{reuse_env: "0"}`` and continue.
        2. For each ``name, opt`` in ``manifest.options.items()``: render a
           ``questionary.select`` with ``Choice(label, value=value)`` entries
           (matching the ``{value, label}`` shape added in Task 1b).  Set
           ``result[opt["env"]] = chosen_value``.
        3. Return the accumulated dict.
        """
        import questionary
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        result: dict[str, str] = {}

        # --- config-reuse short-circuit (e.g. android) ---
        config_reuse = self._manifest.config_reuse
        if config_reuse:
            check_path = Path(config_reuse.get("check_path", "")).expanduser()
            reuse_env = config_reuse.get("env", "")
            if check_path and check_path.exists():
                console.print(
                    f"\n[bold]Existing {self.role_id} config[/bold] "
                    f"[dim]({check_path})[/dim]:"
                )
                console.print(
                    Panel(check_path.read_text(encoding="utf-8", errors="replace").rstrip())
                )
                reuse = questionary.confirm("Reuse this config?", default=True).ask()
                if reuse is None:  # Ctrl-C
                    console.print("[yellow]Cancelled.[/yellow]")
                    sys.exit(1)
                if reuse:
                    return {reuse_env: "1"}
                # User said no — record that and fall through to options
                result[reuse_env] = "0"

        # --- per-option prompts ---
        for _name, opt in self._manifest.options.items():
            choices_raw = opt.get("choices", [])
            choices = [
                questionary.Choice(c["label"], value=c["value"])
                for c in choices_raw
            ]
            chosen = questionary.select(opt["prompt"], choices=choices).ask()
            if chosen is None:  # Ctrl-C
                console.print("[yellow]Cancelled.[/yellow]")
                sys.exit(1)
            result[opt["env"]] = chosen

        return result
