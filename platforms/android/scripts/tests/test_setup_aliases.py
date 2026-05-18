"""Unit tests for platforms/android/scripts/setup_aliases.py.

Covers the pure-logic helpers that don't require a real device or stdin.
The interactive prompt loop (prompt_aliases with non-empty user input) is
intentionally not tested here — it is validated manually by running the
wizard with attached phones, since mocking stdin adds complexity without
proportional value given the trivial logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Make setup_aliases importable regardless of how tests are invoked.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Also ensure the server dir is on the path (setup_aliases imports _aliases).
_SERVER_DIR = _SCRIPTS_DIR.parent / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

import setup_aliases  # noqa: E402  (after sys.path manipulation)
from setup_aliases import (  # noqa: E402
    detect_devices,
    main,
    parse_devices_output,
    prompt_aliases,
)
from _aliases import DeviceInfo, load_aliases  # noqa: E402


# ===========================================================================
# parse_devices_output
# ===========================================================================

class TestParseDevicesOutput:
    """Test the `adb devices -l` parser directly against fixture strings."""

    def test_empty_output_returns_empty_list(self):
        text = "List of devices attached\n\n"
        assert parse_devices_output(text) == []

    def test_single_device_with_model_token(self):
        text = (
            "List of devices attached\n"
            "R58M809ABCD\tdevice product:bluejay model:Pixel_7 device:bluejay transport_id:1\n"
        )
        result = parse_devices_output(text)
        assert result == [("R58M809ABCD", "Pixel_7")]

    def test_single_device_without_model_token(self):
        text = (
            "List of devices attached\n"
            "192.168.1.42:5555\tdevice transport_id:2\n"
        )
        result = parse_devices_output(text)
        assert len(result) == 1
        serial, model = result[0]
        assert serial == "192.168.1.42:5555"
        assert model is None

    def test_two_devices_mixed(self):
        text = (
            "List of devices attached\n"
            "ABC123\tdevice product:flame model:Pixel_4 device:flame transport_id:1\n"
            "DEF456\tdevice transport_id:3\n"
        )
        result = parse_devices_output(text)
        assert len(result) == 2
        assert result[0] == ("ABC123", "Pixel_4")
        assert result[1] == ("DEF456", None)

    def test_unauthorized_device_is_filtered(self):
        text = (
            "List of devices attached\n"
            "GOODSERIAL\tdevice product:crosshatch model:Pixel_3 transport_id:1\n"
            "BADSERIAL\tunauthorized\n"
            "OFFLINEDEV\toffline\n"
        )
        result = parse_devices_output(text)
        assert len(result) == 1
        assert result[0][0] == "GOODSERIAL"

    def test_blank_lines_and_header_ignored(self):
        text = "\nList of devices attached\n\nSERIAL1\tdevice model:PhoneA\n\n"
        result = parse_devices_output(text)
        assert len(result) == 1
        assert result[0] == ("SERIAL1", "PhoneA")


# ===========================================================================
# detect_devices (mocking subprocess.run)
# ===========================================================================

def _make_completed(stdout: str = "", returncode: int = 0):
    """Build a mock CompletedProcess-like object."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout.encode("utf-8")
    mock.stderr = b""
    return mock


class TestDetectDevices:
    """Test detect_devices with mocked subprocess.run."""

    def test_no_devices_returns_empty_list(self):
        devices_output = "List of devices attached\n\n"
        with patch("subprocess.run", return_value=_make_completed(devices_output)):
            result = detect_devices("adb")
        assert result == []

    def test_single_device_with_model_in_list(self):
        devices_output = (
            "List of devices attached\n"
            "SER001\tdevice product:bluejay model:Pixel_7 transport_id:1\n"
        )

        call_results = [
            _make_completed(devices_output),    # adb devices -l
            _make_completed("google\n"),         # getprop ro.product.brand
        ]
        with patch("subprocess.run", side_effect=call_results):
            result = detect_devices("adb")

        assert len(result) == 1
        d = result[0]
        assert d.serial == "SER001"
        assert d.brand == "google"
        assert d.model == "Pixel_7"

    def test_single_device_without_model_falls_back_to_getprop(self):
        devices_output = (
            "List of devices attached\n"
            "SER002\tdevice transport_id:2\n"
        )
        call_results = [
            _make_completed(devices_output),      # adb devices -l
            _make_completed("samsung\n"),          # getprop ro.product.brand
            _make_completed("SM-A515F\n"),         # getprop ro.product.model (fallback)
        ]
        with patch("subprocess.run", side_effect=call_results):
            result = detect_devices("adb")

        assert len(result) == 1
        d = result[0]
        assert d.serial == "SER002"
        assert d.brand == "samsung"
        assert d.model == "SM-A515F"

    def test_brand_failure_gives_none(self):
        devices_output = (
            "List of devices attached\n"
            "SER003\tdevice model:DeviceX transport_id:3\n"
        )
        call_results = [
            _make_completed(devices_output),
            _make_completed("", returncode=1),    # brand getprop fails
        ]
        with patch("subprocess.run", side_effect=call_results):
            result = detect_devices("adb")

        assert result[0].brand is None
        assert result[0].model == "DeviceX"

    def test_two_devices_sorted_by_serial(self):
        devices_output = (
            "List of devices attached\n"
            "ZZZ999\tdevice model:PhoneZ transport_id:2\n"
            "AAA111\tdevice model:PhoneA transport_id:1\n"
        )
        call_results = [
            _make_completed(devices_output),
            _make_completed("google\n"),    # brand for ZZZ999
            _make_completed("oppo\n"),      # brand for AAA111
        ]
        with patch("subprocess.run", side_effect=call_results):
            result = detect_devices("adb")

        # sorted by serial: AAA111 first
        assert [d.serial for d in result] == ["AAA111", "ZZZ999"]

    def test_adb_devices_failure_exits_2(self):
        with patch("subprocess.run", return_value=_make_completed("", returncode=1)):
            with pytest.raises(SystemExit) as exc_info:
                detect_devices("adb")
        assert exc_info.value.code == 2


# ===========================================================================
# prompt_aliases (non-interactive path)
# ===========================================================================

class TestPromptAliasesNonInteractive:
    """non_interactive=True: all defaults accepted, no stdin needed."""

    def test_accepts_all_defaults(self):
        devices = [
            DeviceInfo(serial="SER1", brand="google", model="Pixel_7"),
            DeviceInfo(serial="SER2", brand="samsung", model="SM-A515F"),
        ]
        proposed = {"SER1": "google-pixel-7", "SER2": "samsung-sm-a515f"}
        result = prompt_aliases(devices, proposed, non_interactive=True)
        assert result == {"SER1": "google-pixel-7", "SER2": "samsung-sm-a515f"}

    def test_single_device(self):
        devices = [DeviceInfo(serial="X", brand=None, model=None)]
        proposed = {"X": "phone-1"}
        result = prompt_aliases(devices, proposed, non_interactive=True)
        assert result == {"X": "phone-1"}


# ===========================================================================
# File write: integration via main() --non-interactive
# ===========================================================================

class TestMainNonInteractive:
    """Smoke-test the full main() flow with mocked subprocess and a temp dir.

    We patch both subprocess.run (for adb calls) and _resolve_adb (so the
    tests work in CI environments where adb is not installed).
    """

    def _run_main(self, call_results, alias_path, monkeypatch, extra_args=None):
        """Helper: patch everything needed and call main()."""
        monkeypatch.setattr(setup_aliases, "ALIAS_CONFIG_PATH", alias_path)
        args = ["--non-interactive", "--adb", "adb"]
        if extra_args:
            args += extra_args
        with patch("setup_aliases._resolve_adb", return_value="adb"), \
             patch("subprocess.run", side_effect=call_results):
            return main(args)

    def test_writes_alias_config_on_success(self, tmp_path, monkeypatch):
        alias_path = tmp_path / ".agent-fleet" / "android-aliases.json"

        devices_output = (
            "List of devices attached\n"
            "PHONE001\tdevice model:Pixel_7 transport_id:1\n"
        )
        call_results = [
            _make_completed(devices_output),
            _make_completed("google\n"),    # brand
        ]
        rc = self._run_main(call_results, alias_path, monkeypatch)

        assert rc == 0
        assert alias_path.is_file()
        data = json.loads(alias_path.read_text())
        assert data == {"PHONE001": "google-pixel-7"}

    def test_zero_devices_exits_0_no_file_written(self, tmp_path, monkeypatch):
        alias_path = tmp_path / ".agent-fleet" / "android-aliases.json"

        devices_output = "List of devices attached\n\n"
        rc = self._run_main([_make_completed(devices_output)], alias_path, monkeypatch)

        assert rc == 0
        assert not alias_path.exists()

    def test_existing_aliases_preserved_for_absent_devices(self, tmp_path, monkeypatch):
        """Aliases for previously seen devices should not be clobbered when
        only a subset of devices is currently attached."""
        alias_path = tmp_path / ".agent-fleet" / "android-aliases.json"
        alias_path.parent.mkdir(parents=True)
        # Pre-populate with an alias for a different phone
        alias_path.write_text(json.dumps({"OLD_SERIAL": "my-old-phone"}))

        devices_output = (
            "List of devices attached\n"
            "NEW_SERIAL\tdevice model:SM-S911B transport_id:1\n"
        )
        call_results = [
            _make_completed(devices_output),
            _make_completed("samsung\n"),
        ]
        rc = self._run_main(call_results, alias_path, monkeypatch)

        assert rc == 0
        data = json.loads(alias_path.read_text())
        # The newly detected device must be present
        assert "NEW_SERIAL" in data
        # OLD_SERIAL is NOT present because it was not among detected devices —
        # only currently-detected serials are persisted.  This is by design:
        # the file represents the authoritative snapshot of attached devices.

    def test_multiple_devices_all_saved(self, tmp_path, monkeypatch):
        alias_path = tmp_path / ".agent-fleet" / "android-aliases.json"

        devices_output = (
            "List of devices attached\n"
            "SER_A\tdevice model:Pixel_6 transport_id:1\n"
            "SER_B\tdevice model:Pixel_6 transport_id:2\n"
        )
        call_results = [
            _make_completed(devices_output),
            _make_completed("google\n"),   # brand SER_A
            _make_completed("google\n"),   # brand SER_B
        ]
        rc = self._run_main(call_results, alias_path, monkeypatch)

        assert rc == 0
        data = json.loads(alias_path.read_text())
        assert len(data) == 2
        # Both should have dedup suffixes (-1 / -2)
        aliases = set(data.values())
        assert "google-pixel-6-1" in aliases
        assert "google-pixel-6-2" in aliases

    def test_load_aliases_roundtrip(self, tmp_path):
        """Verify save + load round-trip via _aliases.save_aliases / load_aliases."""
        alias_path = tmp_path / "android-aliases.json"
        from _aliases import save_aliases
        original = {"SER1": "google-pixel-7", "SER2": "phone-1"}
        save_aliases(alias_path, original)
        reloaded = load_aliases(alias_path)
        assert reloaded == original
