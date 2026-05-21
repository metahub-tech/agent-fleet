"""Tests for ManifestInstaller + per-role hooks.

Uses real platform.toml manifests so the assertions track any future manifest
changes automatically (behaviour-preserving refactor coverage).

Run with:
    cd cli && PYTHONPATH=src python3 -m pytest tests/test_manifest_installer.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ------------------------------------------------------------------ #
# Make platforms/common importable in the cli test context            #
# ------------------------------------------------------------------ #
_REPO_ROOT = Path(__file__).resolve().parents[2]   # cli/ → agent-fleet/
_PLATFORMS_DIR = _REPO_ROOT / "platforms"
if str(_PLATFORMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORMS_DIR))

from common._manifest import load_manifest  # noqa: E402

from fleet.installers._manifest_installer import ManifestInstaller  # noqa: E402
from fleet.types import InstallContext, OSInfo  # noqa: E402


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _osi(kind: str) -> OSInfo:
    system = {"macos": "Darwin", "windows": "Windows", "linux": "Linux"}.get(kind, kind)
    return OSInfo(system=system, version="1.0", arch="x86_64", is_apple_silicon=False)


def _load(platform: str) -> "PlatformManifest":  # type: ignore[name-defined]
    return load_manifest(_PLATFORMS_DIR / platform / "platform.toml")


# ------------------------------------------------------------------ #
# Android-on-Linux basics                                             #
# ------------------------------------------------------------------ #

class TestAndroidLinuxInstaller:
    def setup_method(self):
        self.manifest = _load("android")
        self.installer = ManifestInstaller(self.manifest, "linux")

    def test_role_id(self):
        assert self.installer.role_id == "android-device"

    def test_port(self):
        assert self.installer.port == 8768

    def test_is_supported_on_linux(self):
        assert self.installer.is_supported_on(_osi("linux")) is True

    def test_is_not_supported_on_windows(self):
        # this instance targets linux only — windows should return False
        assert self.installer.is_supported_on(_osi("windows")) is False

    def test_is_not_supported_on_macos(self):
        # this instance targets linux only — macos should return False
        assert self.installer.is_supported_on(_osi("macos")) is False

    def test_is_not_supported_on_unknown(self):
        osi = OSInfo(system="FreeBSD", version="14", arch="x86_64", is_apple_silicon=False)
        assert self.installer.is_supported_on(osi) is False

    def test_dry_run_install_references_linux_script(self):
        ctx = InstallContext(
            repo_root=str(_REPO_ROOT),
            os_info=_osi("linux"),
            dry_run=True,
        )
        events = list(self.installer.install(ctx))
        assert len(events) == 1
        assert "DRY RUN" in events[0].message
        assert "setup-android-linux.sh" in events[0].message

    def test_guidance_steps_non_empty(self):
        steps = self.installer.guidance_steps()
        assert len(steps) >= 1
        # Each step should be a GuidanceStep with a title
        for step in steps:
            assert step.title

    def test_no_preflight_hook_returns_empty(self):
        assert self.installer.preflight() == []

    def test_no_smoke_hook_returns_empty(self):
        assert self.installer.smoke_tests() == []


# ------------------------------------------------------------------ #
# Android with hooks attached                                          #
# ------------------------------------------------------------------ #

class TestAndroidWithHooks:
    def setup_method(self):
        from fleet.installers._hooks import _android_device_preflight, _android_device_smoke
        self.manifest = _load("android")
        self.installer = ManifestInstaller(
            self.manifest, "macos",
            preflight_hook=_android_device_preflight,
            smoke_hook=_android_device_smoke,
        )

    def test_smoke_tests_non_empty(self):
        from fleet.smoke import SmokeTest
        tests = self.installer.smoke_tests()
        assert len(tests) >= 1
        for t in tests:
            assert isinstance(t, SmokeTest)
            assert t.tool_name
            assert t.description

    def test_smoke_tests_match_linux_android(self):
        """Regression: android smoke tests must be identical across all host OSes."""
        from fleet.installers._hooks import _android_device_smoke
        linux_inst = ManifestInstaller(self.manifest, "linux",
                                       smoke_hook=_android_device_smoke)
        win_inst = ManifestInstaller(self.manifest, "windows",
                                     smoke_hook=_android_device_smoke)
        mac_names = [t.tool_name for t in self.installer.smoke_tests()]
        linux_names = [t.tool_name for t in linux_inst.smoke_tests()]
        win_names = [t.tool_name for t in win_inst.smoke_tests()]
        assert mac_names == linux_names == win_names

    def test_preflight_on_macos_checks_brew(self):
        # On macOS, the android preflight asks for brew
        # Since brew may or may not be present in the CI environment,
        # we just assert the result is a list (possibly empty).
        result = self.installer.preflight()
        assert isinstance(result, list)

    def test_preflight_on_linux_returns_empty(self):
        from fleet.installers._hooks import _android_device_preflight
        linux_inst = ManifestInstaller(self.manifest, "linux",
                                       preflight_hook=_android_device_preflight)
        assert linux_inst.preflight() == []

    def test_preflight_on_windows_returns_empty(self):
        from fleet.installers._hooks import _android_device_preflight
        win_inst = ManifestInstaller(self.manifest, "windows",
                                     preflight_hook=_android_device_preflight)
        assert win_inst.preflight() == []


# ------------------------------------------------------------------ #
# Windows installer                                                    #
# ------------------------------------------------------------------ #

class TestWindowsInstaller:
    def setup_method(self):
        self.manifest = _load("windows")
        self.installer = ManifestInstaller(self.manifest, "windows")

    def test_role_id(self):
        assert self.installer.role_id == "win-device"

    def test_port(self):
        assert self.installer.port == 8766

    def test_is_supported_on_windows(self):
        assert self.installer.is_supported_on(_osi("windows")) is True

    def test_not_supported_on_linux(self):
        assert self.installer.is_supported_on(_osi("linux")) is False

    def test_dry_run_install_references_ps1(self):
        ctx = InstallContext(
            repo_root=str(_REPO_ROOT),
            os_info=_osi("windows"),
            dry_run=True,
        )
        events = list(self.installer.install(ctx))
        assert len(events) == 1
        assert "DRY RUN" in events[0].message
        assert ".ps1" in events[0].message

    def test_guidance_steps_non_empty(self):
        steps = self.installer.guidance_steps()
        assert len(steps) >= 1


# ------------------------------------------------------------------ #
# macOS installer                                                      #
# ------------------------------------------------------------------ #

class TestMacOSInstaller:
    def setup_method(self):
        self.manifest = _load("macos")
        self.installer = ManifestInstaller(self.manifest, "macos")

    def test_role_id(self):
        assert self.installer.role_id == "mac-device"

    def test_port(self):
        assert self.installer.port == 8767

    def test_is_supported_on_macos(self):
        assert self.installer.is_supported_on(_osi("macos")) is True

    def test_not_supported_on_windows(self):
        assert self.installer.is_supported_on(_osi("windows")) is False

    def test_dry_run_install_references_sh(self):
        ctx = InstallContext(
            repo_root=str(_REPO_ROOT),
            os_info=_osi("macos"),
            dry_run=True,
        )
        events = list(self.installer.install(ctx))
        assert len(events) == 1
        assert "DRY RUN" in events[0].message
        assert ".sh" in events[0].message

    def test_guidance_steps_non_empty(self):
        steps = self.installer.guidance_steps()
        assert len(steps) >= 1


# ------------------------------------------------------------------ #
# iOS installer                                                        #
# ------------------------------------------------------------------ #

class TestIOSInstaller:
    def setup_method(self):
        self.manifest = _load("ios")
        self.installer = ManifestInstaller(self.manifest, "macos")

    def test_role_id(self):
        assert self.installer.role_id == "ios-device"

    def test_port(self):
        assert self.installer.port == 8769

    def test_only_supported_on_macos(self):
        assert self.installer.is_supported_on(_osi("macos")) is True
        assert self.installer.is_supported_on(_osi("windows")) is False
        assert self.installer.is_supported_on(_osi("linux")) is False


# ------------------------------------------------------------------ #
# collect_options — android manifest                                   #
# ------------------------------------------------------------------ #

class TestCollectOptions:
    """Test collect_options with android manifest, mocking questionary."""

    def setup_method(self):
        self.manifest = _load("android")

    def _make_installer(self):
        return ManifestInstaller(self.manifest, "linux")

    def _ctx(self):
        return InstallContext(
            repo_root=str(_REPO_ROOT),
            os_info=_osi("linux"),
        )

    # --- path A: config file exists, user says yes → short-circuit ---

    def test_reuse_yes_returns_only_reuse_env(self, tmp_path, monkeypatch):
        """When the config file exists and user picks 'yes', collect_options
        returns {reuse_env: '1'} immediately — no mode prompt."""
        # Point config_reuse check_path to a real temp file
        config_file = tmp_path / "config.toml"
        config_file.write_text("[android]\nmode = 'usb'\n")

        # Patch the manifest's config_reuse to use our temp file
        monkeypatch.setattr(
            self.manifest, "config_reuse",
            {"check_path": str(config_file), "env": "ATB_ANDROID_REUSE_CONFIG"},
        )

        import questionary as _q
        confirm_mock = MagicMock(return_value=MagicMock(ask=MagicMock(return_value=True)))
        select_mock = MagicMock()

        installer = self._make_installer()
        with patch.object(_q, "confirm", confirm_mock), \
             patch.object(_q, "select", select_mock):
            result = installer.collect_options(self._ctx())

        assert result == {"ATB_ANDROID_REUSE_CONFIG": "1"}
        # select should NOT have been called (early return)
        select_mock.assert_not_called()

    # --- path B: config file exists, user says no → mode prompt fires ---

    def test_reuse_no_then_usb_returns_both_envs(self, tmp_path, monkeypatch):
        """When user declines reuse, collect_options sets reuse env to '0'
        then prompts for mode; returns both env vars."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("[android]\nmode = 'wireless'\n")

        monkeypatch.setattr(
            self.manifest, "config_reuse",
            {"check_path": str(config_file), "env": "ATB_ANDROID_REUSE_CONFIG"},
        )

        import questionary as _q
        confirm_mock = MagicMock(return_value=MagicMock(ask=MagicMock(return_value=False)))
        select_mock = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="usb")))

        installer = self._make_installer()
        with patch.object(_q, "confirm", confirm_mock), \
             patch.object(_q, "select", select_mock):
            result = installer.collect_options(self._ctx())

        assert result["ATB_ANDROID_REUSE_CONFIG"] == "0"
        assert result["ATB_ANDROID_MODE"] == "usb"

    # --- path C: no config file → mode prompt fires, no reuse env ---

    def test_no_config_file_prompts_mode_only(self, monkeypatch):
        """When the config file doesn't exist, only the mode prompt is shown."""
        # Ensure no existing config
        monkeypatch.setattr(
            self.manifest, "config_reuse",
            {"check_path": "/tmp/does-not-exist-in-any-real-location-xyzzy/config.toml",
             "env": "ATB_ANDROID_REUSE_CONFIG"},
        )

        import questionary as _q
        select_mock = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="wireless")))

        installer = self._make_installer()
        with patch.object(_q, "select", select_mock):
            result = installer.collect_options(self._ctx())

        # No reuse env because file didn't exist
        assert "ATB_ANDROID_REUSE_CONFIG" not in result
        assert result["ATB_ANDROID_MODE"] == "wireless"

    # --- path D: no config_reuse at all (e.g. windows/macos manifest) ---

    def test_manifest_with_no_options_returns_empty(self, monkeypatch):
        """Manifests that declare no options return {}."""
        win_manifest = _load("windows")
        installer = ManifestInstaller(win_manifest, "windows")
        ctx = InstallContext(repo_root=str(_REPO_ROOT), os_info=_osi("windows"))
        result = installer.collect_options(ctx)
        assert result == {}


# ------------------------------------------------------------------ #
# Hooks registry integrity                                             #
# ------------------------------------------------------------------ #

class TestHooksRegistry:
    def test_all_expected_roles_present(self):
        from fleet.installers._hooks import ROLE_HOOKS
        for role in ("mac-device", "ios-device", "android-device", "win-device"):
            assert role in ROLE_HOOKS

    def test_hook_callables(self):
        from fleet.installers._hooks import ROLE_HOOKS
        for role, hooks in ROLE_HOOKS.items():
            pf = hooks.get("preflight_hook")
            sm = hooks.get("smoke_hook")
            assert callable(pf), f"{role} preflight_hook not callable"
            assert callable(sm), f"{role} smoke_hook not callable"

    def test_android_preflight_hook_signature(self):
        """preflight_hook must accept host_os string."""
        from fleet.installers._hooks import ROLE_HOOKS
        hook = ROLE_HOOKS["android-device"]["preflight_hook"]
        result_linux = hook("linux")
        result_windows = hook("windows")
        assert isinstance(result_linux, list)
        assert isinstance(result_windows, list)
        assert result_linux == []
        assert result_windows == []
