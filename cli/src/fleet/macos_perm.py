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
from pathlib import Path


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


def prime_accessibility(venv_python: Path) -> None:
    """Trigger Accessibility permission registration for Python.app.

    Calls AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    via the macOS server's venv python (which has pyobjc installed).  This
    pops the system dialog AND registers Python.app in the Accessibility list
    even if denied.  Then opens the Accessibility pane so user can toggle.
    """
    snippet = (
        "from ApplicationServices import "
        "AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt; "
        "AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})"
    )
    subprocess.run([str(venv_python), "-c", snippet], check=False)
    open_settings_pane(SettingsPane.ACCESSIBILITY)


def prime_screen_recording(venv_python: Path) -> None:
    """Trigger Screen Recording permission registration.

    Quartz.CGRequestScreenCaptureAccess() — macOS 11+ API that pops the
    system dialog and registers Python.app in the Screen Recording list.
    """
    snippet = "import Quartz; Quartz.CGRequestScreenCaptureAccess()"
    subprocess.run([str(venv_python), "-c", snippet], check=False)
    open_settings_pane(SettingsPane.SCREEN_RECORDING)


def prime_automation() -> None:
    """Trigger Automation/AppleScript permission registration.

    First-time use of `tell application "System Events"` triggers the
    Automation prompt for the calling app (Terminal, in this context — the
    parent of the wizard process).  This is different from the others: it
    grants Terminal the right to control System Events, which transitively
    lets python subprocesses spawned from Terminal control GUI apps.
    """
    script = 'tell application "System Events" to count of processes'
    subprocess.run(["osascript", "-e", script], check=False)
    open_settings_pane(SettingsPane.AUTOMATION)
