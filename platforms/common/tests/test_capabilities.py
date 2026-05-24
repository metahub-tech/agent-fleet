"""Tests for the capability-module framework (capabilities/).

Dependency-free: a FakeMcp stands in for FastMCP (records @tool registrations,
exposes async list_tools()), so the bucketing logic runs without fastmcp/GUI libs.
The real-FastMCP integration is validated separately on a live server."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capabilities import (  # noqa: E402
    ORIGIN_PROXIED,
    CapabilityModule,
    CapabilityRegistry,
    CoreCapability,
    resolve_enabled_capabilities,
)


# --------------------------------------------------------------------------- #
# FakeMcp — minimal stand-in for FastMCP
# --------------------------------------------------------------------------- #
class _FakeTool:
    def __init__(self, name):
        self.name = name


class FakeMcp:
    def __init__(self):
        self.names: list[str] = []

    def tool(self, fn=None, **kwargs):
        def _reg(f):
            self.names.append(f.__name__)
            return f
        return _reg(fn) if callable(fn) else _reg

    async def list_tools(self):
        return [_FakeTool(n) for n in self.names]


# --------------------------------------------------------------------------- #
# resolve_enabled_capabilities
# --------------------------------------------------------------------------- #
def test_resolve_default_is_core_only():
    assert resolve_enabled_capabilities(None) == ["core"]
    assert resolve_enabled_capabilities({}) == ["core"]


def test_resolve_forces_core_in():
    assert resolve_enabled_capabilities({"enabled": ["browser"]}) == ["core", "browser"]


def test_resolve_keeps_manifest_list():
    assert resolve_enabled_capabilities({"enabled": ["core", "browser"]}) == ["core", "browser"]


def test_resolve_fleet_override_wins(tmp_path):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "config.toml").write_text(
        '[capabilities]\nenabled = ["core", "agent_browser"]\n'
    )
    # manifest says browser, but .fleet override wins
    assert resolve_enabled_capabilities({"enabled": ["browser"]}, tmp_path) == [
        "core",
        "agent_browser",
    ]


def test_resolve_no_fleet_file_falls_back_to_manifest(tmp_path):
    assert resolve_enabled_capabilities({"enabled": ["x"]}, tmp_path) == ["core", "x"]


# --------------------------------------------------------------------------- #
# bucketing + status
# --------------------------------------------------------------------------- #
class _Browser(CapabilityModule):
    id = "browser"
    display_name = "browser"
    origin = ORIGIN_PROXIED
    skill = "using-fleet-browser"
    usage_hint = "navigate then snapshot"

    def register(self, mcp):
        @mcp.tool
        def browser_navigate(url: str) -> str:
            "nav"
            return url
        return ["browser_navigate"]


class _Unavailable(CapabilityModule):
    id = "media"
    display_name = "media"

    def availability(self):
        return False, "ffmpeg not installed"


class _Disabled(CapabilityModule):
    id = "deep_a11y"
    display_name = "deep a11y"


class _WinOnly(CapabilityModule):
    id = "win_only"
    display_name = "win only"
    platforms = ["windows"]


def _build_macos_registry():
    mcp = FakeMcp()

    @mcp.tool
    def tap(x: int, y: int) -> str:
        "core tap"
        return "ok"

    @mcp.tool
    def type_text(text: str) -> str:
        "core type"
        return "ok"

    reg = CapabilityRegistry(host_os="macos")
    reg.add(CoreCapability(skill="using-mac"))
    reg.add(_Browser())
    reg.add(_Unavailable())
    reg.add(_Disabled())
    reg.add(_WinOnly())
    # deep_a11y intentionally left out of `enabled` -> disabled.
    # setup() = activate + register_list_capabilities in the correct order.
    reg.setup(mcp, ["core", "browser", "media", "win_only"])
    return mcp, reg


def _payload():
    mcp, reg = _build_macos_registry()
    p = asyncio.run(reg.payload(mcp))
    return {c["id"]: c for c in p["capabilities"]}


def test_core_owns_unclaimed_tools():
    caps = _payload()
    core_tools = set(caps["core"]["tools"])
    assert {"tap", "type_text", "list_capabilities"} <= core_tools
    assert "browser_navigate" not in core_tools  # optional tool not leaked to core
    assert caps["core"]["origin"] == "self-built"
    assert caps["core"]["status"] == "enabled"


def test_enabled_optional_module():
    caps = _payload()
    assert caps["browser"]["status"] == "enabled"
    assert caps["browser"]["tools"] == ["browser_navigate"]
    assert caps["browser"]["origin"] == "proxied"
    assert caps["browser"]["skill"] == "using-fleet-browser"


def test_unavailable_module_reports_reason():
    caps = _payload()
    assert caps["media"]["status"] == "unavailable"
    assert caps["media"]["reason"] == "ffmpeg not installed"
    assert caps["media"]["tools"] == []


def test_disabled_module():
    caps = _payload()
    assert caps["deep_a11y"]["status"] == "disabled"
    assert caps["deep_a11y"]["tools"] == []


def test_platform_gating_omits_other_os():
    caps = _payload()
    assert "win_only" not in caps  # windows-only module omitted on a macos host
