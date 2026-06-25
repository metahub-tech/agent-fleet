"""agent_browser — method A: multi-profile, real-parallel (design §6 / browser-profile-lease).

Each profile gets its OWN @playwright/mcp stdio client (one Chrome user-data-dir).
We DON'T mcp.mount a single backend; instead, at startup we introspect the
@playwright/mcp tool schemas once and generate, for EACH tool, a dynamic wrapper
whose signature is (profile, holder, *original params) and register it via
mcp.add_tool. A call routes to the per-profile client via the shared
BrowserLeaseRegistry (bind/auto-bind, idle reuse, cross-engine exclusion).

Concurrency model (learned the hard way, design §6): the clients live on the
SERVER'S OWN main event loop — NEVER a background-thread loop (Windows asyncio
subprocess deadlocks in a child-thread ProactorEventLoop). The sync registry and
the async clients are bridged by: start_fn builds a session object (no connect;
connect is lazy on first call inside an async handler), and close_fn schedules
session.aclose() with asyncio.ensure_future (fire-and-forget, non-blocking).

origin stays "proxied" (we still graft @playwright/mcp); it's just no longer a
single mounted proxy.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import shutil
from pathlib import Path
from typing import Optional

from .._base import CapabilityModule, ORIGIN_PROXIED

# _browser_lease lives at common/ top level (not inside the capabilities package);
# the server/tests put common on sys.path, so import it absolutely.
from _browser_lease import ENGINE_AGENT, shared_registry, _resolve_profile, _isolated_dir  # noqa: E402

# Advertised surface for list_capabilities (live tools come from the dynamic
# wrappers; this is a fallback list if introspection can't run).
PLAYWRIGHT_TOOLS = [
    "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_click",
    "browser_type", "browser_fill_form", "browser_press_key", "browser_hover",
    "browser_drag", "browser_drop", "browser_select_option", "browser_file_upload",
    "browser_take_screenshot", "browser_evaluate", "browser_run_code_unsafe",
    "browser_console_messages", "browser_network_requests", "browser_network_request",
    "browser_handle_dialog", "browser_wait_for", "browser_tabs", "browser_resize",
    "browser_close",
]
_MGMT_TOOLS = ["browser_bind", "browser_release", "browser_quit", "browser_status"]

if os.name == "nt":
    _NODE_PATH_DIRS = [r"C:\Program Files\nodejs", os.path.expandvars(r"%APPDATA%\npm")]
else:
    _NODE_PATH_DIRS = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin"]

_TYPE = {"string": str, "number": float, "integer": int, "boolean": bool,
         "object": dict, "array": list}


def _augmented_path() -> str:
    return os.pathsep.join(_NODE_PATH_DIRS) + os.pathsep + os.environ.get("PATH", "")


def _augmented_env() -> dict:
    return {**os.environ, "PATH": _augmented_path()}


class AgentBrowserSession:
    """One @playwright/mcp client bound to one profile. Lazily connects on the
    server's main event loop (inside an async handler) — never a bg thread."""

    def __init__(self, udd: str, profile_dir: Optional[str]):
        self._udd = udd
        self._pdir = profile_dir
        self._client = None
        self._lock = asyncio.Lock()

    async def _ensure(self):
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    from fastmcp import Client
                    from fastmcp.client.transports import StdioTransport
                    args = ["-y", "@playwright/mcp@latest", "--browser", "chrome",
                            "--user-data-dir", self._udd]
                    if self._pdir:
                        args += ["--profile-directory", self._pdir]
                    c = Client(StdioTransport(command="npx", args=args, env=_augmented_env()))
                    await c.__aenter__()
                    self._client = c
        return self._client

    async def call(self, name: str, args: dict):
        client = await self._ensure()
        return await client.call_tool(name, args)

    async def aclose(self):
        c, self._client = self._client, None
        if c is not None:
            try:
                await c.__aexit__(None, None, None)
            except Exception:
                pass


def _close_session(sess: AgentBrowserSession) -> None:
    """Sync, non-blocking: schedule the async close on the running loop. Called by
    the registry (idle expiry / quit) from within an async handler, so a running
    loop exists."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop (not expected from handlers) — best-effort
    loop.create_task(sess.aclose())  # loop keeps a ref until done; aclose swallows its own errors


def _make_wrapper(tool_name: str, doc: str, props: dict, required: list):
    """Build a handler whose runtime __signature__ is (profile, holder, *orig params),
    so fastmcp introspects a full structured schema; routes to the per-profile client."""
    async def handler(**kwargs):
        profile = kwargs.pop("profile", "isolated")
        holder = kwargs.pop("holder", "agent")
        # fastmcp passes UNSET optionals as None; @playwright/mcp's schema rejects
        # null for typed optionals, so forward only real values (omitted = backend default).
        args = {k: v for k, v in kwargs.items() if v is not None}
        udd, pdir, key = _resolve_profile(profile)
        reg = shared_registry()
        sess = reg.get_instance(key, holder)
        if sess is None:
            r = reg.bind(key, ENGINE_AGENT, holder,
                         lambda: AgentBrowserSession(udd, pdir), _close_session)
            if not r.get("bound"):
                return r  # busy / refused by another holder or engine
            sess = reg.get_instance(key, holder)
            if sess is None:  # extreme race (bind then immediate expiry) -- don't crash
                return {"error": "session unavailable right after bind; retry", "profile_key": key}
        return await sess.call(tool_name, args)

    params = [
        inspect.Parameter("profile", inspect.Parameter.KEYWORD_ONLY, annotation=str, default="isolated"),
        inspect.Parameter("holder", inspect.Parameter.KEYWORD_ONLY, annotation=str, default="agent"),
    ]
    ann = {"profile": str, "holder": str}
    for pname, pschema in props.items():
        pytype = _TYPE.get(pschema.get("type"), object)
        if pname in required:
            default = inspect.Parameter.empty
        else:
            default = None
            pytype = Optional[pytype]
        params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY,
                                        annotation=pytype, default=default))
        ann[pname] = pytype
    ann["return"] = dict
    handler.__name__ = tool_name
    handler.__doc__ = (doc or tool_name)[:400]
    handler.__signature__ = inspect.Signature(params)
    handler.__annotations__ = ann
    return handler


class AgentBrowserCapability(CapabilityModule):
    id = "agent_browser"
    display_name = "浏览器 agent_browser(有自动化痕迹,多 profile)"
    origin = ORIGIN_PROXIED
    skill = "using-fleet-browser"
    platforms = None
    usage_hint = (
        "端到端测试 / 浏览学习,多 profile 真并行:每个 browser_* 工具带 profile(默认 isolated)"
        "+ holder(默认 agent)。首次调用自动 bind 起该 profile 的 Chrome;browser_bind 显式绑定、"
        "browser_release 解绑保留进程(秒复用)、browser_quit 关进程、browser_status 看租约。"
        "有自动化痕迹(CDP);作为人本人操作真实账号用 human_browser。"
    )

    def __init__(self, profile_dir: Optional[str] = None):
        self.description = (
            "代理型(嫁接 Playwright MCP),多 profile 真并行:每 profile 一个 @playwright/mcp 子进程,"
            "browser_* 工具带 profile 参数路由,经租约(bind/release/quit/idle)管理。永不 headless。"
        )
        self._default_isolated = profile_dir  # optional override for 'isolated'

    def availability(self) -> tuple[bool, str]:
        if shutil.which("npx", path=_augmented_path()) is None:
            return False, "node/npx 未找到(需装 node + @playwright/mcp;见 using-fleet-browser skill)"
        return True, ""

    def _introspect(self) -> list[tuple]:
        """Start a throwaway @playwright/mcp client once, list its tools, close it.
        Runs in register() (server setup, no running loop) via asyncio.run."""
        async def go():
            from fastmcp import Client
            from fastmcp.client.transports import StdioTransport
            udd = str(Path.home() / ".fleet" / "agent-browser-probe")
            c = Client(StdioTransport(
                command="npx",
                args=["-y", "@playwright/mcp@latest", "--browser", "chrome", "--user-data-dir", udd],
                env=_augmented_env(),
            ))
            async with c:
                tools = await c.list_tools()
            return [
                (t.name, getattr(t, "description", "") or t.name,
                 (t.inputSchema or {}).get("properties", {}),
                 (t.inputSchema or {}).get("required", []))
                for t in tools
            ]
        return asyncio.run(go())

    def register(self, mcp) -> list[str]:
        schemas = self._introspect()  # raises if npx/playwright can't start -> registry marks unavailable
        names = []
        for name, doc, props, req in schemas:
            mcp.add_tool(_make_wrapper(name, doc, props, req))
            names.append(name)

        reg = shared_registry()

        @mcp.tool
        async def browser_bind(profile: str = "isolated", holder: str = "agent") -> dict:
            """显式绑定指定 profile 的 agent 浏览器(起 @playwright/mcp + Chrome)。
            profile: 'isolated'(默认隔离)/ 目录路径 / 'dir@ProfileName'。被他人占→拒绝+auto_release_in。"""
            udd, pdir, key = _resolve_profile(profile)
            return reg.bind(key, ENGINE_AGENT, holder,
                            lambda: AgentBrowserSession(udd, pdir), _close_session)

        @mcp.tool
        async def browser_release(profile: str, holder: str = "agent") -> dict:
            """解绑指定 profile(保留浏览器进程供秒复用;idle 超时才真关)。"""
            _, _, key = _resolve_profile(profile)
            return reg.release(key, holder)

        @mcp.tool
        async def browser_quit(profile: str, holder: str = "agent") -> dict:
            """关闭指定 profile 的浏览器进程并删除租约(detached 进程任何调用方可关)。"""
            _, _, key = _resolve_profile(profile)
            return reg.close(key, holder)

        @mcp.tool
        async def browser_status() -> dict:
            """列出所有 agent/human 浏览器租约(profile/engine/holder/state/idle/auto_release_in)。"""
            return reg.status()

        names += _MGMT_TOOLS
        return names

    def proxied_tools(self) -> list[str]:
        return list(PLAYWRIGHT_TOOLS) + _MGMT_TOOLS
