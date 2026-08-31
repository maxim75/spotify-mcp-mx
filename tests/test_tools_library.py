from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.library import (
    get_me,
    get_recently_played,
    get_saved_tracks,
    get_top_items,
    remove_saved_tracks,
    save_tracks,
)
from tests.fixtures import ARTIST, TRACK

if TYPE_CHECKING:
    from tests.conftest import FakeCtx, FakeSpotify


async def test_get_me_maps_the_profile(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["current_user"] = {
        "id": "maksym",
        "display_name": "Maksym",
        "followers": {"total": 12},
    }
    profile = await get_me(ctx)
    assert profile.id == "maksym"
    assert profile.display_name == "Maksym"
    assert profile.followers == 12


async def test_get_me_tolerates_a_stripped_profile(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    # The restricted regime returns id only; that must not be an error.
    fake_spotify.responses["current_user"] = {"id": "maksym"}
    profile = await get_me(ctx)
    assert profile.email is None
    assert profile.country is None
    assert profile.product is None


async def test_get_saved_tracks_populates_added_at(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_saved_tracks"] = {
        "items": [{"added_at": "2026-01-02T03:04:05Z", "track": copy.deepcopy(TRACK)}, None],
        "total": 900,
        "limit": 20,
        "offset": 0,
    }
    page = await get_saved_tracks(ctx=ctx)
    assert len(page.items) == 1
    assert page.items[0].added_at == "2026-01-02T03:04:05Z"
    assert page.total == 900


async def test_get_saved_tracks_clamps_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_saved_tracks"] = {"items": [], "total": 0}
    await get_saved_tracks(limit=500, ctx=ctx)
    _args, kwargs = fake_spotify.last_call("current_user_saved_tracks")
    assert kwargs["limit"] == 50


async def test_save_tracks_delegates_with_the_caller_scope(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.save_tracks",
        lambda client, scope, ids: seen.update(scope=scope, ids=ids),
    )
    result = await save_tracks(["abc"], ctx=ctx)
    assert seen["scope"] == "id-1"
    assert seen["ids"] == ["abc"]
    assert result.status == "success"


async def test_save_tracks_rejects_more_than_fifty(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await save_tracks([f"id-{i}" for i in range(51)], ctx=ctx)
    assert str(excinfo.value) == "Maximum 50 track IDs per request (Spotify API limit)"


async def test_remove_saved_tracks_rejects_more_than_fifty(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError):
        await remove_saved_tracks([f"id-{i}" for i in range(51)], ctx=ctx)


async def test_get_top_items_tracks(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["current_user_top_tracks"] = {"items": [copy.deepcopy(TRACK)]}
    result = await get_top_items(ctx=ctx)
    assert result.time_range == "medium_term"
    assert result.tracks is not None and len(result.tracks) == 1
    assert result.artists is None


async def test_get_top_items_artists(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["current_user_top_artists"] = {"items": [copy.deepcopy(ARTIST)]}
    result = await get_top_items(item_type="artists", ctx=ctx)
    assert result.artists is not None and result.artists[0].name == "Radiohead"
    assert result.tracks is None


async def test_get_top_items_validates_item_type(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await get_top_items(item_type="albums", ctx=ctx)
    assert str(excinfo.value) == "item_type must be 'tracks' or 'artists'"


async def test_get_top_items_validates_time_range(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await get_top_items(time_range="forever", ctx=ctx)
    assert str(excinfo.value) == (
        "time_range must be 'short_term', 'medium_term' or 'long_term'"
    )


async def test_get_recently_played_populates_played_at(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_recently_played"] = {
        "items": [{"played_at": "2026-08-30T10:00:00Z", "track": copy.deepcopy(TRACK)}]
    }
    result = await get_recently_played(ctx=ctx)
    assert result.items[0].played_at == "2026-08-30T10:00:00Z"
