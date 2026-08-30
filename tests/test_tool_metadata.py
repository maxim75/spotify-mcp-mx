from __future__ import annotations

import re
from pathlib import Path

import spotify_mcp_mx.tools  # noqa: F401  - registers every tool
from spotify_mcp_mx.server import mcp

README = Path(__file__).resolve().parent.parent / "README.md"

EXPECTED = {
    "get_me",
    "search_music",
    "get_track_info",
    "get_artist_info",
    "get_album_info",
    "get_playback_state",
    "control_playback",
    "list_devices",
    "transfer_playback",
    "get_queue",
    "add_to_queue",
    "get_user_playlists",
    "get_playlist_info",
    "get_playlist_tracks",
    "create_playlist",
    "modify_playlist_details",
    "add_tracks_to_playlist",
    "remove_tracks_from_playlist",
    "reorder_playlist_tracks",
    "unfollow_playlist",
    "get_saved_tracks",
    "save_tracks",
    "remove_saved_tracks",
    "get_top_items",
    "get_recently_played",
}


async def _tools() -> list:
    return await mcp.list_tools()


async def test_exactly_the_expected_tools_are_registered() -> None:
    names = {tool.name for tool in await _tools()}
    assert names == EXPECTED


async def test_every_tool_has_a_title_icon_and_annotations() -> None:
    for tool in await _tools():
        assert tool.title, f"{tool.name} has no title"
        assert tool.icons, f"{tool.name} has no icon"
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.open_world_hint is True, f"{tool.name} is not open-world"


async def test_every_tool_has_a_description_and_output_schema() -> None:
    for tool in await _tools():
        assert tool.description, f"{tool.name} has no description"
        assert tool.output_schema, f"{tool.name} has no structured output schema"


async def test_ctx_is_not_exposed_as_a_tool_argument() -> None:
    """The SDK injects Context by annotation; it must never reach the wire schema."""
    for tool in await _tools():
        properties = (tool.input_schema or {}).get("properties", {})
        assert "ctx" not in properties, f"{tool.name} exposes ctx as an argument"


async def test_destructive_tools_are_marked_destructive() -> None:
    destructive = {
        "remove_tracks_from_playlist",
        "modify_playlist_details",
        "reorder_playlist_tracks",
        "unfollow_playlist",
        "remove_saved_tracks",
    }
    by_name = {tool.name: tool for tool in await _tools()}
    for name in destructive:
        assert by_name[name].annotations.destructive_hint is True, f"{name} not destructive"


async def test_readme_tool_table_matches_the_registered_tools() -> None:
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", README.read_text(), re.MULTILINE))
    assert documented == EXPECTED
