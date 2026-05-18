"""Tests for _resolve_device and _build_instructions (T3a of v0.7.0)."""
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SERVER_DIR))

# Provide a fake adb so module import succeeds in environments without one.
# Individual tests monkeypatch _detect_devices, so the binary is never actually
# invoked — it just needs to exist so _resolve_adb() in module import doesn't
# raise FileNotFoundError.
if not os.environ.get("ATB_ANDROID_ADB"):
    _fake = Path(tempfile.gettempdir()) / "fake_adb_for_tests"
    if not _fake.exists():
        _fake.write_text("#!/bin/sh\nexit 0\n")
        _fake.chmod(0o755)
    os.environ["ATB_ANDROID_ADB"] = str(_fake)

import android_device_mcp as m  # noqa: E402
from _aliases import DeviceInfo  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def no_overrides(monkeypatch):
    """No alias-file overrides — pure derived aliases."""
    monkeypatch.setattr(m, "_load_alias_overrides", lambda: {})


@pytest.fixture(autouse=True)
def fresh_session_defaults(monkeypatch):
    """Ensure each test starts with an empty per-session sticky map."""
    monkeypatch.setattr(m, "_session_defaults", {})


def _patch_detect(monkeypatch, devices: list[DeviceInfo]):
    monkeypatch.setattr(m, "_detect_devices", lambda: list(devices))


# ---------------------------------------------------------------------------
# _resolve_device
# ---------------------------------------------------------------------------

class TestResolveDeviceExplicit:
    def test_explicit_serial_match(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        assert m._resolve_device("AAA111") == "AAA111"
        assert m._resolve_device("BBB222") == "BBB222"

    def test_explicit_alias_match(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        assert m._resolve_device("google-pixel-7") == "AAA111"
        assert m._resolve_device("samsung-sm-s908u") == "BBB222"

    def test_explicit_alias_with_override(self, monkeypatch):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
        ])
        monkeypatch.setattr(m, "_load_alias_overrides", lambda: {"AAA111": "qa-phone"})
        assert m._resolve_device("qa-phone") == "AAA111"

    def test_unknown_device_raises(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
        ])
        with pytest.raises(RuntimeError, match="unknown device 'nope'"):
            m._resolve_device("nope")

    def test_unknown_device_error_lists_known(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        with pytest.raises(RuntimeError) as ei:
            m._resolve_device("nope")
        msg = str(ei.value)
        assert "google-pixel-7" in msg
        assert "AAA111" in msg
        assert "samsung-sm-s908u" in msg
        assert "BBB222" in msg


class TestResolveDeviceSessionDefault:
    def test_session_default_used_when_arg_none(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        assert m._resolve_device(None, session_default="BBB222") == "BBB222"

    def test_session_default_can_be_alias(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        assert m._resolve_device(None, session_default="samsung-sm-s908u") == "BBB222"

    def test_session_default_pointing_at_vanished_device_raises(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
        ])
        with pytest.raises(RuntimeError, match="unknown device"):
            m._resolve_device(None, session_default="GHOST")

    def test_explicit_arg_overrides_session_default(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        assert m._resolve_device("AAA111", session_default="BBB222") == "AAA111"


class TestResolveDeviceAutoselect:
    def test_only_one_device_autoselected(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [DeviceInfo("AAA111", "google", "Pixel_7")])
        assert m._resolve_device(None) == "AAA111"

    def test_zero_devices_raises_no_devices_found(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [])
        with pytest.raises(m.MultipleDevicesError, match="no devices found"):
            m._resolve_device(None)

    def test_multiple_devices_raises_multiple_devices_error(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
        ])
        with pytest.raises(m.MultipleDevicesError) as ei:
            m._resolve_device(None)
        msg = str(ei.value)
        assert "multiple devices" in msg.lower()
        assert "google-pixel-7" in msg
        assert "samsung-sm-s908u" in msg
        assert "set_default_device" in msg


# ---------------------------------------------------------------------------
# _build_instructions
# ---------------------------------------------------------------------------

class TestBuildInstructions:
    def test_zero_devices_static_message(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [])
        text = m._build_instructions()
        assert "No devices currently attached" in text
        assert "list_devices" in text

    def test_one_device_mentions_autoroute(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [DeviceInfo("AAA111", "google", "Pixel_7")])
        text = m._build_instructions()
        assert "1 device" in text
        assert "AAA111" in text
        assert "google-pixel-7" in text
        assert "auto-route" in text.lower() or "auto route" in text.lower()

    def test_multiple_devices_lists_each(self, monkeypatch, no_overrides):
        _patch_detect(monkeypatch, [
            DeviceInfo("AAA111", "google", "Pixel_7"),
            DeviceInfo("BBB222", "samsung", "SM_S908U"),
            DeviceInfo("CCC333", "xiaomi", "Redmi_Note_12"),
        ])
        text = m._build_instructions()
        assert "3 devices attached" in text
        for serial in ("AAA111", "BBB222", "CCC333"):
            assert serial in text
        for alias in ("google-pixel-7", "samsung-sm-s908u", "xiaomi-redmi-note-12"):
            assert alias in text
        assert "device=" in text or "`device`" in text
        assert "set_default_device" in text
        assert "list_devices" in text

    def test_detection_failure_degrades_gracefully(self, monkeypatch):
        def boom():
            raise RuntimeError("adb gone")
        monkeypatch.setattr(m, "_detect_devices", boom)
        text = m._build_instructions()
        # Should still return a string mentioning no devices
        assert "No devices currently attached" in text
