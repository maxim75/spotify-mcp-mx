"""Pydantic response models. These are the tools' structured output schemas.

Field names, types and optionality mirror jamiew/spotify-mcp exactly so a client
written against that server sees the same shapes here.
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "Track",
    "PlaybackState",
    "Playlist",
    "Artist",
    "Album",
    "SearchResults",
    "QueueState",
    "TrackList",
    "ArtistInfo",
    "AlbumInfo",
    "PlaylistList",
    "PlaylistTracks",
    "SavedTracks",
    "Device",
    "DeviceList",
    "UserProfile",
    "TopItems",
    "RecentlyPlayed",
    "ActionResult",
]


class Track(BaseModel):
    """A Spotify track with metadata."""

    name: str
    id: str
    artist: str
    artists: list[str] | None = None
    album: str | None = None
    album_id: str | None = None
    release_date: str | None = None
    duration_ms: int | None = None
    popularity: int | None = None
    external_urls: dict[str, str] | None = None
    added_at: str | None = None
    played_at: str | None = None


class PlaybackState(BaseModel):
    """Current playback state."""

    is_playing: bool
    track: Track | None = None
    device: str | None = None
    volume: int | None = None
    shuffle: bool = False
    repeat: str = "off"
    progress_ms: int | None = None


class Playlist(BaseModel):
    """A Spotify playlist."""

    name: str
    id: str
    owner: str | None = None
    description: str | None = None
    tracks: list[Track] | None = None
    total_tracks: int | None = None
    public: bool | None = None


class Artist(BaseModel):
    """A Spotify artist."""

    name: str
    id: str
    genres: list[str] | None = None
    popularity: int | None = None
    followers: int | None = None


class Album(BaseModel):
    """A Spotify album."""

    name: str
    id: str
    artist: str
    artists: list[str] | None = None
    release_date: str | None = None
    release_date_precision: str | None = None
    total_tracks: int | None = None
    album_type: str | None = None
    label: str | None = None
    genres: list[str] | None = None
    popularity: int | None = None
    external_urls: dict[str, str] | None = None


class SearchResults(BaseModel):
    """Paginated search results."""

    items: list[Track]
    total: int
    limit: int
    offset: int
    next: str | None = None
    previous: str | None = None


class QueueState(BaseModel):
    """Currently playing track plus the upcoming queue."""

    currently_playing: Track | None = None
    queue: list[Track]


class TrackList(BaseModel):
    """A list of tracks."""

    tracks: list[Track]


class ArtistInfo(BaseModel):
    """An artist with their top tracks."""

    artist: Artist
    top_tracks: list[Track]


class AlbumInfo(BaseModel):
    """An album with its tracks."""

    album: Album
    tracks: list[Track]


class PlaylistList(BaseModel):
    """Paginated list of playlists."""

    items: list[Playlist]
    total: int
    limit: int
    offset: int
    next: str | None = None
    previous: str | None = None


class PlaylistTracks(BaseModel):
    """Paginated tracks from a single playlist."""

    items: list[Track]
    total: int
    limit: int | None = None
    offset: int
    returned: int


class SavedTracks(BaseModel):
    """Paginated saved/liked tracks."""

    items: list[Track]
    total: int
    limit: int
    offset: int
    next: str | None = None
    previous: str | None = None


class Device(BaseModel):
    """A Spotify Connect device."""

    id: str | None = None
    name: str
    type: str | None = None
    is_active: bool = False
    volume_percent: int | None = None


class DeviceList(BaseModel):
    """The user's available devices."""

    devices: list[Device]


class UserProfile(BaseModel):
    """The signed-in user's profile.

    Everything but `id` is optional: Spotify's restricted regime strips these
    fields rather than erroring, so they must never be required here.
    """

    id: str
    display_name: str | None = None
    email: str | None = None
    country: str | None = None
    product: str | None = None
    followers: int | None = None


class TopItems(BaseModel):
    """The user's top artists or tracks over a time range."""

    time_range: str
    artists: list[Artist] | None = None
    tracks: list[Track] | None = None


class RecentlyPlayed(BaseModel):
    """Recently played tracks, most recent first."""

    items: list[Track]


class ActionResult(BaseModel):
    """Result of a state-changing operation."""

    status: str
    message: str
    snapshot_id: str | None = None
