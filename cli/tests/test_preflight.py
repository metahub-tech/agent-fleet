"""Tests for the preflight wiring in cmd_setup (_warn_preflight)."""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest

from fleet.cli import _warn_preflight
from fleet.installers.base import BaseInstaller
from fleet.types import OSInfo, InstallContext, VerifyResult


# ---------------------------------------------------------------------------
# Minimal stub installer whose preflight() is configurable
# ---------------------------------------------------------------------------

class _StubInstaller(BaseInstaller):
    role_id = "stub-role"
    display_name = "Stub"
    port = 9999

    def __init__(self, preflight_issues: list[str]):
        self._preflight_issues = preflight_issues

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return True

    def preflight(self) -> list[str]:
        return list(self._preflight_issues)

    def install(self, ctx: InstallContext):
        return iter([])

    def verify(self) -> VerifyResult:
        return VerifyResult(ok=True, tool_count=0)

    def guidance_steps(self):
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_warn_preflight_no_issues_produces_no_output(capsys):
    """When all installers report no missing prereqs, _warn_preflight is silent."""
    roles = [_StubInstaller([])]
    _warn_preflight(roles)
    captured = capsys.readouterr()
    assert captured.out == ""


def test_warn_preflight_with_issues_prints_warning(capsys):
    """When an installer returns missing prerequisites the warning block is printed."""
    roles = [_StubInstaller(["FakeDep", "AnotherDep"])]
    _warn_preflight(roles)
    captured = capsys.readouterr()
    # Should mention the role id and both missing prereqs
    assert "stub-role" in captured.out
    assert "FakeDep" in captured.out
    assert "AnotherDep" in captured.out


def test_warn_preflight_multiple_roles_all_reported(capsys):
    """When multiple roles have missing prereqs, all are listed."""
    class _RoleA(_StubInstaller):
        role_id = "role-a"

    class _RoleB(_StubInstaller):
        role_id = "role-b"

    roles = [_RoleA(["Homebrew"]), _RoleB(["winget"])]
    _warn_preflight(roles)
    captured = capsys.readouterr()
    assert "role-a" in captured.out
    assert "Homebrew" in captured.out
    assert "role-b" in captured.out
    assert "winget" in captured.out


def test_warn_preflight_mixed_roles_only_reports_missing(capsys):
    """Roles with no missing prereqs don't appear in the warning output."""
    class _GoodRole(_StubInstaller):
        role_id = "good-role"

    class _BadRole(_StubInstaller):
        role_id = "bad-role"

    roles = [_GoodRole([]), _BadRole(["MissingThing"])]
    _warn_preflight(roles)
    captured = capsys.readouterr()
    assert "bad-role" in captured.out
    assert "MissingThing" in captured.out
    # good-role had nothing missing, should NOT appear
    assert "good-role" not in captured.out


def test_cmd_setup_calls_preflight_before_install(monkeypatch):
    """Integration: cmd_setup must invoke _warn_preflight on the selected roles
    before calling _run_install, so missing prereqs are surfaced early.

    We test this by patching _warn_preflight and verifying it is called with
    the role list that came out of role-selection.
    """
    import argparse
    from fleet import cli

    # Patch all interactive prompts and side-effectful functions so cmd_setup
    # can run to completion without a TTY.
    captured_preflight_calls = []

    def fake_banner():
        osi = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
        return osi, None  # no Tailscale

    stub = _StubInstaller(["Homebrew"])
    stub.role_id = "mac-device"

    monkeypatch.setattr(cli, "_banner", fake_banner)
    monkeypatch.setattr(cli, "_select_roles", lambda osi: [stub])
    monkeypatch.setattr(cli, "_select_network", lambda ts: "lan")
    monkeypatch.setattr(cli, "build_install_context", lambda **kw: InstallContext(
        repo_root="/tmp/fake", os_info=kw["os_info"], dry_run=True, selected_network="lan",
    ))

    def fake_warn_preflight(roles):
        captured_preflight_calls.append(list(roles))

    monkeypatch.setattr(cli, "_warn_preflight", fake_warn_preflight)
    monkeypatch.setattr(cli, "_run_install", lambda roles, ctx: ([], []))
    monkeypatch.setattr(cli, "_select_frameworks", lambda: [])
    monkeypatch.setattr(cli, "render_install_summary", lambda **kw: "")

    args = argparse.Namespace(dry_run=True)
    result = cli.cmd_setup(args)

    assert result == 0
    # _warn_preflight must have been called exactly once with our stub role
    assert len(captured_preflight_calls) == 1
    assert stub in captured_preflight_calls[0]
