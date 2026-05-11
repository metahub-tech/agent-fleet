# cli/src/fleet/macos_perm.py
"""macOS TCC permission primer.

Triggers the macOS Privacy & Security permission dialogs programmatically so
Python.app gets registered in the relevant TCC list, then opens System
Settings to the corresponding pane.  After this runs the user can just toggle
the switch — no manual binary drag required.
"""
from __future__ import annotations

import enum
import subprocess


class SettingsPane(enum.Enum):
    """System Settings → Privacy & Security panes addressable via URL scheme.

    The URL suffix corresponds to the anchor in
    x-apple.systempreferences:com.apple.preference.security?<suffix>
    """
    ACCESSIBILITY = "Privacy_Accessibility"
    SCREEN_RECORDING = "Privacy_ScreenCapture"
    AUTOMATION = "Privacy_Automation"
    FULL_DISK_ACCESS = "Privacy_AllFiles"

    @property
    def url_suffix(self) -> str:
        return self.value


def open_settings_pane(pane: SettingsPane) -> None:
    """Open System Settings directly to the given Privacy pane.

    Uses the documented x-apple.systempreferences:// URL scheme.  Best-effort
    (check=False) — if `open` fails the user can still navigate manually.
    """
    url = f"x-apple.systempreferences:com.apple.preference.security?{pane.url_suffix}"
    subprocess.run(["open", url], check=False)
