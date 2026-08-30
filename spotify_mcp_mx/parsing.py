"""Spotify API payloads → response models.

spotipy returns untyped dicts. Everything the tools read passes through here so
missing optional fields degrade to None in one place rather than 25.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from .models import Album, Artist, Playlist, Track

if TYPE_CHECKING:
    from .spotify_types import AlbumObject, ArtistObject, PlaylistObject, TrackObject

__all__ = ["parse_album", "parse_artist", "parse_playlist", "parse_track"]


def parse_track(item: TrackObject) -> Track:
    """Parse Spotify track data into a Track."""
    album_data: dict[str, Any] = cast("dict[str, Any]", item.get("album") or {})
    artists = item.get("artists") or []
    return Track(
        name=item["name"],
        id=item["id"],
        artist=artists[0]["name"] if artists else "Unknown",
        artists=[a["name"] for a in artists],
        album=album_data.get("name"),
        album_id=album_data.get("id"),
        release_date=album_data.get("release_date"),
        duration_ms=item.get("duration_ms"),
        popularity=item.get("popularity"),
        external_urls=cast("dict[str, str] | None", item.get("external_urls")),
    )


def parse_artist(item: ArtistObject) -> Artist:
    """Parse Spotify artist data into an Artist."""
    followers = item.get("followers") or {}
    return Artist(
        name=item["name"],
        id=item["id"],
        genres=item.get("genres", []),
        popularity=item.get("popularity"),
        followers=followers.get("total"),
    )


def parse_album(item: AlbumObject) -> Album:
    """Parse Spotify album metadata into an Album (without its track list)."""
    artists = item.get("artists") or []
    return Album(
        name=item["name"],
        id=item["id"],
        artist=artists[0]["name"] if artists else "Unknown",
        artists=[a["name"] for a in artists],
        release_date=item.get("release_date"),
        release_date_precision=item.get("release_date_precision"),
        total_tracks=item.get("total_tracks"),
        album_type=item.get("album_type"),
        label=item.get("label"),
        genres=item.get("genres", []),
        popularity=item.get("popularity"),
        external_urls=cast("dict[str, str] | None", item.get("external_urls")),
    )


def parse_playlist(
    item: PlaylistObject, *, tracks: list[Track] | None = None
) -> Playlist:
    """Parse Spotify playlist metadata into a Playlist."""
    owner = item.get("owner") or {}
    tracks_meta = item.get("tracks") or {}
    return Playlist(
        name=item["name"],
        id=item["id"],
        owner=owner.get("display_name"),
        description=item.get("description"),
        tracks=tracks,
        total_tracks=tracks_meta.get("total"),
        public=item.get("public"),
    )
