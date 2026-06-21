"""Tests for _server_runtime: CLI arg resolution + bearer ASGI gate.

Dependency-free: arg parsing is pure; the middleware's async ``__call__`` is
driven directly via ``asyncio.run`` (no pytest-asyncio needed). A blank token
must leave the server exactly as before (no gate).
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.middleware import Middleware  # noqa: E402

from _server_runtime import (  # noqa: E402
    BearerAuthMiddleware,
    HEALTH_PATH,
    auth_middleware,
    parse_server_args,
)


# ----------------------------- arg parsing -----------------------------


@pytest.fixture(autouse=True)
def _clear_fleet_env(monkeypatch):
    for var in ("FLEET_HOST", "FLEET_PORT", "FLEET_AUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_defaults():
    ns = parse_server_args("prog", 8766, argv=[])
    assert ns.host == "0.0.0.0"
    assert ns.port == 8766
    assert ns.token == ""


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("FLEET_HOST", "127.0.0.1")
    monkeypatch.setenv("FLEET_PORT", "8770")
    monkeypatch.setenv("FLEET_AUTH_TOKEN", "envsecret")
    ns = parse_server_args("prog", 8766, argv=[])
    assert ns.host == "127.0.0.1"
    assert ns.port == 8770
    assert ns.token == "envsecret"


def test_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("FLEET_HOST", "127.0.0.1")
    monkeypatch.setenv("FLEET_PORT", "8770")
    monkeypatch.setenv("FLEET_AUTH_TOKEN", "envsecret")
    ns = parse_server_args(
        "prog", 8766, argv=["--host", "0.0.0.0", "--port", "9001", "--token", "clisecret"]
    )
    assert ns.host == "0.0.0.0"
    assert ns.port == 9001
    assert ns.token == "clisecret"


def test_invalid_port_env_falls_back(monkeypatch):
    monkeypatch.setenv("FLEET_PORT", "not-an-int")
    ns = parse_server_args("prog", 8766, argv=[])
    assert ns.port == 8766


# --------------------------- middleware list ---------------------------


def test_auth_middleware_empty_when_no_token():
    assert auth_middleware("") == []


def test_auth_middleware_wraps_token():
    mws = auth_middleware("secret")
    assert len(mws) == 1
    assert isinstance(mws[0], Middleware)
    assert mws[0].cls is BearerAuthMiddleware
    assert mws[0].kwargs["token"] == "secret"


# ----------------------------- bearer gate -----------------------------


class _RecordingApp:
    """Downstream ASGI app that records whether it was reached."""

    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


class _Sink:
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)

    @property
    def status(self):
        for m in self.messages:
            if m["type"] == "http.response.start":
                return m["status"]
        return None


def _http_scope(path="/mcp", headers=None):
    return {"type": "http", "path": path, "headers": headers or []}


def _drive(token, scope):
    app = _RecordingApp()
    sink = _Sink()
    mw = BearerAuthMiddleware(app, token=token)
    asyncio.run(mw(scope, _receive, sink))
    return app, sink


def test_no_token_passes_through():
    app, sink = _drive("", _http_scope())
    assert app.called
    assert sink.status == 200


def test_missing_auth_header_rejected():
    app, sink = _drive("secret", _http_scope())
    assert not app.called
    assert sink.status == 401


def test_wrong_token_rejected():
    scope = _http_scope(headers=[(b"authorization", b"Bearer nope")])
    app, sink = _drive("secret", scope)
    assert not app.called
    assert sink.status == 401


def test_correct_token_passes_through():
    scope = _http_scope(headers=[(b"authorization", b"Bearer secret")])
    app, sink = _drive("secret", scope)
    assert app.called
    assert sink.status == 200


def test_health_path_exempt():
    # Token set, no auth header, but /health is exempt → reaches the app.
    app, sink = _drive("secret", _http_scope(path=HEALTH_PATH))
    assert app.called
    assert sink.status == 200


def test_non_http_scope_passes_through():
    app, sink = _drive("secret", {"type": "lifespan"})
    assert app.called


# --------------------- FastMCP wiring (integration) ---------------------
# The unit tests above drive BearerAuthMiddleware in isolation; they can't see
# whether serve()'s real build path actually applies the gate. These exercise
# that path — register_health_route(mcp) + mcp.http_app(middleware=...) — over an
# in-process httpx ASGI transport, so a silently-dropped `middleware` kwarg or a
# broken custom_route would be caught. Skipped when fastmcp/httpx aren't present
# (CI's python-tests job installs neither and doesn't run common/ tests; this is
# meant to be run in a platform server venv).
try:  # noqa: SIM105
    import fastmcp  # noqa: F401
    import httpx  # noqa: F401

    _HAS_FASTMCP = True
except ImportError:  # pragma: no cover
    _HAS_FASTMCP = False

requires_fastmcp = pytest.mark.skipif(
    not _HAS_FASTMCP, reason="fastmcp/httpx not installed (run in a server venv)"
)


def _build_app(token):
    from fastmcp import FastMCP

    from _server_runtime import register_health_route

    mcp = FastMCP("test-server-runtime")
    register_health_route(mcp)
    # Mirror serve()'s conditional: only hand `middleware` to FastMCP when a gate
    # exists, exactly as the production path does.
    mws = auth_middleware(token)
    return mcp.http_app(middleware=mws) if mws else mcp.http_app()


async def _get(app, path, headers=None):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        return await c.get(path, headers=headers or {})


@requires_fastmcp
def test_health_route_reachable_unauthenticated():
    # /health is registered via custom_route and exempt from the gate even when a
    # token is configured — the parent's liveness probe must not need the secret.
    r = asyncio.run(_get(_build_app("secret"), HEALTH_PATH))
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@requires_fastmcp
def test_fastmcp_app_gates_without_token():
    # A non-exempt path with no Authorization header → middleware short-circuits
    # 401 before routing. Proves the gate is actually wired into the FastMCP app.
    r = asyncio.run(_get(_build_app("secret"), "/does-not-exist"))
    assert r.status_code == 401


@requires_fastmcp
def test_fastmcp_app_passes_with_correct_token():
    # Correct token → gate passes; Starlette then 404s the unknown path. The point
    # is only that it is NOT 401 (the request got past the gate).
    r = asyncio.run(
        _get(_build_app("secret"), "/does-not-exist", headers={"authorization": "Bearer secret"})
    )
    assert r.status_code != 401


@requires_fastmcp
def test_fastmcp_app_no_token_means_no_gate():
    # No token configured → serve() passes no middleware → nothing is gated.
    r = asyncio.run(_get(_build_app(""), "/does-not-exist"))
    assert r.status_code != 401
