"""agent_browser — proxied capability grafting Playwright MCP (design §9.3).

Drives a REAL Chrome (headed, `--browser chrome`), isolated profile, never
headless / never attach. The Playwright MCP runs as an stdio subprocess that this
module proxies + mounts onto the device server; its browser_* tools (snapshot+ref
DOM model) are re-exposed under their own names. Has automation traces (CDP) by
design — for testing / browsing-to-learn. For acting as the human (real accounts),
use human_browser (Phase 2b, self-built, OS input, zero traces).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .._base import ProxiedCapability

# Playwright MCP tool surface — mirrors @playwright/mcp (verified on macmini
# 2026-05-25: 23 tools via create_proxy). Used for list_capabilities display; the
# live tools come from the mount, so functionality is unaffected if this drifts.
PLAYWRIGHT_TOOLS = [
    "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_click",
    "browser_type", "browser_fill_form", "browser_press_key", "browser_hover",
    "browser_drag", "browser_drop", "browser_select_option", "browser_file_upload",
    "browser_take_screenshot", "browser_evaluate", "browser_run_code_unsafe",
    "browser_console_messages", "browser_network_requests", "browser_network_request",
    "browser_handle_dialog", "browser_wait_for", "browser_tabs", "browser_resize",
    "browser_close",
]

# Dirs where node/npx commonly live — prepended to PATH so launchd / Task-Scheduler
# server environments (which often have a minimal PATH) can still find npx.
if os.name == "nt":
    _NODE_PATH_DIRS = [r"C:\Program Files\nodejs", os.path.expandvars(r"%APPDATA%\npm")]
else:
    _NODE_PATH_DIRS = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin"]


def _augmented_path() -> str:
    return os.pathsep.join(_NODE_PATH_DIRS) + os.pathsep + os.environ.get("PATH", "")


def _augmented_env() -> dict[str, str]:
    return {**os.environ, "PATH": _augmented_path()}


class AgentBrowserCapability(ProxiedCapability):
    id = "agent_browser"
    display_name = "浏览器 agent_browser(有自动化痕迹)"
    skill = "using-fleet-browser"
    platforms = None  # OS-agnostic — Playwright runs on win/mac/linux
    usage_hint = (
        "端到端测试 / 浏览学习用:browser_navigate 开页 → browser_snapshot 取 a11y 树+ref "
        "→ browser_click(ref=...) / browser_type 操作。有自动化痕迹(CDP);需作为人本人操作"
        "真实账号时改用 human_browser。"
    )

    def __init__(self, profile_dir: str | None = None, browser: str = "chrome"):
        self.description = (
            "代理型(嫁接 Playwright MCP):驱动真实 Chrome(headed)做浏览器自动化——"
            "DOM/snapshot+ref 语义操作、抽取页面文本、端到端测试。永不 headless/不 attach,隔离 profile。"
        )
        self._browser = browser
        self._profile = profile_dir or str(Path.home() / ".fleet" / "agent-browser-profile")

    def availability(self) -> tuple[bool, str]:
        if shutil.which("npx", path=_augmented_path()) is None:
            return False, "node/npx 未找到(需装 node + @playwright/mcp;见 using-fleet-browser skill)"
        return True, ""

    def make_transport(self):
        from fastmcp.client.transports import StdioTransport

        Path(self._profile).mkdir(parents=True, exist_ok=True)
        return StdioTransport(
            command="npx",
            args=["-y", "@playwright/mcp@latest", "--browser", self._browser,
                  "--user-data-dir", self._profile],
            env=_augmented_env(),
            keep_alive=True,  # shared singleton subprocess for the server's lifetime
        )

    def proxied_tools(self) -> list[str]:
        return list(PLAYWRIGHT_TOOLS)
