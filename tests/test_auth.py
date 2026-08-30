from __future__ import annotations

import time
from typing import Any

import pytest

from spotify_mcp_mx.auth import (
    CLIENT_ID_HEADER,
    CLIENT_SECRET_HEADER,
    REFRESH_TOKEN_HEADER,
    Credentials,
    access_token_for,
    credentials_from_headers,
    reset_token_cache,
)
from spotify_mcp_mx.errors import MissingCredentialsError, TokenRefreshError

FULL = {
    CLIENT_ID_HEADER: "id-1",
    CLIENT_SECRET_HEADER: "secret-1",
    REFRESH_TOKEN_HEADER: "refresh-1",
}


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_token_cache()


# --- header parsing -------------------------------------------------------

def test_reads_the_three_credential_headers() -> None:
    creds = credentials_from_headers(FULL)
    assert creds.client_id == "id-1"
    assert creds.client_secret == "secret-1"
    assert creds.refresh_token == "refresh-1"
    assert creds.access_token is None
    assert creds.cache_scope == "id-1"


def test_header_lookup_is_case_insensitive() -> None:
    creds = credentials_from_headers({k.lower(): v for k, v in FULL.items()})
    assert creds.client_id == "id-1"


def test_bearer_fallback_is_accepted() -> None:
    creds = credentials_from_headers({"Authorization": "Bearer AT-123"})
    assert creds.access_token == "AT-123"
    assert creds.cache_scope == ""


def test_bearer_scheme_is_case_insensitive_and_trimmed() -> None:
    assert credentials_from_headers({"authorization": "bearer  AT-9 "}).access_token == "AT-9"


def test_three_header_form_wins_over_bearer() -> None:
    creds = credentials_from_headers({**FULL, "Authorization": "Bearer AT-123"})
    assert creds.access_token is None
    assert creds.refresh_token == "refresh-1"


def test_blank_values_count_as_absent() -> None:
    with pytest.raises(MissingCredentialsError):
        credentials_from_headers({**FULL, REFRESH_TOKEN_HEADER: "   "})


def test_no_headers_at_all_raises() -> None:
    with pytest.raises(MissingCredentialsError):
        credentials_from_headers(None)


def test_error_names_the_headers_and_never_echoes_a_value() -> None:
    with pytest.raises(MissingCredentialsError) as excinfo:
        credentials_from_headers({CLIENT_ID_HEADER: "super-secret-value"})
    message = str(excinfo.value)
    assert CLIENT_SECRET_HEADER in message
    assert REFRESH_TOKEN_HEADER in message
    assert "super-secret-value" not in message


# --- token exchange -------------------------------------------------------

class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def test_exchange_returns_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, {"access_token": "AT-fresh", "expires_in": 3600})

    monkeypatch.setattr("spotify_mcp_mx.auth._post_token", fake_post)
    assert access_token_for(credentials_from_headers(FULL)) == "AT-fresh"
    assert calls[0]["url"] == "https://accounts.spotify.com/api/token"
    assert calls[0]["data"]["grant_type"] == "refresh_token"
    assert calls[0]["auth"] == ("id-1", "secret-1")


def test_bearer_credentials_skip_the_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*a: Any, **k: Any) -> FakeResponse:
        raise AssertionError("must not exchange when an access token was supplied")

    monkeypatch.setattr("spotify_mcp_mx.auth._post_token", explode)
    assert access_token_for(credentials_from_headers({"Authorization": "Bearer AT-1"})) == "AT-1"


def test_rejected_exchange_raises_without_leaking_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(400, {"error": "invalid_grant"}),
    )
    with pytest.raises(TokenRefreshError) as excinfo:
        access_token_for(credentials_from_headers(FULL))
    assert "invalid_grant" in str(excinfo.value)
    assert "secret-1" not in str(excinfo.value)
    assert "refresh-1" not in str(excinfo.value)


# --- cache ----------------------------------------------------------------

def test_second_call_is_served_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    hits = {"n": 0}

    def fake_post(*a: Any, **k: Any) -> FakeResponse:
        hits["n"] += 1
        return FakeResponse(200, {"access_token": f"AT-{hits['n']}", "expires_in": 3600})

    monkeypatch.setattr("spotify_mcp_mx.auth._post_token", fake_post)
    creds = credentials_from_headers(FULL)
    assert access_token_for(creds) == "AT-1"
    assert access_token_for(creds) == "AT-1"
    assert hits["n"] == 1


def test_two_callers_never_share_a_cache_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = iter(["AT-alice", "AT-bob"])
    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(200, {"access_token": next(tokens), "expires_in": 3600}),
    )
    alice = credentials_from_headers(
        {CLIENT_ID_HEADER: "id-a", CLIENT_SECRET_HEADER: "s", REFRESH_TOKEN_HEADER: "r-a"}
    )
    bob = credentials_from_headers(
        {CLIENT_ID_HEADER: "id-b", CLIENT_SECRET_HEADER: "s", REFRESH_TOKEN_HEADER: "r-b"}
    )
    assert access_token_for(alice) == "AT-alice"
    assert access_token_for(bob) == "AT-bob"
    assert access_token_for(alice) == "AT-alice"


def test_expired_entry_is_refetched(monkeypatch: pytest.MonkeyPatch) -> None:
    n = {"i": 0}

    def fake_post(*a: Any, **k: Any) -> FakeResponse:
        n["i"] += 1
        # expires_in below the skew, so the entry is already stale when stored
        return FakeResponse(200, {"access_token": f"AT-{n['i']}", "expires_in": 1})

    monkeypatch.setattr("spotify_mcp_mx.auth._post_token", fake_post)
    creds = credentials_from_headers(FULL)
    assert access_token_for(creds) == "AT-1"
    assert access_token_for(creds) == "AT-2"


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from spotify_mcp_mx.auth import _TOKEN_CACHE, MAX_CACHED_TOKENS

    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(200, {"access_token": "AT", "expires_in": 3600}),
    )
    for i in range(MAX_CACHED_TOKENS + 25):
        access_token_for(
            Credentials(client_id=f"id-{i}", client_secret="s", refresh_token=f"r-{i}")
        )
    assert len(_TOKEN_CACHE) <= MAX_CACHED_TOKENS


def test_cache_key_never_contains_the_raw_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from spotify_mcp_mx.auth import _TOKEN_CACHE

    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(200, {"access_token": "AT", "expires_in": 3600}),
    )
    access_token_for(credentials_from_headers(FULL))
    joined = "".join(_TOKEN_CACHE.keys())
    assert "refresh-1" not in joined
    assert "secret-1" not in joined


def test_cached_entry_stores_an_absolute_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    from spotify_mcp_mx.auth import _TOKEN_CACHE

    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(200, {"access_token": "AT", "expires_in": 3600}),
    )
    access_token_for(credentials_from_headers(FULL))
    (_token, expires_at), = _TOKEN_CACHE.values()
    assert time.monotonic() < expires_at <= time.monotonic() + 3600
