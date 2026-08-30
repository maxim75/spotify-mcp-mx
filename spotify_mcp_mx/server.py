"""The MCP server instance and the harness every tool call goes through."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import Icon

from . import __version__
from .auth import (
    _MISSING_MESSAGE,
    CLIENT_ID_HEADER,
    CLIENT_SECRET_HEADER,
    REFRESH_TOKEN_HEADER,
    spotify_for,
)
from .errors import MissingCredentialsError, convert_spotify_error

if TYPE_CHECKING:
    from collections.abc import Callable

    import spotipy

__all__ = ["INSTRUCTIONS", "SPOTIFY_ICON", "mcp", "run_tool"]

logger = logging.getLogger(__name__)

# Guidance that applies to the whole surface lives here rather than in every
# tool description — it ships once per session instead of once per tool.
INSTRUCTIONS = f"""\
Spotify for the signed-in user. Tracks, albums, artists and playlists are accepted as
bare IDs or spotify: URIs anywhere.

Every request must carry the caller's own Spotify credentials in the
{CLIENT_ID_HEADER}, {CLIENT_SECRET_HEADER} and {REFRESH_TOKEN_HEADER} HTTP headers.
This server stores no credentials.

Start from search_music to turn names into IDs. get_playlist_tracks returns zero-based
positions, which reorder_playlist_tracks and remove_tracks_from_playlist need.

Playback tools need Spotify Premium and an open device; if none is active, call
list_devices then transfer_playback.

Spotify has withdrawn /recommendations, audio-features and related-artists from
third-party apps, so there is no recommendation endpoint to call. Build suggestions
from get_top_items and get_recently_played plus search_music instead.

Newly created playlists may read back as public even when created private; that is
Spotify's reporting, not a failed write.
"""

# Shared Spotify glyph, attached to the server and to every tool.
SPOTIFY_ICON = Icon(
    src=(
        "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdC"
        "b3g9IjAgMCAyNCAyNCI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTIiIGZpbGw9IiMxREI5NTQiLz48"
        "cGF0aCBmaWxsPSIjZmZmIiBkPSJNMTcgMTYuNmEuNy43IDAgMCAxLTEgLjI1Yy0yLjctMS42NS02LjEtMi0x"
        "MC4xLTEuMWEuNzUuNzUgMCAxIDEtLjMzLTEuNDZjNC40LTEgOC4yLS42IDExLjIgMS4yNS4zNS4yLjQ2LjY2"
        "LjIzIDEuMDZ6bTEuMy0yLjk1YS45NC45NCAwIDAgMS0xLjI5LjNjLTMuMS0xLjktNy44LTIuNDYtMTEuNDUt"
        "MS4zNWEuOTQuOTQgMCAxIDEtLjU1LTEuOGM0LjE4LTEuMjcgOS4zNi0uNjUgMTIuOTMgMS41NS40NC4yNy41"
        "OC44NS4zNiAxLjN6bS4xLTMuMDdDMTQuNyA4LjQgOC45IDguMiA1LjQzIDkuMjZhMS4xMiAxLjEyIDAgMSAx"
        "LS42NS0yLjE1QzguNzYgNS45IDE1LjE4IDYuMTMgMTkuNDUgOC42NmExLjEyIDEuMTIgMCAxIDEtMS4xNSAx"
        "LjkyeiIvPjwvc3ZnPg=="
    ),
    mime_type="image/svg+xml",
)

mcp = MCPServer(
    "Spotify MCP",
    title="Spotify",
    instructions=INSTRUCTIONS,
    website_url="https://github.com/maxim75/spotify-mcp-mx",
    icons=[SPOTIFY_ICON],
    version=__version__,
)


async def run_tool[T](ctx: Context | None, fn: Callable[[spotipy.Spotify, str], T]) -> T:
    """Run *fn* with a client built from this request's credentials.

    ``fn`` receives ``(client, cache_scope)`` and runs entirely on a worker
    thread, because everything it touches blocks: the token exchange, and
    spotipy's synchronous ``requests`` calls. A slow Spotify response must not
    stall the event loop and every other in-flight call with it.

    Headers are read here, on the event loop, and copied into the closure —
    ``ctx`` itself is never handed to the worker.

    ``ctx`` is ``None`` when a tool is called without the SDK's context
    injection wired up (e.g. directly, rather than through a live session);
    that surfaces as the same missing-credentials error a request with no
    headers would produce.
    """
    if ctx is None:
        raise convert_spotify_error(MissingCredentialsError(_MISSING_MESSAGE)) from None

    headers = dict(getattr(ctx, "headers", None) or {})

    def work() -> T:
        with spotify_for(headers) as (client, scope):
            return fn(client, scope)

    try:
        return await anyio.to_thread.run_sync(work)
    except Exception as exc:  # noqa: BLE001 - re-raised as a classified ToolError
        raise convert_spotify_error(exc) from None
