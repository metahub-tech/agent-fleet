from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ._env import setup_env
from ..types import GuidanceStep, InstallContext, InstallEvent, OSInfo, VerifyResult


class LinuxAndroidBridge(BaseInstaller):
    role_id = "android-device"
    display_name = "Android bridge on Linux (android-device)"
    port = 8768

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "linux"

    def preflight(self) -> list[str]:
        return []

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "android" / "scripts" / "setup-android-linux.sh"
        if ctx.dry_run:
            yield InstallEvent(self.role_id, "deps", f"[DRY RUN] would run {setup}")
            return
        if not setup.exists():
            yield InstallEvent(self.role_id, "preflight", f"setup script missing at {setup}", level="error")
            return
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, encoding="utf-8", errors="replace", env=setup_env(ctx, self.role_id))
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            yield InstallEvent(self.role_id, "install", line)
        proc.wait()
        if proc.returncode != 0:
            yield InstallEvent(self.role_id, "install", f"setup-android-linux.sh exited rc={proc.returncode}", level="error")

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

    def smoke_tests(self):
        from ._android import _android_bridge_smoke_tests
        return _android_bridge_smoke_tests()
