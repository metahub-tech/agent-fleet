# cli/tests/test_macos_perm.py
from unittest.mock import patch
from fleet.macos_perm import open_settings_pane, SettingsPane


def test_open_settings_pane_calls_open_with_correct_url():
    with patch("subprocess.run") as mock_run:
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
