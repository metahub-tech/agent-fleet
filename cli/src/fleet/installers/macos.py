from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ._env import setup_env
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
            bufsize=1, encoding="utf-8", errors="replace",
            env=setup_env(ctx, self.role_id),
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

    def smoke_tests(self):
        from ..smoke import SmokeTest
        return [
            SmokeTest("get_mac_status", {},
                description="server reachable"),
            SmokeTest("run_zsh", {"script": "echo ok"},
                description="shell exec",
                hint_on_failure="setup-macos.sh probably exited without starting the launchd plist; check ~/Library/LaunchAgents/cc.metahub.mac-device.plist + logs/"),
            SmokeTest("get_screen_size", {},
                description="GUI baseline (pyautogui)",
                hint_on_failure="pyautogui import failed; venv missing pyobjc-framework-Quartz or similar"),
            SmokeTest("take_screenshot", {},
                description="Screen Recording TCC",
                timeout=12,
                hint_on_failure="System Settings → Privacy & Security → Screen Recording → enable BOTH 'Python' and 'python3.12'; then `launchctl unload + load ~/Library/LaunchAgents/cc.metahub.mac-device.plist`"),
            SmokeTest("run_applescript", {"script": 'return "ok"'},
                description="Automation TCC",
                hint_on_failure="System Settings → Privacy & Security → Automation → expand Terminal → check System Events"),
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
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, encoding="utf-8", errors="replace", env=setup_env(ctx, self.role_id))
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

    def smoke_tests(self):
        from ..smoke import SmokeTest
        return _android_bridge_smoke_tests()


def _android_bridge_smoke_tests():
    """Shared smoke tests for the android-device role regardless of host OS
    (Mac / Windows / Linux all run the same android_mcp.py server)."""
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_android_status", {},
            description="server reachable"),
        SmokeTest("list_devices", {},
            description="ADB sees at least one device",
            hint_on_failure="Plug in via USB (and accept the 'Allow USB debugging' prompt on the phone), OR run setup-android again and pick Wireless/Hybrid",
            success_predicate=lambda r: _has_device_in_result(r)),
        SmokeTest("get_screen_size", {},
            description="device responsive",
            hint_on_failure="adb sees the device but it's unauthorized — unplug + replug + accept the on-screen prompt"),
        SmokeTest("take_screenshot", {},
            description="screencap via adb exec-out",
            timeout=10),
        SmokeTest("current_app", {},
            description="dumpsys focused app",
            optional=True,
            hint_on_failure="(optional) some OEM ROMs strip dumpsys; non-blocking"),
    ]


def _has_device_in_result(result) -> bool:
    """Inspect list_devices tool result and return True iff at least one device is present."""
    import json
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        devs = payload.get("devices") or []
        if any(d.get("state") == "device" for d in devs):
            return True
    return False


def _which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
