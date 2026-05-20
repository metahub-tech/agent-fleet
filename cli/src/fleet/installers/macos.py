from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ._env import setup_env
from ._android import _android_bridge_smoke_tests
from ._ios import _ios_bridge_smoke_tests
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


class MacosIosBridge(BaseInstaller):
    role_id = "ios-device"
    display_name = "iOS bridge on macOS (ios-device)"
    port = 8769

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "macos"

    def preflight(self) -> list[str]:
        m = []
        if not _which("brew"):
            m.append("Homebrew (brew). Install: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        # Must have brew python@3.12; system Python 3.9.6 can't run fastmcp
        import subprocess as _sp
        py312_ok = False
        for cand in [
            "/opt/homebrew/opt/python@3.12/bin/python3.12",
            "/usr/local/opt/python@3.12/bin/python3.12",
            "/opt/homebrew/bin/python3.12",
            "/usr/local/bin/python3.12",
        ]:
            if Path(cand).is_file():
                py312_ok = True
                break
        if not py312_ok:
            m.append("python@3.12 via Homebrew. Run: brew install python@3.12")
        # Warn if Xcode CLT only (no full Xcode) — WDA needs full Xcode
        try:
            r = _sp.run(["xcode-select", "-p"], capture_output=True, text=True, timeout=5)
            xcode_path = r.stdout.strip()
            if r.returncode != 0 or not xcode_path:
                m.append("Xcode (full Xcode.app required to build WDA, not just Command Line Tools). "
                          "Install from the Mac App Store or developer.apple.com.")
            elif "CommandLineTools" in xcode_path:
                # Not a hard error — setup can proceed, but WDA won't build without full Xcode
                m.append("WARNING: xcode-select points to CLT only. WDA requires full Xcode.app. "
                          "Install Xcode.app and run: sudo xcode-select -s /Applications/Xcode.app")
        except Exception:
            pass
        return m

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "ios" / "scripts" / "setup-ios.sh"
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
            yield InstallEvent(self.role_id, "install", f"setup-ios.sh exited rc={proc.returncode}", level="error")

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("ios_wda_deploy.yaml"),
        ]

    def smoke_tests(self):
        return _ios_bridge_smoke_tests()


def _which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
