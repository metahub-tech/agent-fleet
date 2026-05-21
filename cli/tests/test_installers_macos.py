"""macOS installer tests — rewritten to use ManifestInstaller."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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


class TestMacDeviceInstaller:
    """mac-device (ManifestInstaller for macos/macos) replaces MacosDesktop."""

    def setup_method(self):
        self.manifest = load_manifest(_PLATFORMS_DIR / "macos" / "platform.toml")
        self.installer = ManifestInstaller(self.manifest, "macos")

    def test_metadata(self):
        assert self.installer.role_id == "mac-device"
        assert self.installer.port == 8767

    def test_role_id_is_mac_device(self):
        assert self.installer.role_id == "mac-device"

    def test_supported_only_on_macos(self):
        assert self.installer.is_supported_on(_osi("macos"))
        assert not self.installer.is_supported_on(_osi("windows"))
        assert not self.installer.is_supported_on(_osi("linux"))

    def test_install_dry_run_skips_subprocess(self):
        ctx = InstallContext(
            repo_root=str(_REPO_ROOT),
            os_info=_osi("macos"),
            dry_run=True,
        )
        with patch("subprocess.Popen") as mock_popen:
            list(self.installer.install(ctx))
            assert not mock_popen.called


class TestAndroidMacosInstaller:
    """android-device on macos replaces MacosAndroidBridge."""

    def setup_method(self):
        self.manifest = load_manifest(_PLATFORMS_DIR / "android" / "platform.toml")
        self.installer = ManifestInstaller(self.manifest, "macos")

    def test_metadata(self):
        assert self.installer.role_id == "android-device"
        assert self.installer.port == 8768

    def test_role_id_is_android_device(self):
        assert self.installer.role_id == "android-device"

    def test_supported_on_macos(self):
        assert self.installer.is_supported_on(_osi("macos"))

    def test_supported_on_all_declared_host_os(self):
        # android-device manifest declares support for windows, macos, linux
        assert self.installer.is_supported_on(_osi("macos"))
        assert self.installer.is_supported_on(_osi("windows"))
        assert self.installer.is_supported_on(_osi("linux"))

    def test_not_supported_on_unknown_os(self):
        osi = OSInfo(system="FreeBSD", version="14", arch="x86_64", is_apple_silicon=False)
        assert not self.installer.is_supported_on(osi)

    def test_install_dry_run_skips_subprocess(self):
        ctx = InstallContext(
            repo_root=str(_REPO_ROOT),
            os_info=_osi("macos"),
            dry_run=True,
        )
        with patch("subprocess.Popen") as mock_popen:
            list(self.installer.install(ctx))
            assert not mock_popen.called
