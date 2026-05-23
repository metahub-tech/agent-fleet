"""Global regression: legacy role-ID and service-identifier strings must not
appear in active code/config.

Allowlisted areas: CHANGELOG (historical record), docs/internal/ (historical
plans, specs, and design docs), and the package's own .venv / test_env directories.

This test is the safety net for the rename done in v0.6.0-alpha (Tasks 7-16).
It commits to main while still failing — Tasks 10-16 drive it to green.
"""
from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

LEGACY = [
    # role IDs (pre-v0.6.0)
    "macbox-gui", "winpc-gui", "android-gui",
    # service identifiers (pre-v0.6.0)
    "cc.metahub.macbox-gui",
    "MCP-WindowsGui", "MCP-AndroidGui",
    "atb-android-gui",
    # skill dir names (pre-v0.6.0)
    "using-macbox", "using-winpc",
    # Python entry-point + log filenames (pre-v0.6.11)
    "macos_gui_mcp", "windows_gui_mcp",
    "macos-gui.log", "windows-gui.log",
    # GitHub repo rename (project was renamed agent-test-bench → agent-fleet
    # on GitHub; internal refs cleaned up in v0.6.12-alpha)
    "agent-test-bench",
]

# Path-prefix substrings we don't scan (historical, generated, or external).
ALLOW_PATH_PREFIXES = (
    "CHANGELOG.md",
    "docs/internal/",
    "cli/.venv/",
    "cli/test_env/",
    ".git/",
    "__pycache__",
    "uv.lock",
    # this test file contains the legacy strings as data — exclude self
    "cli/tests/test_no_legacy_naming.py",
)

SCAN_EXTS = {".py", ".sh", ".ps1", ".yaml", ".yml", ".toml", ".json", ".md"}


def _is_allowlisted(rel: pathlib.Path) -> bool:
    s = str(rel)
    return any(s.startswith(p) or p in s for p in ALLOW_PATH_PREFIXES)


def test_no_legacy_naming_strings_in_active_code():
    failures: list[tuple[str, str, int]] = []  # (path, legacy_str, line_no)
    for f in REPO_ROOT.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in SCAN_EXTS:
            continue
        rel = f.relative_to(REPO_ROOT)
        if _is_allowlisted(rel):
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for legacy in LEGACY:
            for i, line in enumerate(text.splitlines(), 1):
                if legacy in line:
                    # Skip lines that are part of an intentional legacy-cleanup
                    # migration block, marked by "legacy" in the comment or
                    # variable name on the same line.
                    if "legacy" in line.lower():
                        continue
                    failures.append((str(rel), legacy, i))

    if failures:
        msg = f"\nLegacy naming strings still present ({len(failures)} hit(s)):\n"
        for path, legacy, ln in failures:
            msg += f"  {path}:{ln}  →  {legacy!r}\n"
        msg += "\nAllowlisted prefixes: " + ", ".join(ALLOW_PATH_PREFIXES)
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Guard: renamed-away CORE tool names must not reappear in active code/docs.
# These were the pre-P3 names superseded by canonical platform-prefixed names.
# Do NOT add: inspect_window, list_ui_elements, kill_process (kept as platform
# extensions); or bare "click" (too noisy in prose/extension contexts).
# ---------------------------------------------------------------------------

LEGACY_TOOL_NAMES = [
    # win-device CORE renames
    "acquire_winpc",
    "release_winpc",
    "get_winpc_status",
    # mac-device CORE renames
    "acquire_mac",
    "release_mac",
    "get_mac_status",
    # android-device CORE renames
    "acquire_android",
    "release_android",
    "get_android_status",
    # ios-device CORE renames
    "acquire_ios",
    "release_ios",
    "get_ios_status",
    # cross-platform CORE renames
    "dump_ui_hierarchy",
    "kill_app",
    "press_button",
    # OPTIONAL renames (P3 OPTIONAL batch) — superseded by canonical names
    "run_powershell",   # win  → run_shell
    "run_zsh",          # mac  → run_shell
    "adb_shell",        # android → run_shell (internal helper renamed _adb_exec)
    "open_app",         # mac  → launch_app
    "start_app",        # android+ios → launch_app
    "install_apk",      # android → install_app
    "install_ipa",      # ios  → install_app
]


def test_no_legacy_tool_names():
    """Ensure renamed-away CORE tool names do not reappear in active code/docs."""
    failures: list[tuple[str, str, int]] = []  # (path, tool_name, line_no)
    for f in REPO_ROOT.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in SCAN_EXTS:
            continue
        rel = f.relative_to(REPO_ROOT)
        if _is_allowlisted(rel):
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for name in LEGACY_TOOL_NAMES:
            for i, line in enumerate(text.splitlines(), 1):
                if name in line:
                    failures.append((str(rel), name, i))

    if failures:
        msg = f"\nLegacy CORE tool names still present ({len(failures)} hit(s)):\n"
        for path, name, ln in failures:
            msg += f"  {path}:{ln}  →  {name!r}\n"
        msg += "\nAllowlisted prefixes: " + ", ".join(ALLOW_PATH_PREFIXES)
        raise AssertionError(msg)
