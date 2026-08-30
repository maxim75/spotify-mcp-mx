"""Catalog lookup tools: search, tracks, artists and albums."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import Context  # noqa: TC002 - the SDK injects by runtime type
from mcp.types import ToolAnnotations

from ..logging_utils import log_tool_execution
from ..models import AlbumInfo, ArtistInfo, SearchResults, Track, TrackList
from ..parsing import parse_album, parse_artist, parse_track
from ..server import SPOTIFY_ICON, mcp, run_tool

if TYPE_CHECKING:
    import spotipy


@mcp.tool(
    title="Search Spotify",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def search_music(
    query: str,
    qtype: str = "track",
    limit: int = 10,
    offset: int = 0,
    year: str | None = None,
    year_range: str | None = None,
    genre: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    ctx: Context | None = None,
) -> SearchResults:
    """Search Spotify for tracks, albums, artists, or playlists.

    Args:
        query: Search query
        qtype: Type ('track', 'album', 'artist', 'playlist')
        limit: Max results per page (1-50, default 10)
        offset: Number of results to skip for pagination (default 0)
        year: Filter by year (e.g., '2024')
        year_range: Filter by year range (e.g., '2020-2024')
        genre: Filter by genre (e.g., 'electronic', 'hip-hop')
        artist: Filter by artist name
        album: Filter by album name

    Returns:
        SearchResults with 'items' (list of tracks) and pagination info ('total', 'limit', 'offset')

    Note: Filters use Spotify's search syntax. For large result sets, use offset to paginate.
    Example: query='love', year='2024', genre='pop' searches for 'love year:2024 genre:pop'
    """

    def work(client: spotipy.Spotify, scope: str) -> SearchResults:
        clamped_limit = max(1, min(50, limit))

        # Build filtered query
        filters = []
        if artist:
            filters.append(f"artist:{artist}")
        if album:
            filters.append(f"album:{album}")
        if year:
            filters.append(f"year:{year}")
        if year_range:
            filters.append(f"year:{year_range}")
        if genre:
            filters.append(f"genre:{genre}")

        full_query = " ".join([query] + filters) if filters else query

        result = client.search(q=full_query, type=qtype, limit=clamped_limit, offset=offset)

        tracks = []
        items_key = f"{qtype}s"
        result_section = result.get(items_key, {})
        # Spotify can return null entries in items (e.g. removed content), so guard each.
        if qtype == "track" and result_section.get("items"):
            tracks = [parse_track(item) for item in result_section["items"] if item]
        elif result_section.get("items"):
            # Convert other types to track-like format for consistency
            for item in result_section["items"]:
                if not item:
                    continue
                track = Track(
                    name=item["name"],
                    id=item["id"],
                    artist=(
                        item.get("artists", [{}])[0].get("name", "Unknown")
                        if qtype != "artist"
                        else item["name"]
                    ),
                    external_urls=item.get("external_urls"),
                )
                tracks.append(track)

        total_results = result_section.get("total", 0)

        return SearchResults(
            items=tracks,
            total=total_results,
            limit=result_section.get("limit", clamped_limit),
            offset=result_section.get("offset", offset),
            next=result_section.get("next"),
            previous=result_section.get("previous"),
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Get Track Info",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_track_info(track_ids: str | list[str], ctx: Context | None = None) -> TrackList:
    """Get detailed information about one or more Spotify tracks.

    Args:
        track_ids: Single track ID or list of track IDs (up to 50)

    Returns:
        TrackList with 'tracks' containing track metadata including release_date.
        For single ID, returns {'tracks': [track]}.

    Note: Batch lookup is much more efficient - 50 tracks = 1 API call instead of 50.
    """

    def work(client: spotipy.Spotify, scope: str) -> TrackList:
        ids = [track_ids] if isinstance(track_ids, str) else track_ids

        if len(ids) > 50:
            raise ValueError("Maximum 50 track IDs per request (Spotify API limit)")

        if len(ids) == 1:
            result = client.track(ids[0])
            tracks = [parse_track(result)]
        else:
            result = client.tracks(ids)
            tracks = [parse_track(item) for item in result.get("tracks", []) if item]

        return TrackList(tracks=tracks)

    return await run_tool(ctx, work)


@mcp.tool(
    title="Get Artist Info",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_artist_info(artist_id: str, ctx: Context | None = None) -> ArtistInfo:
    """Get detailed information about a Spotify artist.

    Args:
        artist_id: Spotify artist ID
    Returns:
        ArtistInfo with the artist and their top tracks
    """

    def work(client: spotipy.Spotify, scope: str) -> ArtistInfo:
        result = client.artist(artist_id)
        top_tracks = client.artist_top_tracks(artist_id)

        artist = parse_artist(result)
        tracks = [parse_track(track) for track in top_tracks.get("tracks", [])[:10]]

        return ArtistInfo(artist=artist, top_tracks=tracks)

    return await run_tool(ctx, work)


@mcp.tool(
    title="Get Album Info",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_album_info(album_id: str, ctx: Context | None = None) -> AlbumInfo:
    """Get detailed information about a Spotify album.

    Args:
        album_id: Spotify album ID

    Returns:
        AlbumInfo with album metadata (release_date, label) and its tracks
    """

    def work(client: spotipy.Spotify, scope: str) -> AlbumInfo:
        result = client.album(album_id)

        album = parse_album(result)

        # Parse album tracks
        tracks = []
        album_tracks = result.get("tracks") or {}
        for item in album_tracks.get("items", []):
            if item:
                # Album track items don't have album info, add it
                item["album"] = {
                    "name": result["name"],
                    "id": result["id"],
                    "release_date": result.get("release_date"),
                }
                tracks.append(parse_track(item))

        return AlbumInfo(album=album, tracks=tracks)

    return await run_tool(ctx, work)
