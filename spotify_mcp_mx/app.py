"""The ASGI application: both MCP transports plus a health check.

Routes:
    ``/mcp``        Streamable HTTP transport (current MCP standard)
    ``/sse``        Legacy SSE transport, with ``/messages/`` for client posts
    ``/health``     Unauthenticated liveness probe for Coolify
    ``/``           Short service description
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from . import __version__
from . import tools as _tools  # noqa: F401  - imported to register all 25 tools
from .auth import CLIENT_ID_HEADER, CLIENT_SECRET_HEADER, REFRESH_TOKEN_HEADER
from .server import mcp

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.requests import Request

__all__ = ["create_app", "default_host", "default_port"]


def default_host() -> str:
    return os.environ.get("HOST", "0.0.0.0")


def default_port() -> int:
    return int(os.environ.get("PORT", "6402"))


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Liveness probe. Deliberately unauthenticated so Coolify can poll it."""
    return JSONResponse({"status": "ok", "version": __version__})


@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "name": "spotify-mcp-mx",
            "version": __version__,
            "description": "MCP server for the Spotify Web API.",
            "endpoints": {"streamable_http": "/mcp", "sse": "/sse", "health": "/health"},
            "authentication": (
                f"Send your own Spotify credentials in the {CLIENT_ID_HEADER}, "
                f"{CLIENT_SECRET_HEADER} and {REFRESH_TOKEN_HEADER} headers on every "
                "request. This server stores no credentials."
            ),
        }
    )


def create_app(host: str | None = None) -> Starlette:
    """Build the ASGI app serving both MCP transports from one process.

    ``streamable_http_app()`` owns the lifespan that runs the session manager,
    so it is the base app. The SSE routes are self-contained (each connection
    runs its own server loop, no lifespan needed), so they can simply be
    appended.

    ``host`` is passed to the SDK only so it can decide about DNS-rebinding
    protection: the SDK auto-enables a localhost-only Host/Origin allowlist when
    told it is serving loopback. Behind Coolify's proxy the request arrives with
    the public domain in Host, which such an allowlist would reject, so the
    default bind address of 0.0.0.0 correctly leaves it off.
    """
    host = host or default_host()

    # Stateless: no session pins a client to one worker, which matters because
    # the caller's credentials travel on every request anyway. Coolify can
    # restart or scale the container without breaking in-flight clients.
    app = mcp.streamable_http_app(stateless_http=True, host=host)

    mounted = {getattr(route, "path", None) for route in app.routes}
    for route in mcp.sse_app(host=host).routes:
        if getattr(route, "path", None) not in mounted:
            app.router.routes.append(route)

    return app
