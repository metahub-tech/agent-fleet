"""Shared launch runtime for the device MCP servers.

Lets a parent process (e.g. AgentHub desktop) launch a platform server as a
managed child:

  - ``--host`` chooses the bind address. Default stays ``0.0.0.0`` (existing
    Tailscale/Firewall-gated deployments keep working); pass ``127.0.0.1`` for
    loopback-only, which is reachable by this machine alone and needs no
    firewall rule, open port, or admin rights.
  - ``--port`` chooses the listen port. The parent can scan for a free port and
    pass it in, so a busy default port no longer blocks startup.
  - ``--token`` enables a shared-secret bearer gate. When set, every request
    (except the health probe) must carry ``Authorization: Bearer <token>``.
    Empty token = no auth (transitional, e.g. trusted loopback before a token
    is provisioned).

All three accept an environment-variable fallback (``FLEET_HOST`` /
``FLEET_PORT`` / ``FLEET_AUTH_TOKEN``) so a launcher can inject them either way.

The bearer gate is a *pure ASGI* middleware on purpose: ``BaseHTTPMiddleware``
buffers the response body, which would break the streamable-http transport the
servers rely on for long-running tool calls. This middleware only inspects the
request scope — it either short-circuits with 401 or passes the call through
untouched, so streaming is preserved.
"""
from __future__ import annotations

import argparse
import hmac
import os
import sys

from starlette.middleware import Middleware

HEALTH_PATH = "/health"

_HOST_ENV = "FLEET_HOST"
_PORT_ENV = "FLEET_PORT"
_TOKEN_ENV = "FLEET_AUTH_TOKEN"

_DEFAULT_HOST = "0.0.0.0"


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to ``default`` when the
    variable is unset, blank, or not a valid integer."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def parse_server_args(prog: str, default_port: int, argv: "list[str] | None" = None) -> argparse.Namespace:
    """Parse ``--host`` / ``--port`` / ``--token`` for a platform server.

    Precedence per flag: explicit CLI value > environment variable > built-in
    default. ``argv`` is accepted so tests can drive it without touching
    ``sys.argv``.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run the device MCP server (host/port/token configurable).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get(_HOST_ENV, _DEFAULT_HOST),
        help=f"Bind address. Default {_DEFAULT_HOST!r} (firewall/Tailscale gated). "
        "Pass 127.0.0.1 for loopback-only.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int(_PORT_ENV, default_port),
        help=f"Listen port (default {default_port}).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get(_TOKEN_ENV, ""),
        help="Shared-secret bearer token. When set, every request except "
        f"{HEALTH_PATH} must send 'Authorization: Bearer <token>'. "
        "Empty = no auth (transitional).",
    )
    return parser.parse_args(argv)


class BearerAuthMiddleware:
    """Pure-ASGI shared-secret bearer gate.

    Constructed by Starlette's ``Middleware(BearerAuthMiddleware, token=...)``
    wrapper, which calls ``BearerAuthMiddleware(app, token=...)``.
    """

    def __init__(self, app, token: str, exempt_paths: "tuple[str, ...]" = (HEALTH_PATH,)):
        self.app = app
        self._token = token or ""
        self._exempt = tuple(exempt_paths)

    async def __call__(self, scope, receive, send) -> None:
        # Only gate HTTP requests; a blank token disables the gate entirely.
        if scope.get("type") != "http" or not self._token:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if self._is_exempt(path) or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        await self._reject(send)

    def _is_exempt(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self._exempt)

    def _authorized(self, scope) -> bool:
        expected = f"Bearer {self._token}"
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                got = value.decode("latin-1")
                # constant-time compare to avoid leaking the token via timing.
                return hmac.compare_digest(got, expected)
        return False

    @staticmethod
    async def _reject(send) -> None:
        body = b'{"error":"unauthorized"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def auth_middleware(token: str) -> "list[Middleware]":
    """Middleware list for ``mcp.run(..., middleware=...)``.

    Empty list when no token is configured, so the server runs exactly as
    before in the transitional no-auth case.
    """
    if not token:
        return []
    return [Middleware(BearerAuthMiddleware, token=token)]


def register_health_route(mcp) -> None:
    """Register an unauthenticated ``GET /health`` so a parent process can probe
    liveness before routing MCP traffic. Must be called before the app is built
    (i.e. before ``mcp.run``)."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @mcp.custom_route(HEALTH_PATH, methods=["GET"])
    async def _health(request: "Request") -> "JSONResponse":  # noqa: ARG001
        return JSONResponse({"status": "ok"})


def _run_app(app, host: str, port: int) -> None:
    """Launch a Starlette/ASGI *app* directly via uvicorn.

    Extracted as a module-level function so tests can monkeypatch it without
    needing a real uvicorn install.
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


def serve(
    mcp,
    prog: str,
    default_port: int,
    argv: "list[str] | None" = None,
    extra_routes: "list[tuple[str, object]] | None" = None,
) -> None:
    """Parse args, wire the health route + optional bearer gate, and run the
    server over streamable-http. Shared entry used by each platform's
    ``main()``."""
    # Line-buffer stdio first so a parent process (launcher / Task Scheduler /
    # AgentHub desktop) reading our redirected stdout/stderr sees logs in real
    # time, instead of waiting for an ~8 KB pipe buffer to fill or the process to
    # exit. Non-tty pipes default to block buffering, which would otherwise hide
    # startup/health logs the parent uses for readiness checks.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    args = parse_server_args(prog, default_port, argv)
    register_health_route(mcp)

    if not extra_routes:
        # Original path: delegate everything to FastMCP's own run(), which
        # handles uvicorn startup internally.  Pass `middleware` only when a
        # gate is configured so the no-token transitional case is byte-for-byte
        # unchanged (avoids handing an empty list to the transport layer).
        run_kwargs: "dict[str, object]" = {
            "transport": "http",
            "host": args.host,
            "port": args.port,
        }
        gate = auth_middleware(args.token)
        if gate:
            run_kwargs["middleware"] = gate
        mcp.run(**run_kwargs)
        return

    # Extra-routes path: build the Starlette app ourselves so we can attach WS
    # routes (e.g. the /dom-bridge Chrome-extension channel) that FastMCP's
    # mcp.run() has no API for.
    gate = auth_middleware(args.token)
    app = mcp.http_app(transport="http", middleware=gate or None)
    for path, handler in extra_routes:
        app.router.add_websocket_route(path, handler)
    _run_app(app, args.host, args.port)
