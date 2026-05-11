# cli/tests/test_macos_perm.py
from pathlib import Path
from unittest.mock import patch
from fleet.macos_perm import open_settings_pane, SettingsPane


def test_open_settings_pane_calls_open_with_correct_url():
    with patch("fleet.macos_perm.subprocess.run") as mock_run:
        open_settings_pane(SettingsPane.ACCESSIBILITY)
        mock_run.assert_called_once_with(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )


def test_settings_pane_enum_values():
    assert SettingsPane.ACCESSIBILITY.url_suffix == "Privacy_Accessibility"
    assert SettingsPane.SCREEN_RECORDING.url_suffix == "Privacy_ScreenCapture"
    assert SettingsPane.AUTOMATION.url_suffix == "Privacy_Automation"
    assert SettingsPane.FULL_DISK_ACCESS.url_suffix == "Privacy_AllFiles"


def test_prime_accessibility_calls_venv_python_then_opens_pane():
    from fleet.macos_perm import prime_accessibility
    venv_py = Path("/tmp/venv/bin/python3")
    with patch("fleet.macos_perm.subprocess.run") as mock_run:
        prime_accessibility(venv_py)
        # First call: trigger the TCC dialog by importing ApplicationServices
        first_args = mock_run.call_args_list[0].args[0]
        assert first_args[0] == str(venv_py)
        assert "-c" in first_args
        assert "AXIsProcessTrustedWithOptions" in first_args[-1]
        # Second call: open the pane
        second_args = mock_run.call_args_list[1].args[0]
        assert second_args[0] == "open"
        assert "Privacy_Accessibility" in second_args[1]
