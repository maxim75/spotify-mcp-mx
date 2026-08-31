"""Smoke tests against the real Spotify API.

Opt-in: these skip themselves unless all three SPOTIFY_* variables are set, so
the default suite stays offline and CI is green without credentials.

    SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... SPOTIFY_REFRESH_TOKEN=... \
      uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN),
        reason="set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN",
    ),
]

HEADERS = {
    "X-Spotify-Client-Id": CLIENT_ID,
    "X-Spotify-Client-Secret": CLIENT_SECRET,
    "X-Spotify-Refresh-Token": REFRESH_TOKEN,
}


class LiveCtx:
    headers = HEADERS


async def test_real_token_exchange_and_profile() -> None:
    from spotify_mcp_mx.tools.library import get_me

    profile = await get_me(LiveCtx())
    assert profile.id


async def test_real_search_returns_tracks() -> None:
    from spotify_mcp_mx.tools.catalog import search_music

    results = await search_music("radiohead", limit=5, ctx=LiveCtx())
    assert results.items
    assert results.total > 0


async def test_second_call_reuses_the_cached_access_token() -> None:
    from spotify_mcp_mx.auth import _TOKEN_CACHE, reset_token_cache
    from spotify_mcp_mx.tools.library import get_me

    reset_token_cache()
    await get_me(LiveCtx())
    assert len(_TOKEN_CACHE) == 1
    await get_me(LiveCtx())
    assert len(_TOKEN_CACHE) == 1
