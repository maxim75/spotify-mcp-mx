from __future__ import annotations

import hashlib
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
    spotify_for,
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
    # Bearer callers have no client id, but they still must not collide with
    # one another in anything keyed on cache_scope (see the regime memo in
    # spotify_api) — so this is an opaque per-token digest, not "".
    assert creds.cache_scope != ""
    assert creds.cache_scope == hashlib.sha256(b"AT-123").hexdigest()[:16]


def test_bearer_cache_scope_differs_per_token() -> None:
    alice = credentials_from_headers({"Authorization": "Bearer AT-alice"})
    bob = credentials_from_headers({"Authorization": "Bearer AT-bob"})
    assert alice.cache_scope != bob.cache_scope
    assert "AT-alice" not in alice.cache_scope
    assert "AT-bob" not in bob.cache_scope


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


def test_cache_key_differs_when_only_the_secret_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A right id + refresh token but wrong secret must never hit a cache entry
    warmed by the correctly-authenticated caller — that would skip client
    authentication entirely for the life of the entry."""
    from spotify_mcp_mx.auth import _TOKEN_CACHE

    tokens = iter(["AT-correct", "AT-should-not-reuse"])
    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(200, {"access_token": next(tokens), "expires_in": 3600}),
    )
    correct = credentials_from_headers(FULL)
    wrong_secret = credentials_from_headers({**FULL, CLIENT_SECRET_HEADER: "wrong-secret"})

    assert access_token_for(correct) == "AT-correct"
    assert access_token_for(wrong_secret) == "AT-should-not-reuse"
    assert len(_TOKEN_CACHE) == 2


# --- spotify_for ------------------------------------------------------------

def test_spotify_for_yields_client_id_scope_for_three_header_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "spotify_mcp_mx.auth._post_token",
        lambda *a, **k: FakeResponse(200, {"access_token": "AT", "expires_in": 3600}),
    )
    with spotify_for(FULL) as (_client, scope):
        assert scope == "id-1"


def test_spotify_for_yields_opaque_scope_for_bearer_form() -> None:
    with spotify_for({"Authorization": "Bearer AT-1"}) as (_client, scope):
        assert scope == hashlib.sha256(b"AT-1").hexdigest()[:16]


def test_spotify_for_client_session_carries_the_shared_retry() -> None:
    from spotify_mcp_mx.auth import RETRY_STATUS_CODES

    with spotify_for({"Authorization": "Bearer AT-1"}) as (client, _scope):
        adapter = client._session.get_adapter("https://api.spotify.com/v1/me")
        assert set(adapter.max_retries.status_forcelist) == set(RETRY_STATUS_CODES)
        assert adapter.max_retries.total == 3
        assert 429 not in adapter.max_retries.status_forcelist


def test_spotify_for_client_has_a_request_timeout() -> None:
    """A hung api.spotify.com socket must not block its worker thread forever:
    anyio.to_thread.run_sync is non-cancellable and its default limiter caps
    the pool at 40 threads, so unbounded calls could exhaust it for every
    caller."""
    with spotify_for({"Authorization": "Bearer AT-1"}) as (client, _scope):
        assert client.requests_timeout == 10


def test_shared_pool_never_retries_a_post() -> None:
    """spotipy issues POST for genuine writes (queue, playlist adds, create
    playlist). Retrying one after a 5xx that Spotify already actioned would
    duplicate the write, so POST must stay off the pool every spotipy client
    shares — only the separate token-exchange pool may retry POST."""
    from spotify_mcp_mx.auth import _SHARED_POOL

    allowed = _SHARED_POOL.max_retries.allowed_methods
    assert "POST" not in allowed
    assert "GET" in allowed


def test_shared_pool_never_retries_a_put() -> None:
    """playlist_reorder_items issues a PUT and is not idempotent: replaying it
    after a 5xx that Spotify already actioned moves a different block of
    tracks and can scramble the playlist. save_tracks also PUTs and is
    idempotent, but one non-idempotent, user-data-corrupting write outweighs
    retry coverage on an idempotent one, so PUT must stay off the whole
    shared pool."""
    from spotify_mcp_mx.auth import _SHARED_POOL

    allowed = _SHARED_POOL.max_retries.allowed_methods
    assert "PUT" not in allowed
    assert "GET" in allowed
    assert "DELETE" in allowed


def test_token_pool_retries_post() -> None:
    """The refresh-token exchange is safely repeatable, so its own pool (never
    shared with spotipy's writes) is allowed to retry POST."""
    from spotify_mcp_mx.auth import _TOKEN_POOL

    assert "POST" in _TOKEN_POOL.max_retries.allowed_methods


def test_spotify_for_never_constructs_a_spotify_oauth() -> None:
    with spotify_for({"Authorization": "Bearer AT-1"}) as (client, _scope):
        # No SpotifyOAuth (or any auth manager) anywhere: the access token was
        # handed to spotipy directly via `auth=`, never via a manager that
        # could fall back to its own on-disk token cache.
        assert client.auth_manager is None
        assert client.oauth_manager is None
        assert client.client_credentials_manager is None
        assert client._auth == "AT-1"
