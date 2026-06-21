"""Integration tests: the bearer gate + /health route are really wired into the
FastMCP app that ``_server_runtime.serve()`` runs — not just unit-tested in
isolation (``test_server_runtime.py`` covers the helper's pure logic).

Platform-agnostic on purpose: it builds a *minimal* ``FastMCP()`` and drives it
over an in-process httpx ASGI transport, importing NO platform deps (pyautogui /
pyobjc / pywinauto). So this one file runs on Linux CI and is shared by the
windows + macOS bridges (and any future platform adopting ``serve()``).

Skipped when fastmcp / httpx aren't importable. (CI's ``python-tests`` job
installs neither and does not run ``platforms/common/tests``; this is meant to be
run inside a platform server venv, where both are present as fastmcp deps.)
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _server_runtime import (  # noqa: E402
    HEALTH_PATH,
    auth_middleware,
    register_health_route,
)

try:
    import fastmcp  # noqa: F401
    import httpx  # noqa: F401

    _HAS_DEPS = True
except ImportError:  # pragma: no cover
    _HAS_DEPS = False

pytestmark = pytest.mark.skipif(
    not _HAS_DEPS, reason="fastmcp/httpx not installed (run in a server venv)"
)


def _build_app(token):
    """Build the same app shape serve() runs: a FastMCP http app with the health
    route registered and the bearer gate applied only when a token is set."""
    from fastmcp import FastMCP

    mcp = FastMCP("test-server-app-integration")
    register_health_route(mcp)
    # Mirror serve()'s conditional: only hand `middleware` to FastMCP when a gate
    # is configured (and exactly via http_app(middleware=...), the path run uses).
    mws = auth_middleware(token)
    if mws:
        return mcp.http_app(transport="http", middleware=mws)
    return mcp.http_app(transport="http")


async def _get(app, path, headers=None):
    # Enter the app lifespan so /mcp's session manager is initialized; the gate
    # short-circuits 401 before that matters, but a passed-through /mcp needs it.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers or {})


def _run(app, path, headers=None):
    return asyncio.run(_get(app, path, headers))


def test_health_unauthenticated_ok():
    # /health is exempt even with a token configured — the parent's liveness probe
    # must not need the secret.
    r = _run(_build_app("secret"), HEALTH_PATH)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_mcp_no_token_rejected():
    # No Authorization header on a gated path → middleware 401 before routing.
    r = _run(_build_app("secret"), "/mcp")
    assert r.status_code == 401


def test_mcp_wrong_token_rejected():
    r = _run(_build_app("secret"), "/mcp", headers={"authorization": "Bearer nope"})
    assert r.status_code == 401


def test_mcp_correct_token_passes_gate():
    # Correct token → past the gate. The MCP endpoint may then answer 400/406 for a
    # bare GET; the point is only that it is NOT 401 (the request got through).
    r = _run(_build_app("secret"), "/mcp", headers={"authorization": "Bearer secret"})
    assert r.status_code != 401


def test_no_token_config_passes_through():
    # No token configured → serve() passes no middleware → nothing is gated.
    r = _run(_build_app(""), "/mcp")
    assert r.status_code != 401
