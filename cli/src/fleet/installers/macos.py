from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ..types import (
    GuidanceStep, InstallContext, InstallEvent, OSInfo, VerifyResult,
)


class MacosDesktop(BaseInstaller):
    role_id = "mac-device"
    display_name = "macOS desktop (mac-device)"
    port = 8767

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "macos"

    def preflight(self) -> list[str]:
        missing = []
        if not _which("brew"):
            missing.append("Homebrew (brew). Install: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        return missing

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "macos" / "scripts" / "setup-macos.sh"
        if ctx.dry_run:
            yield InstallEvent(self.role_id, "deps", f"[DRY RUN] would run {setup}")
            return
        if not setup.exists():
            yield InstallEvent(self.role_id, "preflight", f"setup script missing at {setup}", level="error")
            return

        proc = subprocess.Popen(
            ["bash", str(setup)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            yield InstallEvent(self.role_id, "install", line)
        proc.wait()
        if proc.returncode != 0:
            yield InstallEvent(self.role_id, "install", f"setup-macos.sh exited rc={proc.returncode}", level="error")

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("macos_accessibility.yaml"),
            load_guidance_yaml("macos_screen_recording.yaml"),
            load_guidance_yaml("macos_automation.yaml"),
            load_guidance_yaml("macos_full_disk_access.yaml"),
        ]


class MacosAndroidBridge(BaseInstaller):
    role_id = "android-device"
    display_name = "Android bridge on macOS (android-device)"
    port = 8768

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "macos"

    def preflight(self) -> list[str]:
        m = []
        if not _which("brew"):
            m.append("Homebrew (brew)")
        return m

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "android" / "scripts" / "setup-android.sh"
        if ctx.dry_run:
            yield InstallEvent(self.role_id, "deps", f"[DRY RUN] would run {setup}")
            return
        if not setup.exists():
            yield InstallEvent(self.role_id, "preflight", f"setup script missing at {setup}", level="error")
            return
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            yield InstallEvent(self.role_id, "install", line)
        proc.wait()
        if proc.returncode != 0:
            yield InstallEvent(self.role_id, "install", f"setup-android.sh exited rc={proc.returncode}", level="error")

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("android_dev_options.yaml"),
            load_guidance_yaml("android_usb_debug.yaml"),
            load_guidance_yaml("android_wireless_pair.yaml"),
        ]


def _which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
