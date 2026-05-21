"""Tests for the smoke-test module + installer.smoke_tests() shapes."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fleet.smoke import SmokeResult, SmokeTest
from fleet.installers._android import _has_device_in_result

# Make platforms/common importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLATFORMS_DIR = _REPO_ROOT / "platforms"
if str(_PLATFORMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORMS_DIR))

from common._manifest import load_manifest  # noqa: E402
from fleet.installers._manifest_installer import ManifestInstaller  # noqa: E402
from fleet.installers._hooks import ROLE_HOOKS  # noqa: E402
from fleet.types import InstallContext, OSInfo  # noqa: E402


def _make_installer(platform: str, host_os: str) -> ManifestInstaller:
    """Build a ManifestInstaller with its role hooks attached."""
    m = load_manifest(_PLATFORMS_DIR / platform / "platform.toml")
    hooks = ROLE_HOOKS.get(m.id, {})
    return ManifestInstaller(
        m, host_os,
        preflight_hook=hooks.get("preflight_hook"),
        smoke_hook=hooks.get("smoke_hook"),
    )


# ---------------------------------------------------------------
# Each role declares at least one smoke test
# ---------------------------------------------------------------

# Parametrize over (platform, host_os) pairs — one per role×os
_INSTALLER_PARAMS = [
    ("macos", "macos"),      # mac-device
    ("android", "macos"),    # android-device on macos (MacosAndroidBridge equivalent)
    ("android", "linux"),    # android-device on linux (LinuxAndroidBridge equivalent)
    ("android", "windows"),  # android-device on windows (WindowsAndroidBridge equivalent)
    ("windows", "windows"),  # win-device (WindowsDesktop equivalent)
    ("ios", "macos"),        # ios-device (MacosIosBridge equivalent)
]


@pytest.mark.parametrize("platform,host_os", _INSTALLER_PARAMS)
def test_every_installer_declares_smoke_tests(platform, host_os):
    """Regression: a new installer must opt in to smoke testing — empty list
    silently skips the new UX safety net."""
    installer = _make_installer(platform, host_os)
    tests = installer.smoke_tests()
    assert len(tests) >= 1
    for t in tests:
        assert isinstance(t, SmokeTest)
        assert t.tool_name  # not empty
        assert t.description  # human-readable


# ---------------------------------------------------------------
# Android-bridge tests are shared across host OS
# ---------------------------------------------------------------

def test_android_bridge_smoke_tests_match_across_hosts():
    """Regression: changes to android-device's smoke tests must propagate to
    all three host installers via the shared _android_bridge_smoke_tests()
    helper.  Catches a future refactor that adds a smoke test on Mac but
    forgets Windows/Linux."""
    mac = [t.tool_name for t in _make_installer("android", "macos").smoke_tests()]
    linux = [t.tool_name for t in _make_installer("android", "linux").smoke_tests()]
    win = [t.tool_name for t in _make_installer("android", "windows").smoke_tests()]
    assert mac == linux == win


# ---------------------------------------------------------------
# _has_device_in_result parses list_devices tool output correctly
# ---------------------------------------------------------------

class _FakeTextItem:
    def __init__(self, text):
        self.text = text


class _FakeResult:
    def __init__(self, content):
        self.content = content


def test_has_device_in_result_recognizes_device_state():
    r = _FakeResult([_FakeTextItem('{"devices":[{"serial":"S","state":"device"}]}')])
    assert _has_device_in_result(r) is True


def test_has_device_in_result_rejects_unauthorized():
    r = _FakeResult([_FakeTextItem('{"devices":[{"serial":"S","state":"unauthorized"}]}')])
    assert _has_device_in_result(r) is False


def test_has_device_in_result_rejects_empty():
    r = _FakeResult([_FakeTextItem('{"devices":[]}')])
    assert _has_device_in_result(r) is False


def test_has_device_in_result_handles_garbage():
    r = _FakeResult([_FakeTextItem("not json at all")])
    assert _has_device_in_result(r) is False


# ---------------------------------------------------------------
# SmokeResult shape sanity
# ---------------------------------------------------------------

def test_smoke_result_default_fields():
    t = SmokeTest(tool_name="x", description="x")
    r = SmokeResult(test=t, ok=True)
    assert r.ok is True
    assert r.skipped is False
    assert r.error == ""


# ---------------------------------------------------------------
# _run_install must return BOTH ServerRoles (for snippet rendering)
# AND installer instances (for smoke testing).
# ---------------------------------------------------------------

def test_unwrap_exception_extracts_real_cause_from_exception_group():
    """Regression for v0.6.3-alpha smoke output: every test showed 'MCP
    connection failed: ExceptionGroup: unhandled errors in a TaskGroup
    (1 sub-exception)' which hid the real underlying error like
    ConnectionRefusedError or socket.gaierror.  The unwrapper walks
    `.exceptions` to surface the innermost cause."""
    from fleet.smoke import _unwrap_exception

    # Python 3.11+ ExceptionGroup
    inner = ConnectionRefusedError("[Errno 61] Connection refused")
    try:
        eg = ExceptionGroup("outer", [inner])  # type: ignore[name-defined]
    except NameError:
        # 3.10 fallback — synthesise the duck-typed shape
        class FakeGroup(Exception):
            def __init__(self, msg, excs):
                super().__init__(msg)
                self.exceptions = excs
        eg = FakeGroup("outer", [inner])

    out = _unwrap_exception(eg)
    assert "ConnectionRefusedError" in out
    assert "Connection refused" in out


def test_unwrap_exception_passes_through_plain_exception():
    from fleet.smoke import _unwrap_exception
    out = _unwrap_exception(ValueError("boom"))
    assert out == "ValueError: boom"


def test_run_install_returns_installer_instances_with_smoke_tests():
    """Regression for v0.6.2-alpha bug: smoke runner crashed with
    `AttributeError: 'ServerRole' object has no attribute 'smoke_tests'`
    because _run_install only returned ServerRole dataclasses.  Now it
    returns (server_roles, installers) so smoke can call .smoke_tests()."""
    from fleet.cli import _run_install
    from fleet.types import InstallContext, OSInfo

    osi = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    ctx = InstallContext(repo_root="/tmp/nonexistent-repo", os_info=osi,
                         dry_run=True, selected_network="tailscale", tailscale_hostname="mac-test")
    mac_installer = _make_installer("macos", "macos")
    result = _run_install([mac_installer], ctx)

    # Tuple return shape
    assert isinstance(result, tuple) and len(result) == 2
    server_roles, installers = result
    assert len(server_roles) == 1
    assert len(installers) == 1

    # The installer is the same instance we passed in, so smoke_tests() works
    assert installers[0] is mac_installer
    smoke = installers[0].smoke_tests()
    assert len(smoke) >= 1
