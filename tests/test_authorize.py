from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from spotify_mcp_mx.authorize import SCOPES, build_authorize_url, exchange_code


def test_scope_list_covers_every_capability() -> None:
    assert len(SCOPES) == 16
    for required in (
        "user-read-playback-state",
        "user-modify-playback-state",
        "playlist-modify-private",
        "playlist-modify-public",
        "user-library-modify",
        "user-top-read",
        "user-read-recently-played",
    ):
        assert required in SCOPES


def test_authorize_url_requests_a_code_with_every_scope() -> None:
    url = build_authorize_url("id-1", "http://127.0.0.1:8888", "state-1")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.spotify.com"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["id-1"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8888"]
    assert query["state"] == ["state-1"]
    assert set(query["scope"][0].split()) == set(SCOPES)


def test_exchange_code_returns_the_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"refresh_token": "RT-1", "access_token": "AT-1"}

    monkeypatch.setattr("spotify_mcp_mx.authorize.requests.post", lambda *a, **k: Response())
    assert exchange_code("id", "secret", "http://127.0.0.1:8888", "code-1") == "RT-1"


def test_exchange_code_raises_on_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 400

        @staticmethod
        def json() -> dict[str, Any]:
            return {"error": "invalid_grant"}

    monkeypatch.setattr("spotify_mcp_mx.authorize.requests.post", lambda *a, **k: Response())
    with pytest.raises(SystemExit):
        exchange_code("id", "secret", "http://127.0.0.1:8888", "bad")
