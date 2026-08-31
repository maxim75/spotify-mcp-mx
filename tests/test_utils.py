from __future__ import annotations

import pytest

from spotify_mcp_mx.utils import to_id, to_uri


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("6rqhFgbbKwnb9MLmUQDhG6", "6rqhFgbbKwnb9MLmUQDhG6"),
        ("spotify:track:6rqhFgbbKwnb9MLmUQDhG6", "6rqhFgbbKwnb9MLmUQDhG6"),
        ("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6", "6rqhFgbbKwnb9MLmUQDhG6"),
        ("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6?si=abc", "6rqhFgbbKwnb9MLmUQDhG6"),
        ("  6rqhFgbbKwnb9MLmUQDhG6  ", "6rqhFgbbKwnb9MLmUQDhG6"),
    ],
)
def test_to_id_accepts_every_reference_form(value: str, expected: str) -> None:
    assert to_id(value) == expected


def test_to_uri_builds_from_any_form() -> None:
    assert to_uri("track", "6rqhFgbbKwnb9MLmUQDhG6") == "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"
    assert to_uri("track", "spotify:track:6rq") == "spotify:track:6rq"
    assert to_uri("playlist", "https://open.spotify.com/playlist/37i9") == "spotify:playlist:37i9"
