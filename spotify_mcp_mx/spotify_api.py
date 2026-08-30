"""Feb 2026 regime fallback.

Spotify's February 2026 changes split apps into a "restricted" and a
"full/legacy" regime that serve different paths for the same operation. Which
one an app gets is not introspectable, so we try the restricted shape, fall
back to the legacy one, and remember the answer.

Tool calls on this server run on multiple `anyio` worker threads for many
different callers at once, each potentially on a different Spotify app (and
therefore a different regime). The memo is keyed per caller (`scope`, the
caller's Spotify client id) rather than process-global, so one caller's
regime can never pin another caller to the wrong endpoint. It is a bounded
LRU so an unbounded stream of distinct callers cannot grow it forever.

Paths and request bodies below are ported from the live-verified
implementation in https://github.com/jamiew/spotify-mcp-cloudflare
(src/endpoints.ts).
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

import spotipy
from spotipy import SpotifyException

from .utils import to_id, to_uri

if TYPE_CHECKING:
    from collections.abc import Callable

# Endpoint families confirmed to need the legacy path, per Spotify app.
#
# The reference memoises this in a process-global set. That is correct for a
# single-user stdio server and wrong for a shared one: two callers may be on
# two different regimes, and a global memo would let the first caller pin every
# later caller to the wrong endpoint for the life of the process.
_LEGACY_FAMILIES: OrderedDict[str, set[str]] = OrderedDict()
_MEMO_LOCK = threading.Lock()

MAX_MEMOISED_SCOPES = 512

# Statuses that mean "this route isn't served for us" rather than "not found".
# 400 is included because the restricted /me/library routes reject rather than
# 404 when the app is actually on the legacy regime.
_REGIME_MISS_STATUSES = frozenset({400, 404, 405, 410})


def with_fallback[T](
    scope: str, family: str, restricted: Callable[[], T], legacy: Callable[[], T]
) -> T:
    """Try the restricted request shape for *family*, falling back to the legacy one."""
    with _MEMO_LOCK:
        if family in _LEGACY_FAMILIES.get(scope, frozenset()):
            known_legacy = True
        else:
            known_legacy = False
    if known_legacy:
        return legacy()

    try:
        return restricted()
    except SpotifyException as e:
        if e.http_status not in _REGIME_MISS_STATUSES:
            raise
        # Only memoise once the legacy shape actually works — a genuine
        # not-found fails both ways and must not pin us to the wrong regime.
        result = legacy()
        with _MEMO_LOCK:
            _LEGACY_FAMILIES.setdefault(scope, set()).add(family)
            _LEGACY_FAMILIES.move_to_end(scope)
            while len(_LEGACY_FAMILIES) > MAX_MEMOISED_SCOPES:
                _LEGACY_FAMILIES.popitem(last=False)
        logging.getLogger(__name__).info(
            "Spotify '%s' endpoints resolved to the legacy regime for this app", family
        )
        return result


def reset_regime_memo() -> None:
    """Forget every memoised regime. Test seam; never called in production."""
    with _MEMO_LOCK:
        _LEGACY_FAMILIES.clear()


def playlist_items(
    sp: spotipy.Spotify, scope: str, playlist_id: str, *, limit: int, offset: int
) -> dict:
    """Read a page of playlist entries. Restricted serves /items, legacy /tracks."""
    pid = to_id(playlist_id)
    return with_fallback(
        scope,
        "playlist-items",
        lambda: sp._get(f"playlists/{pid}/items", limit=limit, offset=offset),
        lambda: sp.playlist_tracks(pid, limit=limit, offset=offset),
    )


def create_playlist(
    sp: spotipy.Spotify, scope: str, name: str, description: str, public: bool
) -> dict:
    """Restricted moved playlist creation from /users/{id}/playlists to /me/playlists."""
    body = {"name": name, "public": public, "description": description}
    return with_fallback(
        scope,
        "create-playlist",
        lambda: sp._post("me/playlists", payload=body),
        lambda: sp._post(f"users/{sp.current_user()['id']}/playlists", payload=body),
    )


def playlist_add_items(
    sp: spotipy.Spotify,
    scope: str,
    playlist_id: str,
    uris: list[str],
    position: int | None = None,
) -> dict:
    pid = to_id(playlist_id)
    body: dict = {"uris": uris}
    if position is not None:
        body["position"] = position
    return with_fallback(
        scope,
        "playlist-items",
        lambda: sp._post(f"playlists/{pid}/items", payload=body),
        lambda: sp._post(f"playlists/{pid}/tracks", payload=body),
    )


def playlist_remove_items(
    sp: spotipy.Spotify, scope: str, playlist_id: str, uris: list[str]
) -> dict:
    """Restricted keys the DELETE body off `items`; legacy off `tracks`."""
    pid = to_id(playlist_id)
    entries = [{"uri": uri} for uri in uris]
    return with_fallback(
        scope,
        "playlist-items",
        lambda: sp._delete(f"playlists/{pid}/items", payload={"items": entries}),
        lambda: sp._delete(f"playlists/{pid}/tracks", payload={"tracks": entries}),
    )


def playlist_reorder_items(
    sp: spotipy.Spotify,
    scope: str,
    playlist_id: str,
    *,
    range_start: int,
    insert_before: int,
    range_length: int = 1,
    snapshot_id: str | None = None,
) -> dict:
    pid = to_id(playlist_id)
    body: dict = {
        "range_start": range_start,
        "insert_before": insert_before,
        "range_length": range_length,
    }
    if snapshot_id:
        body["snapshot_id"] = snapshot_id
    return with_fallback(
        scope,
        "playlist-items",
        lambda: sp._put(f"playlists/{pid}/items", payload=body),
        lambda: sp._put(f"playlists/{pid}/tracks", payload=body),
    )


def save_tracks(sp: spotipy.Spotify, scope: str, track_ids: list[str]) -> None:
    """Restricted consolidated library writes onto /me/library, keyed by URI."""
    ids = [to_id(t) for t in track_ids]
    with_fallback(
        scope,
        "library-write",
        lambda: sp._put("me/library", payload={"uris": [to_uri("track", i) for i in ids]}),
        lambda: sp.current_user_saved_tracks_add(tracks=ids),
    )


def remove_saved_tracks(sp: spotipy.Spotify, scope: str, track_ids: list[str]) -> None:
    ids = [to_id(t) for t in track_ids]
    with_fallback(
        scope,
        "library-write",
        lambda: sp._delete("me/library", payload={"uris": [to_uri("track", i) for i in ids]}),
        lambda: sp.current_user_saved_tracks_delete(tracks=ids),
    )
