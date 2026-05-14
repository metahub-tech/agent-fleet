from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ._env import setup_env
from ..types import GuidanceStep, InstallContext, InstallEvent, OSInfo, VerifyResult


def _run_setup_ps1(ctx: InstallContext, script_path: Path, role_id: str) -> Iterator[InstallEvent]:
    if ctx.dry_run:
        yield InstallEvent(role_id, "deps", f"[DRY RUN] would run {script_path}")
        return
    if not script_path.exists():
        yield InstallEvent(role_id, "preflight", f"setup script missing at {script_path}", level="error")
        return
    # Force PowerShell to emit UTF-8 to stdout (PS 5.1 default is system
    # codepage = GBK on Chinese Windows, which we'd then decode as UTF-8 and
    # get mojibake — every Chinese error message comes out as `���...`).
    # Setting [Console]::OutputEncoding inside the PS process BEFORE running
    # the script forces all child cmdlet output through UTF-8 too.
    ps_wrapped = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"& '{script_path}'"
    )
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_wrapped],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
        encoding="utf-8", errors="replace",
        env=setup_env(ctx, role_id),
    )
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if not line:
            continue
        yield InstallEvent(role_id, "install", line)
    proc.wait()
    if proc.returncode != 0:
        yield InstallEvent(role_id, "install", f"setup script exited rc={proc.returncode}", level="error")


class WindowsDesktop(BaseInstaller):
    role_id = "win-device"
    display_name = "Windows desktop (win-device)"
    port = 8766

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "windows"

    def preflight(self) -> list[str]:
        return []  # winget bundled on Win 10/11; powershell.exe always present

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        yield from _run_setup_ps1(
            ctx,
            Path(ctx.repo_root) / "platforms" / "windows" / "scripts" / "setup-windows.ps1",
            self.role_id,
        )

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [load_guidance_yaml("windows_postinstall.yaml")]

    def smoke_tests(self):
        from ..smoke import SmokeTest
        return [
            SmokeTest("get_winpc_status", {},
                description="server reachable"),
            SmokeTest("run_powershell", {"script": "Write-Output ok"},
                description="shell exec",
                hint_on_failure="setup-windows.ps1 probably exited without registering the scheduled task; check Get-ScheduledTask MCP-WinDevice"),
            SmokeTest("get_screen_size", {},
                description="GUI baseline (pywinauto)"),
            SmokeTest("take_screenshot", {},
                description="screen capture",
                timeout=10,
                hint_on_failure="If the user session is locked, take_screenshot returns the lock-screen image. Unlock the session or configure autologon for headless deployments."),
            SmokeTest("list_windows", {},
                description="window enumeration"),
        ]


class WindowsAndroidBridge(BaseInstaller):
    role_id = "android-device"
    display_name = "Android bridge on Windows (android-device)"
    port = 8768

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "windows"

    def preflight(self) -> list[str]:
        return []

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        yield from _run_setup_ps1(
            ctx,
            Path(ctx.repo_root) / "platforms" / "android" / "scripts" / "setup-android.ps1",
            self.role_id,
        )

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
