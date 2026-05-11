"""Per-agent-framework MCP config generators."""
from .base import BaseFrameworkConfig, ServerRoleEntry
from .claude_code import ClaudeCodeConfig
from .cursor import CursorConfig
from .cline import ClineConfig
from .openclaw import OpenClawConfig
from .antigravity import AntigravityConfig
from .hermes import HermesConfig

# Instantiated registry — wizard iterates this for the multi-select prompt.
FRAMEWORK_REGISTRY: list[BaseFrameworkConfig] = [
    ClaudeCodeConfig(),
    CursorConfig(),
    ClineConfig(),
    OpenClawConfig(),
    AntigravityConfig(),
    HermesConfig(),
]

__all__ = [
    "BaseFrameworkConfig", "ServerRoleEntry", "FRAMEWORK_REGISTRY",
    "ClaudeCodeConfig", "CursorConfig", "ClineConfig",
    "OpenClawConfig", "AntigravityConfig", "HermesConfig",
]
