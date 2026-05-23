"""Per-role preflight / smoke_tests hooks for ManifestInstaller.

Each entry maps a ``role_id`` → ``{"preflight_hook": ..., "smoke_hook": ...}``.
The callables reproduce the EXACT behaviour of the six hand-written installer
classes they replace.  No logic is invented here — only moved/imported.

preflight_hook signature: ``(host_os: str) -> list[str]``
    Receives the host OS so android's brew check is only active on macOS.
smoke_hook signature:     ``() -> list[SmokeTest]``
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..smoke import SmokeTest


# ---------------------------------------------------------------------------
# Shared helpers (reproduced verbatim from the original installer files so
# _hooks.py is self-contained and Task 3 can delete the old classes cleanly)
# ---------------------------------------------------------------------------

def _which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def _brew_missing_message() -> str:
    return (
        "Homebrew (brew). Install: "
        '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    )


# ---------------------------------------------------------------------------
# mac-device preflight (from MacosDesktop.preflight)
# ---------------------------------------------------------------------------

def _mac_device_preflight(host_os: str) -> list[str]:
    """Reproduce MacosDesktop.preflight() — host_os not needed (always macOS)."""
    missing: list[str] = []
    if not _which("brew"):
        missing.append(_brew_missing_message())
    return missing


# ---------------------------------------------------------------------------
# ios-device preflight (from MacosIosBridge.preflight)
# ---------------------------------------------------------------------------

def _ios_device_preflight(host_os: str) -> list[str]:
    """Reproduce MacosIosBridge.preflight() — host_os not needed (always macOS)."""
    import subprocess as _sp

    m: list[str] = []
    if not _which("brew"):
        m.append(_brew_missing_message())

    # Must have brew python@3.12; system Python 3.9.6 can't run fastmcp
    py312_ok = False
    for cand in [
        "/opt/homebrew/opt/python@3.12/bin/python3.12",
        "/usr/local/opt/python@3.12/bin/python3.12",
        "/opt/homebrew/bin/python3.12",
        "/usr/local/bin/python3.12",
    ]:
        if Path(cand).is_file():
            py312_ok = True
            break
    if not py312_ok:
        m.append("python@3.12 via Homebrew. Run: brew install python@3.12")

    # Warn if Xcode CLT only (no full Xcode) — WDA needs full Xcode
    try:
        r = _sp.run(["xcode-select", "-p"], capture_output=True, text=True, timeout=5)
        xcode_path = r.stdout.strip()
        if r.returncode != 0 or not xcode_path:
            m.append(
                "Xcode (full Xcode.app required to build WDA, not just Command Line Tools). "
                "Install from the Mac App Store or developer.apple.com."
            )
        elif "CommandLineTools" in xcode_path:
            m.append(
                "WARNING: xcode-select points to CLT only. WDA requires full Xcode.app. "
                "Install Xcode.app and run: sudo xcode-select -s /Applications/Xcode.app"
            )
    except Exception:
        pass

    return m


# ---------------------------------------------------------------------------
# android-device preflight
# (from MacosAndroidBridge.preflight — brew check on macOS only)
# ---------------------------------------------------------------------------

def _android_device_preflight(host_os: str) -> list[str]:
    """Reproduce MacosAndroidBridge.preflight() for macOS; [] for win/linux."""
    if host_os == "macos":
        m: list[str] = []
        if not _which("brew"):
            m.append("Homebrew (brew)")
        return m
    # WindowsAndroidBridge.preflight() and LinuxAndroidBridge.preflight() both
    # return [] — no checks needed.
    return []


# ---------------------------------------------------------------------------
# win-device preflight (from WindowsDesktop.preflight)
# ---------------------------------------------------------------------------

def _win_device_preflight(host_os: str) -> list[str]:
    """Reproduce WindowsDesktop.preflight() — always []."""
    return []  # winget bundled on Win 10/11; powershell.exe always present


# ---------------------------------------------------------------------------
# Smoke hooks (delegate to the existing shared helpers)
# ---------------------------------------------------------------------------

def _mac_device_smoke() -> "list[SmokeTest]":
    """Reproduce MacosDesktop.smoke_tests()."""
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_status", {},
            description="server reachable"),
        SmokeTest("run_shell", {"script": "echo ok"},
            description="shell exec",
            hint_on_failure=(
                "setup-macos.sh probably exited without starting the launchd plist; "
                "check ~/Library/LaunchAgents/cc.metahub.mac-device.plist + logs/"
            )),
        SmokeTest("get_screen_size", {},
            description="GUI baseline (pyautogui)",
            hint_on_failure=(
                "pyautogui import failed; "
                "venv missing pyobjc-framework-Quartz or similar"
            )),
        SmokeTest("take_screenshot", {},
            description="Screen Recording TCC",
            timeout=12,
            hint_on_failure=(
                "System Settings → Privacy & Security → Screen Recording → "
                "enable BOTH 'Python' and 'python3.12'; "
                "then `launchctl unload + load ~/Library/LaunchAgents/cc.metahub.mac-device.plist`"
            )),
        SmokeTest("run_applescript", {"script": 'return "ok"'},
            description="Automation TCC",
            hint_on_failure=(
                "System Settings → Privacy & Security → Automation → "
                "expand Terminal → check System Events"
            )),
    ]


def _ios_device_smoke() -> "list[SmokeTest]":
    """Delegate to the shared helper in _ios.py (MacosIosBridge.smoke_tests)."""
    from ._ios import _ios_bridge_smoke_tests
    return _ios_bridge_smoke_tests()


def _android_device_smoke() -> "list[SmokeTest]":
    """Delegate to the shared helper in _android.py (all three host installers)."""
    from ._android import _android_bridge_smoke_tests
    return _android_bridge_smoke_tests()


def _win_device_smoke() -> "list[SmokeTest]":
    """Reproduce WindowsDesktop.smoke_tests()."""
    from ..smoke import SmokeTest
    return [
        SmokeTest("get_status", {},
            description="server reachable"),
        SmokeTest("run_shell", {"script": "Write-Output ok"},
            description="shell exec",
            hint_on_failure=(
                "setup-windows.ps1 probably exited without registering the "
                "scheduled task; check Get-ScheduledTask MCP-WinDevice"
            )),
        SmokeTest("get_screen_size", {},
            description="GUI baseline (pywinauto)"),
        SmokeTest("take_screenshot", {},
            description="screen capture",
            timeout=10,
            hint_on_failure=(
                "If the user session is locked, take_screenshot returns the "
                "lock-screen image. Unlock the session or configure autologon "
                "for headless deployments."
            )),
        SmokeTest("list_windows", {},
            description="window enumeration"),
    ]


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

ROLE_HOOKS: dict[str, dict] = {
    "mac-device": {
        "preflight_hook": _mac_device_preflight,
        "smoke_hook": _mac_device_smoke,
    },
    "ios-device": {
        "preflight_hook": _ios_device_preflight,
        "smoke_hook": _ios_device_smoke,
    },
    "android-device": {
        "preflight_hook": _android_device_preflight,
        "smoke_hook": _android_device_smoke,
    },
    "win-device": {
        "preflight_hook": _win_device_preflight,
        "smoke_hook": _win_device_smoke,
    },
}
