"""agent-fleet capability-module framework (方案C)."""
from ._base import (
    CORE_ID,
    ORIGIN_PROXIED,
    ORIGIN_SELF_BUILT,
    CapabilityModule,
    CapabilityRegistry,
    current_host_os,
    register_list_capabilities,
    resolve_enabled_capabilities,
)
from ._core import CoreCapability

__all__ = [
    "CORE_ID",
    "ORIGIN_SELF_BUILT",
    "ORIGIN_PROXIED",
    "CapabilityModule",
    "CapabilityRegistry",
    "CoreCapability",
    "current_host_os",
    "register_list_capabilities",
    "resolve_enabled_capabilities",
]
