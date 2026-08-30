from __future__ import annotations

from typing import Any

import pytest
from spotipy import SpotifyException

from spotify_mcp_mx.spotify_api import reset_regime_memo, with_fallback


@pytest.fixture(autouse=True)
def _clear_memo() -> None:
    reset_regime_memo()


def _miss(status: int = 404) -> SpotifyException:
    return SpotifyException(status, -1, "not served for this app")


def test_restricted_shape_is_tried_first() -> None:
    calls: list[str] = []
    result = with_fallback(
        "app-a",
        "playlist-items",
        lambda: (calls.append("restricted"), "R")[1],
        lambda: (calls.append("legacy"), "L")[1],
    )
    assert result == "R"
    assert calls == ["restricted"]


@pytest.mark.parametrize("status", [400, 404, 405, 410])
def test_regime_miss_statuses_fall_back(status: int) -> None:
    def restricted() -> str:
        raise _miss(status)

    assert with_fallback("app-a", "playlist-items", restricted, lambda: "L") == "L"


def test_other_statuses_propagate() -> None:
    def restricted() -> str:
        raise _miss(503)

    with pytest.raises(SpotifyException):
        with_fallback("app-a", "playlist-items", restricted, lambda: "L")


def test_answer_is_memoised_so_the_restricted_path_is_not_retried() -> None:
    attempts = {"n": 0}

    def restricted() -> str:
        attempts["n"] += 1
        raise _miss()

    for _ in range(3):
        assert with_fallback("app-a", "playlist-items", restricted, lambda: "L") == "L"
    assert attempts["n"] == 1


def test_memo_is_not_written_when_the_legacy_shape_also_fails() -> None:
    # A genuine not-found fails both ways; it must not pin the app to legacy.
    attempts = {"n": 0}

    def restricted() -> str:
        attempts["n"] += 1
        raise _miss()

    def legacy() -> str:
        raise _miss()

    for _ in range(2):
        with pytest.raises(SpotifyException):
            with_fallback("app-a", "playlist-items", restricted, legacy)
    assert attempts["n"] == 2


def test_one_callers_regime_never_pins_another() -> None:
    """The multi-tenancy fix: app-a is legacy, app-b must still try restricted."""

    def restricted_fails() -> str:
        raise _miss()

    with_fallback("app-a", "playlist-items", restricted_fails, lambda: "L")

    tried: list[str] = []
    result = with_fallback(
        "app-b",
        "playlist-items",
        lambda: (tried.append("restricted"), "R")[1],
        lambda: (tried.append("legacy"), "L")[1],
    )
    assert result == "R"
    assert tried == ["restricted"]


def test_families_are_memoised_independently() -> None:
    def restricted_fails() -> str:
        raise _miss()

    with_fallback("app-a", "playlist-items", restricted_fails, lambda: "L")

    tried: list[str] = []
    with_fallback(
        "app-a",
        "library-write",
        lambda: (tried.append("restricted"), "R")[1],
        lambda: "L",
    )
    assert tried == ["restricted"]


def test_memo_is_bounded() -> None:
    from spotify_mcp_mx.spotify_api import _LEGACY_FAMILIES, MAX_MEMOISED_SCOPES

    def restricted_fails() -> str:
        raise _miss()

    for i in range(MAX_MEMOISED_SCOPES + 25):
        with_fallback(f"app-{i}", "playlist-items", restricted_fails, lambda: "L")
    assert len(_LEGACY_FAMILIES) <= MAX_MEMOISED_SCOPES


class FakeSpotify:
    """Records the private-method calls the regime helpers make."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("GET", path, kwargs))
        return {"items": []}

    def _post(self, path: str, payload: Any = None) -> dict[str, Any]:
        self.calls.append(("POST", path, payload))
        return {"snapshot_id": "snap"}

    def _put(self, path: str, payload: Any = None) -> dict[str, Any]:
        self.calls.append(("PUT", path, payload))
        return {"snapshot_id": "snap"}

    def _delete(self, path: str, payload: Any = None) -> dict[str, Any]:
        self.calls.append(("DELETE", path, payload))
        return {"snapshot_id": "snap"}


def test_playlist_items_uses_the_restricted_items_path() -> None:
    from spotify_mcp_mx.spotify_api import playlist_items

    sp = FakeSpotify()
    playlist_items(sp, "app-a", "spotify:playlist:37i9", limit=50, offset=0)
    assert sp.calls[0][1] == "playlists/37i9/items"


def test_playlist_remove_items_keys_the_body_off_items() -> None:
    from spotify_mcp_mx.spotify_api import playlist_remove_items

    sp = FakeSpotify()
    playlist_remove_items(sp, "app-a", "37i9", ["spotify:track:abc"])
    method, path, payload = sp.calls[0]
    assert method == "DELETE"
    assert path == "playlists/37i9/items"
    assert payload == {"items": [{"uri": "spotify:track:abc"}]}


def test_save_tracks_sends_uris_to_the_library_endpoint() -> None:
    from spotify_mcp_mx.spotify_api import save_tracks

    sp = FakeSpotify()
    save_tracks(sp, "app-a", ["abc", "spotify:track:def"])
    method, path, payload = sp.calls[0]
    assert (method, path) == ("PUT", "me/library")
    assert payload == {"uris": ["spotify:track:abc", "spotify:track:def"]}
