from __future__ import annotations

import copy

from spotify_mcp_mx.parsing import parse_album, parse_artist, parse_playlist, parse_track
from tests.fixtures import ALBUM, ARTIST, PLAYLIST, TRACK


def test_parse_track_flattens_the_primary_artist_and_album() -> None:
    t = parse_track(copy.deepcopy(TRACK))
    assert t.name == "Idioteque"
    assert t.artist == "Radiohead"
    assert t.artists == ["Radiohead"]
    assert t.album == "Kid A"
    assert t.album_id == "6GjwtEZcfenmOf6l18N7T7"
    assert t.release_date == "2000-10-02"
    assert t.duration_ms == 289000


def test_parse_track_survives_a_missing_album() -> None:
    payload = copy.deepcopy(TRACK)
    del payload["album"]
    t = parse_track(payload)
    assert t.album is None
    assert t.album_id is None


def test_parse_track_labels_an_artistless_track_unknown() -> None:
    payload = copy.deepcopy(TRACK)
    payload["artists"] = []
    assert parse_track(payload).artist == "Unknown"


def test_parse_artist_reads_follower_total() -> None:
    a = parse_artist(copy.deepcopy(ARTIST))
    assert a.followers == 9_500_000
    assert a.genres == ["art rock", "oxford indie"]


def test_parse_artist_survives_missing_followers() -> None:
    payload = copy.deepcopy(ARTIST)
    del payload["followers"]
    assert parse_artist(payload).followers is None


def test_parse_album_reads_label_and_precision() -> None:
    a = parse_album(copy.deepcopy(ALBUM))
    assert a.label == "XL Recordings"
    assert a.release_date_precision == "day"
    assert a.artist == "Radiohead"


def test_parse_playlist_reads_owner_display_name_and_total() -> None:
    p = parse_playlist(copy.deepcopy(PLAYLIST))
    assert p.owner == "maksym"
    assert p.total_tracks == 148
    assert p.public is False
    assert p.tracks is None
