"""Windows installer tests — rewritten to use ManifestInstaller."""
from __future__ import annotations

import sys
from pathlib import Path

# Make platforms/common importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLATFORMS_DIR = _REPO_ROOT / "platforms"
if str(_PLATFORMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORMS_DIR))

from common._manifest import load_manifest  # noqa: E402
from fleet.installers._manifest_installer import ManifestInstaller  # noqa: E402
from fleet.types import OSInfo, InstallContext  # noqa: E402


def _osi(kind: str) -> OSInfo:
    system = {"macos": "Darwin", "windows": "Windows", "linux": "Linux"}.get(kind, kind)
    return OSInfo(system=system, version="1.0", arch="x86_64", is_apple_silicon=False)


class TestWindowsDesktopInstaller:
    """win-device (ManifestInstaller for windows/windows) replaces WindowsDesktop."""

    def setup_method(self):
        self.manifest = load_manifest(_PLATFORMS_DIR / "windows" / "platform.toml")
        self.installer = ManifestInstaller(self.manifest, "windows")

    def test_metadata(self):
        assert self.installer.role_id == "win-device"
        assert self.installer.port == 8766

    def test_role_id_is_win_device(self):
        assert self.installer.role_id == "win-device"

    def test_supported_only_on_windows(self):
        assert self.installer.is_supported_on(_osi("windows"))
        assert not self.installer.is_supported_on(_osi("macos"))
        assert not self.installer.is_supported_on(_osi("linux"))

    def test_dry_run_skips_subprocess(self):
        ctx = InstallContext(repo_root=str(_REPO_ROOT), os_info=_osi("windows"), dry_run=True)
        events = list(self.installer.install(ctx))
        assert any("DRY RUN" in e.message for e in events)


class TestAndroidWindowsInstaller:
    """android-device on windows replaces WindowsAndroidBridge."""

    def setup_method(self):
        self.manifest = load_manifest(_PLATFORMS_DIR / "android" / "platform.toml")
        self.installer = ManifestInstaller(self.manifest, "windows")

    def test_metadata(self):
        assert self.installer.role_id == "android-device"
        assert self.installer.port == 8768

    def test_role_id_is_android_device(self):
        assert self.installer.role_id == "android-device"

    def test_supported_on_windows(self):
        assert self.installer.is_supported_on(_osi("windows"))

    def test_dry_run_skips_subprocess(self):
        ctx = InstallContext(repo_root=str(_REPO_ROOT), os_info=_osi("windows"), dry_run=True)
        events = list(self.installer.install(ctx))
        assert any("DRY RUN" in e.message for e in events)
