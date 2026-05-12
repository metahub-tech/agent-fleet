"""Tests for the smoke-test module + installer.smoke_tests() shapes."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from fleet.smoke import SmokeResult, SmokeTest
from fleet.installers.macos import (
    MacosDesktop, MacosAndroidBridge, _has_device_in_result,
)
from fleet.installers.linux import LinuxAndroidBridge
from fleet.installers.windows import WindowsDesktop, WindowsAndroidBridge


# ---------------------------------------------------------------
# Each role declares at least one smoke test
# ---------------------------------------------------------------

@pytest.mark.parametrize("installer_cls", [
    MacosDesktop,
    MacosAndroidBridge,
    LinuxAndroidBridge,
    WindowsDesktop,
    WindowsAndroidBridge,
])
def test_every_installer_declares_smoke_tests(installer_cls):
    """Regression: a new installer must opt in to smoke testing — empty list
    silently skips the new UX safety net."""
    tests = installer_cls().smoke_tests()
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
    mac = [t.tool_name for t in MacosAndroidBridge().smoke_tests()]
    linux = [t.tool_name for t in LinuxAndroidBridge().smoke_tests()]
    win = [t.tool_name for t in WindowsAndroidBridge().smoke_tests()]
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
