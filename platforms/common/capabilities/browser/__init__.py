"""browser capability modules (agent_browser proxied; human_browser self-built)."""
from ._agent_browser import AgentBrowserCapability
from ._human_browser import HumanBrowserCapability

__all__ = ["AgentBrowserCapability", "HumanBrowserCapability"]
