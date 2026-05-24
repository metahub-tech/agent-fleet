"""Capability-module framework (方案C — 见 docs/internal/design/2026-05-24-capability-module-framework.md).

A device server's tools are organized into capability modules:

  - **core**: always-on. Its tools are defined INLINE in each platform server;
    this framework does NOT relocate them (zero behavior change). CoreCapability
    is metadata-only (register() -> []).
  - **optional modules** (browser, ...): registered at server startup IFF enabled
    in config (platform.toml [capabilities] / .fleet/config.toml), gated by
    host_os and availability(). Registered STATICALLY at connect time — the client
    (Claude Code) defers tool schemas, so token cost is handled client-side
    (spike conclusion, design §1). No session-level dynamic tool lists.

Two implementations of a capability (design §9.1):
  - self-built (origin="self-built"): register() registers hand-written tools.
  - proxied   (origin="proxied"):     register() proxies a mature local MCP
                                       (FastMCP as_proxy) and mounts it.

list_capabilities() is the discovery surface: it buckets the live tool list —
core = every live tool NOT claimed by an optional module.
"""
from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import Optional

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # py3.10
    import tomli as tomllib  # type: ignore

ORIGIN_SELF_BUILT = "self-built"
ORIGIN_PROXIED = "proxied"

CORE_ID = "core"


def current_host_os() -> str:
    """The OS this server process runs on, as a fleet host_os token
    (macos / windows / linux). Used to gate platform-specific capability modules.
    Detected at runtime because some servers (e.g. android) run on multiple OSes."""
    return {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(
        _platform.system(), _platform.system().lower()
    )


class CapabilityModule:
    """One capability = a group of tools + metadata + (optional) a skill.

    Subclass and override register() for optional modules. Core is metadata-only.
    """

    id: str = ""
    display_name: str = ""
    description: str = ""
    origin: str = ORIGIN_SELF_BUILT          # self-built | proxied
    skill: Optional[str] = None
    usage_hint: str = ""
    platforms: Optional[list[str]] = None    # applicable host_os; None = all

    def applies_to(self, host_os: str) -> bool:
        return self.platforms is None or host_os in self.platforms

    def availability(self) -> tuple[bool, str]:
        """(usable, reason). Override to probe deps (e.g. browser binary / GUI
        session). Called once at activation and cached by the registry."""
        return True, ""

    def register(self, mcp) -> list[str]:
        """Register this module's tools onto `mcp`; return the tool names added.
        Core returns [] (its tools are defined inline in the server)."""
        return []


class CapabilityRegistry:
    """Holds capability modules, activates the enabled ones, and produces the
    list_capabilities() discovery payload."""

    def __init__(self, host_os: str):
        self.host_os = host_os
        self._modules: dict[str, CapabilityModule] = {}
        self._module_tools: dict[str, list[str]] = {}       # enabled optional id -> tool names
        self._availability: dict[str, tuple[bool, str]] = {}  # probed id -> (ok, reason)

    def add(self, module: CapabilityModule) -> None:
        self._modules[module.id] = module

    def activate(self, mcp, enabled: list[str]) -> None:
        """Register optional modules whose id is in `enabled`, apply to this
        host_os and pass availability(). Core is always present (metadata-only,
        not registered here — its tools are inline)."""
        enabled_set = set(enabled)
        for mid, mod in self._modules.items():
            if mid == CORE_ID:
                continue
            if mid not in enabled_set or not mod.applies_to(self.host_os):
                continue
            ok, reason = mod.availability()
            self._availability[mid] = (ok, reason)
            if not ok:
                continue
            self._module_tools[mid] = list(mod.register(mcp) or [])

    def setup(self, mcp, enabled: list[str]) -> None:
        """Full integration entry point: activate enabled optional modules, THEN
        register the list_capabilities() discovery tool. Order matters —
        list_capabilities must be registered after activate() so it appears in the
        live tool list and gets bucketed into core. Servers should call this rather
        than activate()/register_list_capabilities() separately."""
        self.activate(mcp, enabled)
        register_list_capabilities(mcp, self)

    async def payload(self, mcp) -> dict:
        """Discovery payload for list_capabilities()."""
        live = [t.name for t in await mcp.list_tools()]
        claimed = {n for names in self._module_tools.values() for n in names}

        caps: list[dict] = []
        core = self._modules.get(CORE_ID)
        if core is not None:
            caps.append(_entry(core, "enabled",
                               sorted(n for n in live if n not in claimed)))

        for mid, mod in self._modules.items():
            if mid == CORE_ID or not mod.applies_to(self.host_os):
                continue
            if mid in self._module_tools:
                caps.append(_entry(mod, "enabled", sorted(self._module_tools[mid])))
            elif mid in self._availability and not self._availability[mid][0]:
                caps.append(_entry(mod, "unavailable", [],
                                   self._availability[mid][1] or "dependency missing"))
            else:
                caps.append(_entry(mod, "disabled", []))
        return {"capabilities": caps}


def _entry(mod: CapabilityModule, status: str, tools: list[str], reason: str = "") -> dict:
    e = {
        "id": mod.id,
        "display_name": mod.display_name,
        "origin": mod.origin,
        "status": status,           # enabled | disabled | unavailable
        "tools": tools,
        "skill": mod.skill,
        "usage_hint": mod.usage_hint,
    }
    if reason:
        e["reason"] = reason
    return e


def register_list_capabilities(mcp, registry: CapabilityRegistry) -> None:
    """Register the list_capabilities() discovery tool onto `mcp`."""

    @mcp.tool
    async def list_capabilities() -> dict:
        """List this device's capability modules (core + optional). Each entry has:
        id, display_name, origin (self-built/proxied), status (enabled/disabled/
        unavailable), the tool names it owns, its skill, and a usage_hint.

        This is the discovery surface — call it to learn what the device can do and
        which tool names to load (via tool search). Tools are already registered;
        there is no separate enable step."""
        return await registry.payload(mcp)


def resolve_enabled_capabilities(
    manifest_capabilities: dict | None,
    repo_root: Path | str | None = None,
) -> list[str]:
    """Resolve which capability ids to enable.

    Precedence (design §3.7 / §8.8):
      <repo_root>/.fleet/config.toml [capabilities].enabled
        > platform.toml [capabilities].enabled
        > default ["core"]
    CORE_ID is always included.
    """
    enabled: list[str] | None = None

    if repo_root is not None:
        fleet_cfg = Path(repo_root) / ".fleet" / "config.toml"
        if fleet_cfg.is_file():
            try:
                with fleet_cfg.open("rb") as f:
                    data = tomllib.load(f)
                override = data.get("capabilities", {}).get("enabled")
                if override is not None:
                    enabled = list(override)
            except Exception:
                enabled = None

    if enabled is None:
        override = (manifest_capabilities or {}).get("enabled")
        enabled = list(override) if override is not None else [CORE_ID]

    if CORE_ID not in enabled:
        enabled = [CORE_ID, *enabled]
    return enabled
