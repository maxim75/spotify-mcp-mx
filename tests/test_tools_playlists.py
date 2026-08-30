from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.playlists import (
    add_tracks_to_playlist,
    create_playlist,
    get_playlist_info,
    get_playlist_tracks,
    get_user_playlists,
    modify_playlist_details,
    remove_tracks_from_playlist,
    reorder_playlist_tracks,
    unfollow_playlist,
)
from tests.fixtures import PLAYLIST, TRACK

if TYPE_CHECKING:
    from tests.conftest import FakeCtx, FakeSpotify


async def test_get_user_playlists_maps_and_paginates(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_playlists"] = {
        "items": [copy.deepcopy(PLAYLIST)],
        "total": 62,
        "limit": 20,
        "offset": 0,
        "next": "https://api.spotify.com/next",
    }
    page = await get_user_playlists(ctx=ctx)
    assert page.items[0].name == "Late Night"
    assert page.items[0].owner == "maksym"
    assert page.total == 62
    assert page.next is not None


async def test_get_user_playlists_clamps_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_playlists"] = {"items": [], "total": 0}
    await get_user_playlists(limit=0, ctx=ctx)
    _args, kwargs = fake_spotify.last_call("current_user_playlists")
    assert kwargs["limit"] == 1


async def test_get_playlist_info_requests_only_metadata_fields(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["playlist"] = copy.deepcopy(PLAYLIST)
    info = await get_playlist_info("37i9dQZF1DX4sWSpwq3LiO", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("playlist")
    assert kwargs["fields"] == "id,name,description,owner,public,tracks.total"
    assert info.total_tracks == 148
    assert info.tracks is None


async def test_get_playlist_tracks_pages_and_reports_progress(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_spotify.responses["playlist"] = {"tracks": {"total": 150}}

    def pages(client: Any, scope: str, playlist_id: str, *, limit: int, offset: int) -> Any:
        remaining = max(0, 150 - offset)
        count = min(limit, remaining)
        return {
            "items": [{"item": copy.deepcopy(TRACK)} for _ in range(count)],
            "next": "more" if offset + count < 150 else None,
        }

    monkeypatch.setattr("spotify_mcp_mx.spotify_api.playlist_items", pages)

    result = await get_playlist_tracks("37i9", ctx=ctx)
    assert result.returned == 150
    assert result.total == 150
    assert len(result.items) == 150
    # One progress report per page: 100 then 150.
    assert ctx.progress == [(100.0, 150.0), (150.0, 150.0)]


async def test_get_playlist_tracks_reads_the_legacy_track_key(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_spotify.responses["playlist"] = {"tracks": {"total": 1}}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.playlist_items",
        lambda *a, **k: {"items": [{"track": copy.deepcopy(TRACK)}], "next": None},
    )
    result = await get_playlist_tracks("37i9", ctx=ctx)
    assert result.items[0].name == "Idioteque"


async def test_get_playlist_tracks_honours_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_spotify.responses["playlist"] = {"tracks": {"total": 500}}
    seen: list[int] = []

    def pages(client: Any, scope: str, pid: str, *, limit: int, offset: int) -> Any:
        seen.append(limit)
        return {"items": [{"item": copy.deepcopy(TRACK)} for _ in range(limit)], "next": "m"}

    monkeypatch.setattr("spotify_mcp_mx.spotify_api.playlist_items", pages)
    result = await get_playlist_tracks("37i9", limit=30, ctx=ctx)
    assert result.returned == 30
    assert seen == [30]


async def test_create_playlist(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.create_playlist",
        lambda client, scope, name, description, public: {
            "id": "new1",
            "name": name,
            "description": description,
            "public": public,
            "owner": {"display_name": "maksym"},
        },
    )
    playlist = await create_playlist("Focus", description="deep work", public=False, ctx=ctx)
    assert playlist.id == "new1"
    assert playlist.name == "Focus"
    assert playlist.total_tracks == 0


async def test_modify_playlist_details_requires_a_field(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await modify_playlist_details("37i9", ctx=ctx)
    assert str(excinfo.value) == (
        "At least one of name, description, or public must be provided"
    )


async def test_modify_playlist_details_passes_fields_through(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    result = await modify_playlist_details("37i9", name="Renamed", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("playlist_change_details")
    assert kwargs["name"] == "Renamed"
    assert result.status == "success"


async def test_add_tracks_normalises_to_uris(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.playlist_add_items",
        lambda client, scope, pid, uris: seen.update(uris=uris) or {"snapshot_id": "s1"},
    )
    result = await add_tracks_to_playlist("37i9", ["abc", "spotify:track:def"], ctx=ctx)
    assert seen["uris"] == ["spotify:track:abc", "spotify:track:def"]
    assert result.snapshot_id == "s1"


async def test_remove_tracks_removes_without_confirming(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Elicitation is out of scope; the destructive_hint annotation is what tells
    # clients to confirm. The tool itself must simply perform the removal.
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.playlist_remove_items",
        lambda client, scope, pid, uris: seen.update(uris=uris) or {"snapshot_id": "s2"},
    )
    result = await remove_tracks_from_playlist("37i9", ["abc"], ctx=ctx)
    assert seen["uris"] == ["spotify:track:abc"]
    assert result.status == "success"
    assert result.snapshot_id == "s2"


async def test_reorder_validates_positions(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await reorder_playlist_tracks("37i9", range_start=-1, insert_before=3, ctx=ctx)
    assert str(excinfo.value) == "range_start and insert_before must be >= 0"


async def test_reorder_validates_range_length(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await reorder_playlist_tracks(
            "37i9", range_start=0, insert_before=3, range_length=0, ctx=ctx
        )
    assert str(excinfo.value) == "range_length must be >= 1"


async def test_reorder_passes_every_argument(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def reorder(client: Any, scope: str, pid: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return {"snapshot_id": "s3"}

    monkeypatch.setattr("spotify_mcp_mx.spotify_api.playlist_reorder_items", reorder)
    await reorder_playlist_tracks(
        "37i9", range_start=0, insert_before=10, range_length=3, snapshot_id="old", ctx=ctx
    )
    assert seen == {
        "range_start": 0,
        "insert_before": 10,
        "range_length": 3,
        "snapshot_id": "old",
    }


async def test_unfollow_playlist_normalises_the_id(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    result = await unfollow_playlist("spotify:playlist:37i9", ctx=ctx)
    args, _kwargs = fake_spotify.last_call("current_user_unfollow_playlist")
    assert args[0] == "37i9"
    assert result.status == "success"
