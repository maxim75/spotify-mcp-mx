"""Playlist tools: browse, create, edit membership and ordering, unfollow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context  # noqa: TC002 - the SDK injects by runtime type
from mcp.types import ToolAnnotations

from .. import spotify_api
from ..logging_utils import log_pagination_info, log_tool_execution
from ..models import ActionResult, Playlist, PlaylistList, PlaylistTracks, Track
from ..parsing import parse_playlist, parse_track
from ..server import SPOTIFY_ICON, mcp, run_tool
from ..utils import to_id, to_uri

if TYPE_CHECKING:
    import spotipy

logger = logging.getLogger(__name__)


@mcp.tool(
    title="List My Playlists",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_user_playlists(
    limit: int = 20, offset: int = 0, ctx: Context | None = None
) -> PlaylistList:
    """Get the signed-in user's playlists.

    Args:
        limit: Max playlists to return per page (1-50, default 20)
        offset: Number of playlists to skip for pagination (default 0)

    Returns:
        PlaylistList with 'items' (list of playlists) and pagination info
    """

    def work(client: spotipy.Spotify, scope: str) -> PlaylistList:
        clamped_limit = max(1, min(50, limit))

        result = client.current_user_playlists(limit=clamped_limit, offset=offset) or {}

        playlists = [parse_playlist(item) for item in result.get("items", []) if item]

        return PlaylistList(
            items=playlists,
            total=result.get("total", 0),
            limit=result.get("limit", clamped_limit),
            offset=result.get("offset", offset),
            next=result.get("next"),
            previous=result.get("previous"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Get Playlist Info",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_playlist_info(playlist_id: str, ctx: Context | None = None) -> Playlist:
    """Get metadata for a playlist, without its tracks (see get_playlist_tracks).

    Args:
        playlist_id: Playlist ID

    Returns:
        Playlist with name, description, owner, public and total_tracks
    """

    def work(client: spotipy.Spotify, scope: str) -> Playlist:
        result = client.playlist(
            playlist_id, fields="id,name,description,owner,public,tracks.total"
        )
        return parse_playlist(result)

    return await run_tool(ctx, work)


# Spotify's playlist-items endpoint caps a page at 100.
_PAGE_SIZE = 100

# Stop runaway pagination on a playlist that keeps reporting a next page.
_MAX_OFFSET = 10_000


@mcp.tool(
    title="Get Playlist Tracks",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=True
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_playlist_tracks(
    playlist_id: str,
    limit: int | None = None,
    offset: int = 0,
    ctx: Context | None = None,
) -> PlaylistTracks:
    """Get tracks from a playlist with full pagination support.

    Args:
        playlist_id: Playlist ID
        limit: Max tracks to return (None for all tracks, up to a 10,000 safety limit)
        offset: Number of tracks to skip for pagination (default 0)

    Returns:
        PlaylistTracks with 'items' (list of tracks), 'total', 'limit', 'offset'

    Note: Large playlists require pagination. Use limit/offset to get specific ranges:
    - Get first 100: limit=100, offset=0
    - Get next 100: limit=100, offset=100
    - Get all tracks: limit=None (use with caution on very large playlists)
    """
    if ctx is None:  # pragma: no cover - the SDK always injects a Context
        raise ValueError("get_playlist_tracks requires a request context")

    # Fetch the total up front so progress notifications have a denominator.
    def read_total(client: spotipy.Spotify, scope: str) -> int | None:
        info = client.playlist(playlist_id, fields="tracks.total")
        total: int | None = (info.get("tracks") or {}).get("total")
        return total

    total_tracks = await run_tool(ctx, read_total)

    tracks: list[Track] = []
    current_offset = offset
    remaining = limit

    while True:
        batch_limit = min(_PAGE_SIZE, remaining) if remaining else _PAGE_SIZE

        def read_page(
            client: spotipy.Spotify, scope: str, _at: int = current_offset, _n: int = batch_limit
        ) -> dict[str, Any]:
            page: dict[str, Any] = spotify_api.playlist_items(
                client, scope, playlist_id, limit=_n, offset=_at
            )
            return page or {}

        result = await run_tool(ctx, read_page)
        items = result.get("items") or []
        if not items:
            break

        # Restricted-regime entries key the track off `item`, legacy off `track`.
        batch = [
            parse_track(track)
            for entry in items
            if entry and (track := (entry.get("item") or entry.get("track")))
        ]
        tracks.extend(batch)

        await ctx.report_progress(progress=len(tracks), total=total_tracks)
        await ctx.info(f"Fetched {len(tracks)} tracks so far")

        if remaining:
            remaining -= len(batch)
            if remaining <= 0:
                break

        if len(items) < batch_limit or not result.get("next"):
            break

        current_offset += len(items)
        if current_offset > _MAX_OFFSET:
            logger.warning("Safety limit reached: stopping at offset %d", current_offset)
            break

    if total_tracks is None:
        total_tracks = len(tracks)

    log_pagination_info("get_playlist_tracks", total_tracks, limit, offset)

    return PlaylistTracks(
        items=tracks,
        total=total_tracks,
        limit=limit,
        offset=offset,
        returned=len(tracks),
    )


@mcp.tool(
    title="Create Playlist",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def create_playlist(
    name: str,
    description: str = "",
    public: bool = True,
    ctx: Context | None = None,
) -> Playlist:
    """Create a new, empty playlist for the signed-in user.

    Args:
        name: Playlist name
        description: Playlist description (default: empty)
        public: Whether playlist is public (default: True)

    Returns:
        The newly created Playlist. Add tracks with add_tracks_to_playlist.

    Note: Spotify may report a newly created playlist as public even when created
    private; that is Spotify's reporting, not a failed write.
    """

    def work(client: spotipy.Spotify, scope: str) -> Playlist:
        result = spotify_api.create_playlist(client, scope, name, description, public)
        owner = result.get("owner") or {}
        return Playlist(
            id=result["id"],
            name=result["name"],
            owner=owner.get("display_name"),
            description=result.get("description"),
            tracks=[],
            total_tracks=0,
            public=result.get("public"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Edit Playlist Details",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def modify_playlist_details(
    playlist_id: str,
    name: str | None = None,
    description: str | None = None,
    public: bool | None = None,
    ctx: Context | None = None,
) -> ActionResult:
    """Change a playlist's name, description and/or public visibility.

    Args:
        playlist_id: Playlist ID
        name: New name (omit to leave unchanged)
        description: New description (omit to leave unchanged)
        public: New public visibility (omit to leave unchanged)
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        if name is None and description is None and public is None:
            raise ValueError(
                "At least one of name, description, or public must be provided"
            )

        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if description is not None:
            fields["description"] = description
        if public is not None:
            fields["public"] = public

        client.playlist_change_details(playlist_id, **fields)
        return ActionResult(status="success", message="Playlist details updated successfully")

    return await run_tool(ctx, work)


@mcp.tool(
    title="Add Tracks to Playlist",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def add_tracks_to_playlist(
    playlist_id: str, track_uris: list[str], ctx: Context | None = None
) -> ActionResult:
    """Add tracks to a playlist.

    Args:
        playlist_id: Playlist ID
        track_uris: Track IDs or URIs to add (up to 100)
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        uris = [to_uri("track", t) for t in track_uris]
        result = spotify_api.playlist_add_items(client, scope, playlist_id, uris)
        return ActionResult(
            status="success",
            message=f"Added {len(uris)} tracks to playlist",
            snapshot_id=(result or {}).get("snapshot_id"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Remove Tracks from Playlist",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def remove_tracks_from_playlist(
    playlist_id: str, track_uris: list[str], ctx: Context | None = None
) -> ActionResult:
    """Remove tracks from a playlist.

    Args:
        playlist_id: Playlist ID
        track_uris: Track IDs or URIs to remove
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        uris = [to_uri("track", t) for t in track_uris]
        result = spotify_api.playlist_remove_items(client, scope, playlist_id, uris)
        return ActionResult(
            status="success",
            message=f"Removed {len(uris)} tracks from playlist",
            snapshot_id=(result or {}).get("snapshot_id"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Reorder Playlist Tracks",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def reorder_playlist_tracks(
    playlist_id: str,
    range_start: int,
    insert_before: int,
    range_length: int = 1,
    snapshot_id: str | None = None,
    ctx: Context | None = None,
) -> ActionResult:
    """Reorder a range of tracks within a playlist.

    Args:
        playlist_id: Playlist ID
        range_start: Zero-based position of the first track to move
        insert_before: Zero-based position to insert the moved tracks before.
            Pass the playlist's total track count to move the block to the end.
        range_length: Number of tracks to move starting at range_start (default 1)
        snapshot_id: Playlist snapshot ID to apply the change against (optional)

    Returns:
        ActionResult with the new snapshot_id

    Note: Positions come from get_playlist_tracks.
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        if range_start < 0 or insert_before < 0:
            raise ValueError("range_start and insert_before must be >= 0")
        if range_length < 1:
            raise ValueError("range_length must be >= 1")

        result = spotify_api.playlist_reorder_items(
            client,
            scope,
            playlist_id,
            range_start=range_start,
            insert_before=insert_before,
            range_length=range_length,
            snapshot_id=snapshot_id,
        )
        return ActionResult(
            status="success",
            message=(
                f"Moved {range_length} track(s) from position {range_start} "
                f"to before position {insert_before}"
            ),
            snapshot_id=(result or {}).get("snapshot_id"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Unfollow Playlist",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def unfollow_playlist(playlist_id: str, ctx: Context | None = None) -> ActionResult:
    """Unfollow (remove from the user's library) a playlist.

    For playlists the user owns this is how Spotify deletes them — there is no
    separate delete endpoint.

    Args:
        playlist_id: Playlist ID
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        pid = to_id(playlist_id)
        client.current_user_unfollow_playlist(pid)
        return ActionResult(status="success", message="Playlist unfollowed/deleted")

    return await run_tool(ctx, work)
