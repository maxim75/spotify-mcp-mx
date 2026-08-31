from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.catalog import (
    get_album_info,
    get_artist_info,
    get_track_info,
    search_music,
)
from tests.fixtures import ALBUM, ARTIST, TRACK

if TYPE_CHECKING:
    from tests.conftest import FakeCtx, FakeSpotify


async def test_search_music_composes_filter_syntax(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {"tracks": {"items": [], "total": 0}}
    await search_music("love", year="2024", genre="pop", artist="Prince", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("search")
    assert kwargs["q"] == "love artist:Prince year:2024 genre:pop"


async def test_search_music_year_range_uses_the_year_filter(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {"tracks": {"items": [], "total": 0}}
    await search_music("love", year_range="2020-2024", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("search")
    assert kwargs["q"] == "love year:2020-2024"


@pytest.mark.parametrize(("given", "sent"), [(0, 1), (-5, 1), (999, 50), (25, 25)])
async def test_search_music_clamps_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx, given: int, sent: int
) -> None:
    fake_spotify.responses["search"] = {"tracks": {"items": [], "total": 0}}
    await search_music("x", limit=given, ctx=ctx)
    _args, kwargs = fake_spotify.last_call("search")
    assert kwargs["limit"] == sent


async def test_search_music_returns_tracks_and_pagination(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {
        "tracks": {
            "items": [copy.deepcopy(TRACK), None],
            "total": 812,
            "limit": 10,
            "offset": 20,
            "next": "https://api.spotify.com/next",
            "previous": None,
        }
    }
    results = await search_music("radiohead", offset=20, ctx=ctx)
    assert len(results.items) == 1  # the null entry is skipped
    assert results.total == 812
    assert results.offset == 20
    assert results.next is not None


async def test_search_music_coerces_artists_into_track_shape(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {
        "artists": {"items": [{"name": "Radiohead", "id": "abc"}], "total": 1}
    }
    results = await search_music("radiohead", qtype="artist", ctx=ctx)
    assert results.items[0].name == "Radiohead"
    assert results.items[0].artist == "Radiohead"


async def test_get_track_info_single_id_uses_the_single_endpoint(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["track"] = copy.deepcopy(TRACK)
    result = await get_track_info("6bMDnAdV1bhrbmwmuHRk9c", ctx=ctx)
    assert fake_spotify.called("track")
    assert not fake_spotify.called("tracks")
    assert len(result.tracks) == 1


async def test_get_track_info_batches_above_one_id(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["tracks"] = {"tracks": [copy.deepcopy(TRACK), None]}
    result = await get_track_info(["a", "b"], ctx=ctx)
    assert fake_spotify.called("tracks")
    assert len(result.tracks) == 1


async def test_get_track_info_rejects_more_than_fifty(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await get_track_info([f"id-{i}" for i in range(51)], ctx=ctx)
    assert str(excinfo.value) == "Maximum 50 track IDs per request (Spotify API limit)"


async def test_get_artist_info_truncates_to_ten_top_tracks(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["artist"] = copy.deepcopy(ARTIST)
    fake_spotify.responses["artist_top_tracks"] = {
        "tracks": [copy.deepcopy(TRACK) for _ in range(15)]
    }
    info = await get_artist_info("4Z8W4fKeB5YxbusRsdQVPb", ctx=ctx)
    assert info.artist.name == "Radiohead"
    assert len(info.top_tracks) == 10


async def test_get_album_info_backfills_the_album_on_each_track(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["album"] = copy.deepcopy(ALBUM)
    info = await get_album_info("6GjwtEZcfenmOf6l18N7T7", ctx=ctx)
    assert info.album.label == "XL Recordings"
    # Album track items carry no album of their own; it is filled from the parent.
    assert info.tracks[0].album == "Kid A"
    assert info.tracks[0].album_id == "6GjwtEZcfenmOf6l18N7T7"
    assert info.tracks[0].release_date == "2000-10-02"
