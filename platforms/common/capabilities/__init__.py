"""agent-fleet capability-module framework (方案C)."""
from ._base import (
    CORE_ID,
    ORIGIN_PROXIED,
    ORIGIN_SELF_BUILT,
    CapabilityModule,
    CapabilityRegistry,
    ProxiedCapability,
    current_host_os,
    register_list_capabilities,
    resolve_enabled_capabilities,
)
from ._core import CoreCapability
from .browser import AgentBrowserCapability, HumanBrowserCapability
from .vision import VisionCapability
from .human_dom._human_dom import HumanDomCapability

__all__ = [
    "CORE_ID",
    "ORIGIN_SELF_BUILT",
    "ORIGIN_PROXIED",
    "CapabilityModule",
    "CapabilityRegistry",
    "ProxiedCapability",
    "CoreCapability",
    "AgentBrowserCapability",
    "HumanBrowserCapability",
    "VisionCapability",
    "HumanDomCapability",
    "current_host_os",
    "register_list_capabilities",
    "resolve_enabled_capabilities",
]
