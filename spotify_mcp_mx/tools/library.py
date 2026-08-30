"""Library and history tools: profile, saved tracks, top items, recently played."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import Context  # noqa: TC002 - the SDK injects by runtime type
from mcp.types import ToolAnnotations

from .. import spotify_api
from ..logging_utils import log_tool_execution
from ..models import ActionResult, RecentlyPlayed, SavedTracks, TopItems, UserProfile
from ..parsing import parse_artist, parse_track
from ..server import SPOTIFY_ICON, mcp, run_tool

if TYPE_CHECKING:
    import spotipy


@mcp.tool(
    title="Spotify Profile",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_me(ctx: Context | None = None) -> UserProfile:
    """Get the signed-in user's Spotify profile.

    Returns:
        UserProfile. email/country/product are unavailable on newer Spotify apps
        and come back empty rather than erroring.
    """

    def work(client: spotipy.Spotify, scope: str) -> UserProfile:
        me = client.current_user() or {}
        return UserProfile(
            id=me["id"],
            display_name=me.get("display_name"),
            email=me.get("email"),
            country=me.get("country"),
            product=me.get("product"),
            followers=(me.get("followers") or {}).get("total"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Get Liked Songs",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_saved_tracks(
    limit: int = 20, offset: int = 0, ctx: Context | None = None
) -> SavedTracks:
    """Get user's saved/liked tracks (Liked Songs library).

    Args:
        limit: Max tracks to return per page (1-50, default 20)
        offset: Number of tracks to skip for pagination (default 0)

    Returns:
        SavedTracks with 'items' (tracks with added_at timestamp) and pagination info
    """

    def work(client: spotipy.Spotify, scope: str) -> SavedTracks:
        clamped_limit = max(1, min(50, limit))

        result = client.current_user_saved_tracks(limit=clamped_limit, offset=offset)

        tracks = []
        for item in result.get("items", []):
            if item and item.get("track"):
                track = parse_track(item["track"])
                track.added_at = item.get("added_at")
                tracks.append(track)

        return SavedTracks(
            items=tracks,
            total=result.get("total", 0),
            limit=result.get("limit", clamped_limit),
            offset=result.get("offset", offset),
            next=result.get("next"),
            previous=result.get("previous"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Like Tracks",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def save_tracks(track_ids: list[str], ctx: Context | None = None) -> ActionResult:
    """Save (like) tracks to the user's library.

    Args:
        track_ids: Track IDs or URIs (up to 50)
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        if len(track_ids) > 50:
            raise ValueError("Maximum 50 track IDs per request (Spotify API limit)")

        spotify_api.save_tracks(client, scope, track_ids)
        return ActionResult(status="success", message=f"Saved {len(track_ids)} track(s)")

    return await run_tool(ctx, work)


@mcp.tool(
    title="Unlike Tracks",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def remove_saved_tracks(track_ids: list[str], ctx: Context | None = None) -> ActionResult:
    """Remove tracks from the user's saved (liked) tracks.

    Args:
        track_ids: Track IDs or URIs (up to 50)
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        if len(track_ids) > 50:
            raise ValueError("Maximum 50 track IDs per request (Spotify API limit)")

        spotify_api.remove_saved_tracks(client, scope, track_ids)
        return ActionResult(status="success", message=f"Removed {len(track_ids)} saved track(s)")

    return await run_tool(ctx, work)


@mcp.tool(
    title="Recently Played",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_recently_played(limit: int = 20, ctx: Context | None = None) -> RecentlyPlayed:
    """Get recently played tracks, most recent first.

    Args:
        limit: Max tracks to return (1-50, default 20)

    Returns:
        RecentlyPlayed with each track's played_at timestamp
    """

    def work(client: spotipy.Spotify, scope: str) -> RecentlyPlayed:
        clamped_limit = max(1, min(50, limit))

        result = client.current_user_recently_played(limit=clamped_limit) or {}

        tracks = []
        for item in result.get("items", []):
            if item and item.get("track"):
                track = parse_track(item["track"])
                track.played_at = item.get("played_at")
                tracks.append(track)

        return RecentlyPlayed(items=tracks)

    return await run_tool(ctx, work)


@mcp.tool(
    title="Top Artists and Tracks",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_top_items(
    item_type: str = "tracks",
    time_range: str = "medium_term",
    limit: int = 20,
    ctx: Context | None = None,
) -> TopItems:
    """Get the user's top artists or tracks over a time range.

    With /recommendations, audio-features and related-artists withdrawn from
    third-party apps, this is the measured foundation for taste profiling and
    building suggestions.

    Args:
        item_type: 'tracks' or 'artists' (default 'tracks')
        time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months) or 'long_term'
        limit: Max items to return (1-50, default 20)

    Returns:
        TopItems with either 'tracks' or 'artists' populated
    """

    def work(client: spotipy.Spotify, scope: str) -> TopItems:
        if item_type not in ("tracks", "artists"):
            raise ValueError("item_type must be 'tracks' or 'artists'")
        if time_range not in ("short_term", "medium_term", "long_term"):
            raise ValueError("time_range must be 'short_term', 'medium_term' or 'long_term'")
        clamped_limit = max(1, min(50, limit))

        if item_type == "tracks":
            result = client.current_user_top_tracks(limit=clamped_limit, time_range=time_range)
            return TopItems(
                time_range=time_range,
                tracks=[parse_track(t) for t in (result or {}).get("items", []) if t],
            )

        result = client.current_user_top_artists(limit=clamped_limit, time_range=time_range)
        return TopItems(
            time_range=time_range,
            artists=[parse_artist(a) for a in (result or {}).get("items", []) if a],
        )

    return await run_tool(ctx, work)
