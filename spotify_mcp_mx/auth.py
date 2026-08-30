"""Per-request authentication.

This server holds no Spotify credentials of its own. Every caller supplies their
own on every request, and each tool call gets a freshly built client that is
dropped as soon as the call returns. Keeping clients per-call (rather than
caching one per caller) means one caller's token can never serve another's
request.

``spotipy.oauth2.SpotifyOAuth`` is deliberately unused: its default cache
handler writes a ``.cache`` token file to disk, which is exactly the credential
storage this server must not do. Passing ``auth=<token>`` to ``spotipy.Spotify``
bypasses all of it.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import requests
import spotipy
from requests.adapters import HTTPAdapter

from .errors import MissingCredentialsError, TokenRefreshError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = [
    "CLIENT_ID_HEADER",
    "CLIENT_SECRET_HEADER",
    "REFRESH_TOKEN_HEADER",
    "RETRY_STATUS_CODES",
    "Credentials",
    "access_token_for",
    "credentials_from_headers",
    "reset_token_cache",
    "spotify_for",
]

CLIENT_ID_HEADER = "X-Spotify-Client-Id"
CLIENT_SECRET_HEADER = "X-Spotify-Client-Secret"
REFRESH_TOKEN_HEADER = "X-Spotify-Refresh-Token"

TOKEN_URL = "https://accounts.spotify.com/api/token"  # nosec B105 - a URL, not a secret

# Retry transient server errors but never 429. Since July 2026 Spotify counts
# quota per developer account, so retrying a QUOTA_EXCEEDED 429 burns the pool
# for every app the caller owns; surface it and let them back off.
RETRY_STATUS_CODES = (500, 502, 503, 504)

# Refresh a little early so a token cannot expire in flight.
EXPIRY_SKEW_SECONDS = 60

MAX_CACHED_TOKENS = 512

_MISSING_MESSAGE = (
    f"No Spotify credentials supplied. Send {CLIENT_ID_HEADER}, {CLIENT_SECRET_HEADER} "
    f"and {REFRESH_TOKEN_HEADER} on every request to this server, or an "
    f"'Authorization: Bearer <access token>' header. This server stores no credentials."
)


@dataclass(frozen=True)
class Credentials:
    """One caller's credentials, valid for the lifetime of a single request."""

    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    refresh_token: str = field(default="", repr=False)
    access_token: str | None = field(default=None, repr=False)

    @property
    def cache_scope(self) -> str:
        """Key for anything memoised per Spotify app (see spotify_api regime memo)."""
        return self.client_id


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return (value or "").strip()
    return ""


def credentials_from_headers(headers: Mapping[str, str] | None) -> Credentials:
    """Pull the caller's Spotify credentials out of *headers*.

    Raises:
        MissingCredentialsError: if neither the three-header form nor a bearer
            access token is present. The message names the expected headers and
            never echoes a supplied value.
    """
    headers = headers or {}

    client_id = _header(headers, CLIENT_ID_HEADER)
    client_secret = _header(headers, CLIENT_SECRET_HEADER)
    refresh_token = _header(headers, REFRESH_TOKEN_HEADER)
    if client_id and client_secret and refresh_token:
        return Credentials(
            client_id=client_id, client_secret=client_secret, refresh_token=refresh_token
        )

    authorization = _header(headers, "Authorization")
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return Credentials(access_token=parts[1].strip())

    raise MissingCredentialsError(_MISSING_MESSAGE)


# --- token exchange and cache --------------------------------------------

_TOKEN_CACHE: OrderedDict[str, tuple[str, float]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def reset_token_cache() -> None:
    """Drop every cached access token. Test seam; never called in production."""
    with _CACHE_LOCK:
        _TOKEN_CACHE.clear()


def _cache_key(creds: Credentials) -> str:
    digest = hashlib.sha256()
    digest.update(creds.client_id.encode())
    digest.update(b"\0")
    digest.update(creds.refresh_token.encode())
    return digest.hexdigest()


def _post_token(url: str, **kwargs: Any) -> Any:
    """Seam for tests. Real calls go out over the shared pool."""
    return _pooled_session().post(url, timeout=10, **kwargs)


def _exchange(creds: Credentials) -> tuple[str, float]:
    response = _post_token(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": creds.refresh_token},
        auth=(creds.client_id, creds.client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code != 200 or "access_token" not in payload:
        # Report Spotify's own error words, never the credentials that produced them.
        detail = payload.get("error_description") or payload.get("error") or "unknown error"
        raise TokenRefreshError(
            f"Spotify rejected the refresh token ({response.status_code}): {detail}. "
            f"Check {CLIENT_ID_HEADER}, {CLIENT_SECRET_HEADER} and {REFRESH_TOKEN_HEADER}."
        )

    expires_in = int(payload.get("expires_in", 3600))
    return payload["access_token"], time.monotonic() + expires_in - EXPIRY_SKEW_SECONDS


def access_token_for(creds: Credentials) -> str:
    """Return a usable access token for *creds*, exchanging and caching as needed.

    Blocking. Only ever call this from a worker thread.
    """
    if creds.access_token:
        return creds.access_token

    key = _cache_key(creds)
    now = time.monotonic()

    with _CACHE_LOCK:
        entry = _TOKEN_CACHE.get(key)
        if entry is not None:
            token, expires_at = entry
            if expires_at > now:
                _TOKEN_CACHE.move_to_end(key)
                return token
            del _TOKEN_CACHE[key]

    # Exchange outside the lock: a slow Spotify response must not block every
    # other caller's cache lookup. A concurrent duplicate exchange is harmless.
    token, expires_at = _exchange(creds)

    with _CACHE_LOCK:
        _TOKEN_CACHE[key] = (token, expires_at)
        _TOKEN_CACHE.move_to_end(key)
        while len(_TOKEN_CACHE) > MAX_CACHED_TOKENS:
            _TOKEN_CACHE.popitem(last=False)

    return token


# --- connection pooling ---------------------------------------------------


class _SharedPoolAdapter(HTTPAdapter):
    """An adapter whose connection pool outlives the sessions that mount it.

    ``Session.close()`` closes every adapter it holds. Each tool call gets its
    own short-lived session, so the default behaviour would discard the pool
    with it and every call would pay a fresh TCP and TLS handshake. Closing is
    a no-op here: the pool is process-wide and dies with the process.
    """

    def close(self) -> None:  # pragma: no cover - trivial override
        pass


# Shared across every caller. Safe precisely because a connection pool is keyed
# by host, not by credential: it holds sockets to accounts.spotify.com and
# api.spotify.com and nothing about who is calling. urllib3's PoolManager is
# thread-safe, which matters because tool calls run on anyio worker threads.
_SHARED_POOL = _SharedPoolAdapter(pool_connections=4, pool_maxsize=32)


def _pooled_session() -> requests.Session:
    """Return a fresh session that borrows the process-wide connection pool."""
    session = requests.Session()
    session.mount("https://", _SHARED_POOL)
    session.mount("http://", _SHARED_POOL)
    return session


@contextmanager
def spotify_for(headers: Mapping[str, str] | None) -> Iterator[tuple[spotipy.Spotify, str]]:
    """Yield ``(client, cache_scope)`` built from one request's headers.

    Blocking — it may perform a token exchange. Only ever enter this from a
    worker thread; ``server.run_tool`` is the sole caller.

    The client and its session are per-call, but connections are pooled
    process-wide. The split matters: the access token lives in this session's
    headers, so sharing one *session* between callers would let a second
    caller's token overwrite a first caller's mid-flight. Sharing only the pool
    keeps credentials strictly per-call while still reusing sockets.
    """
    creds = credentials_from_headers(headers)
    token = access_token_for(creds)
    session = _pooled_session()
    client = spotipy.Spotify(
        auth=token,
        requests_session=session,
        status_forcelist=RETRY_STATUS_CODES,
    )
    try:
        yield client, creds.cache_scope
    finally:
        session.close()
