"""Real-shaped Spotify API payloads, trimmed to the fields the code reads."""

from __future__ import annotations

from typing import Any

TRACK: dict[str, Any] = {
    "name": "Idioteque",
    "id": "6bMDnAdV1bhrbmwmuHRk9c",
    "duration_ms": 289000,
    "popularity": 62,
    "external_urls": {"spotify": "https://open.spotify.com/track/6bMDnAdV1bhrbmwmuHRk9c"},
    "artists": [{"name": "Radiohead", "id": "4Z8W4fKeB5YxbusRsdQVPb"}],
    "album": {"name": "Kid A", "id": "6GjwtEZcfenmOf6l18N7T7", "release_date": "2000-10-02"},
}

ARTIST: dict[str, Any] = {
    "name": "Radiohead",
    "id": "4Z8W4fKeB5YxbusRsdQVPb",
    "genres": ["art rock", "oxford indie"],
    "popularity": 79,
    "followers": {"total": 9_500_000},
}

ALBUM: dict[str, Any] = {
    "name": "Kid A",
    "id": "6GjwtEZcfenmOf6l18N7T7",
    "artists": [{"name": "Radiohead", "id": "4Z8W4fKeB5YxbusRsdQVPb"}],
    "release_date": "2000-10-02",
    "release_date_precision": "day",
    "total_tracks": 10,
    "album_type": "album",
    "label": "XL Recordings",
    "genres": [],
    "popularity": 74,
    "external_urls": {"spotify": "https://open.spotify.com/album/6GjwtEZcfenmOf6l18N7T7"},
    "tracks": {
        "items": [
            {
                "name": "Everything in Its Right Place",
                "id": "0WrxwPMTaEAJ8QOAKMBKBz",
                "duration_ms": 251000,
                "artists": [{"name": "Radiohead", "id": "4Z8W4fKeB5YxbusRsdQVPb"}],
            }
        ]
    },
}

PLAYLIST: dict[str, Any] = {
    "name": "Late Night",
    "id": "37i9dQZF1DX4sWSpwq3LiO",
    "description": "after midnight",
    "public": False,
    "owner": {"display_name": "maksym", "id": "maksym"},
    "tracks": {"total": 148},
}
