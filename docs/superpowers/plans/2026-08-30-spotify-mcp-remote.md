# Remote Spotify MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A remotely hosted MCP server exposing 25 Spotify tools over JSON-RPC, where each caller supplies their own Spotify credentials per request so one instance serves many users and stores nothing.

**Architecture:** `mcp` 2.x `MCPServer` behind a Starlette app serving stateless Streamable HTTP at `/mcp` and legacy SSE at `/sse`. Credentials arrive in three request headers; each tool call parses them, exchanges the refresh token for an access token (cached in memory ~1h), builds a throwaway `spotipy` client over a process-wide connection pool, and discards it. All of that runs on an `anyio` worker thread so blocking HTTP never stalls the event loop.

**Tech Stack:** Python 3.12, `mcp>=2.1.1,<3`, `spotipy>=2.26.0,<3`, Starlette, uvicorn, `uv`, pytest + pytest-asyncio, ruff, mypy (strict), Docker, Coolify.

**Spec:** `docs/superpowers/specs/2026-08-30-spotify-mcp-remote-design.md`

## Global Constraints

- Python `>=3.12`. Package/module name `spotify_mcp_mx`. Distribution name `spotify-mcp-mx`.
- `mcp>=2.1.1,<3` — use `mcp.server.mcpserver.MCPServer`, **not** `mcp.server.fastmcp.FastMCP`.
- mcp 2.x annotation fields are **snake_case**: `read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`; `Icon` uses `mime_type`.
- Tool errors are raised as `mcp.server.mcpserver.exceptions.ToolError`.
- Error message format, verbatim: `"<message> — <suggestion> (spotify reason: <reason>) [<error_code>]"` (em dash U+2014).
- Credential headers: `X-Spotify-Client-Id`, `X-Spotify-Client-Secret`, `X-Spotify-Refresh-Token`. Fallback: `Authorization: Bearer <access token>`.
- **No credential is ever written to disk.** Never construct `spotipy.oauth2.SpotifyOAuth` in server code — it writes a `.cache` file. Always `spotipy.Spotify(auth=<token>, ...)`.
- **No credential value is ever logged or echoed in an error message.** Errors name headers only.
- Default bind `HOST=0.0.0.0`, `PORT=6402`.
- `spotipy.Spotify` is always constructed with `status_forcelist=(500, 502, 503, 504)` — retry transient server errors, never a 429.
- Tools are `async`; every blocking Spotify call runs via `anyio.to_thread.run_sync`.
- 25 tools exactly. No resources, no prompts, no elicitation.
- ruff `line-length = 100`, mypy strict.

---

## File Structure

| File | Responsibility |
|---|---|
| `spotify_mcp_mx/__init__.py` | `__version__` only |
| `spotify_mcp_mx/utils.py` | `to_id`, `to_uri` — ID/URI/URL normalisation |
| `spotify_mcp_mx/spotify_types.py` | TypedDicts for the Spotify response subset read |
| `spotify_mcp_mx/errors.py` | Spotify exception → classified `ToolError` |
| `spotify_mcp_mx/models.py` | Pydantic response models (tool output schemas) |
| `spotify_mcp_mx/parsing.py` | Spotify JSON → models |
| `spotify_mcp_mx/auth.py` | Header parsing, token exchange, token cache, pooled session, per-call client |
| `spotify_mcp_mx/spotify_api.py` | Feb-2026 regime fallback, memo keyed by client id |
| `spotify_mcp_mx/logging_utils.py` | `log_tool_execution`, `log_pagination_info` |
| `spotify_mcp_mx/server.py` | `MCPServer` instance, instructions, icon, `run_tool` helper |
| `spotify_mcp_mx/tools/playback.py` | 6 playback tools |
| `spotify_mcp_mx/tools/catalog.py` | 4 catalog tools |
| `spotify_mcp_mx/tools/library.py` | 6 library/history tools |
| `spotify_mcp_mx/tools/playlists.py` | 9 playlist tools |
| `spotify_mcp_mx/app.py` | Starlette app: `/mcp`, `/sse`, `/health`, `/` |
| `spotify_mcp_mx/__main__.py` | uvicorn entrypoint |
| `spotify_mcp_mx/authorize.py` | Local one-time OAuth CLI (never runs on the server) |

**Reference checkout.** Several tasks port logic verbatim. Clone both references once, read-only, outside the repo:

```bash
git clone --depth 1 https://github.com/jamiew/spotify-mcp.git /tmp/ref-spotify && git clone --depth 1 https://github.com/maxim75/tfnsw_trip_planner_mcp.git /tmp/ref-tfnsw
```

Referred to below as `REF_SPOTIFY` (`/tmp/ref-spotify`) and `REF_TFNSW` (`/tmp/ref-tfnsw`).

---

### Task 1: Project scaffolding and tooling

**Files:**
- Modify: `pyproject.toml`
- Create: `spotify_mcp_mx/__init__.py`, `spotify_mcp_mx/tools/__init__.py`, `tests/__init__.py`, `tests/test_version.py`
- Delete: `main.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `spotify_mcp_mx.__version__: str`; a working `uv run pytest`, `uv run ruff check .`, `uv run mypy spotify_mcp_mx`.

- [ ] **Step 1: Write the failing test**

`tests/test_version.py`:

```python
from __future__ import annotations

import spotify_mcp_mx


def test_version_is_a_dotted_string() -> None:
    assert isinstance(spotify_mcp_mx.__version__, str)
    assert spotify_mcp_mx.__version__.count(".") == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_version.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx'`

- [ ] **Step 3: Replace `pyproject.toml`**

```toml
[project]
name = "spotify-mcp-mx"
version = "0.1.0"
description = "Remote MCP server for the Spotify Web API, with per-request user credentials"
readme = "README.md"
requires-python = ">=3.12"
license = "MIT"
keywords = ["mcp", "spotify", "model-context-protocol", "claude", "llm"]
dependencies = [
    "mcp>=2.1.1,<3",
    "spotipy>=2.26.0,<3",
    "starlette>=0.37.0",
    "uvicorn[standard]>=0.30.0",
]

[project.scripts]
spotify-mcp-mx = "spotify_mcp_mx.__main__:main"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
    "types-requests>=2.32.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["spotify_mcp_mx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = ["-v", "--tb=short", "--strict-markers"]
markers = [
    "live: hits the real Spotify API; requires SPOTIFY_* env vars (deselect with '-m \"not live\"')",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP", "TC"]
future-annotations = true
ignore = ["E501", "B008", "C901"]

[tool.ruff.lint.per-file-ignores]
# The MCP client transport is a stack of async context managers; one `async
# with` per line stays readable where collapsing them produces worse lines.
"tests/*" = ["SIM117"]

[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
strict_equality = true
show_error_codes = true

[[tool.mypy.overrides]]
module = ["spotipy.*"]
ignore_missing_imports = true
```

- [ ] **Step 4: Create the package skeleton**

`spotify_mcp_mx/__init__.py`:

```python
"""Remote MCP server for the Spotify Web API, with per-request user credentials."""

__version__ = "0.1.0"
```

`spotify_mcp_mx/tools/__init__.py`:

```python
"""Tool modules. Importing this package registers every tool on the server."""
```

`tests/__init__.py`: empty file.

- [ ] **Step 5: Remove the scaffold entrypoint**

```bash
rm main.py
```

- [ ] **Step 6: Sync and run the test**

Run: `uv sync && uv run pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 7: Verify lint and types are clean**

Run: `uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: both exit 0

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock spotify_mcp_mx tests .python-version .gitignore
git rm --cached main.py 2>/dev/null; git add -A
git commit -m "chore: scaffold spotify_mcp_mx package with uv, ruff and mypy"
```

---

### Task 2: ID and URI normalisation

**Files:**
- Create: `spotify_mcp_mx/utils.py`, `spotify_mcp_mx/spotify_types.py`
- Test: `tests/test_utils.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `to_id(value: str) -> str`, `to_uri(kind: str, value: str) -> str`. TypedDicts `ExternalUrls`, `ArtistRef`, `AlbumRef`, `Followers`, `TrackObject`, `ArtistObject`, `AlbumObject`, `PlaylistObject`.

- [ ] **Step 1: Write the failing test**

`tests/test_utils.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.utils'`

- [ ] **Step 3: Write `spotify_mcp_mx/utils.py`**

```python
"""Normalising Spotify references.

Tools accept a bare ID, a ``spotify:type:id`` URI or an open.spotify.com URL
interchangeably, so every entry point funnels through here first.
"""

from __future__ import annotations

from urllib.parse import urlparse

__all__ = ["to_id", "to_uri"]


def to_id(value: str) -> str:
    """Accept a bare Spotify ID, a ``spotify:type:id`` URI, or an open.spotify.com URL."""
    value = value.strip()
    if value.startswith("spotify:"):
        return value.rsplit(":", 1)[-1]
    if "open.spotify.com/" in value:
        return urlparse(value).path.rsplit("/", 1)[-1].split("?")[0]
    return value


def to_uri(kind: str, value: str) -> str:
    """Build a ``spotify:{kind}:{id}`` URI from anything :func:`to_id` accepts."""
    return f"spotify:{kind}:{to_id(value)}"
```

- [ ] **Step 4: Copy the TypedDicts**

Copy `REF_SPOTIFY/src/spotify_mcp/spotify_types.py` to `spotify_mcp_mx/spotify_types.py` unchanged — it has no imports from its own package, so it ports as-is.

```bash
cp /tmp/ref-spotify/src/spotify_mcp/spotify_types.py spotify_mcp_mx/spotify_types.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_utils.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS, both linters exit 0

- [ ] **Step 6: Commit**

```bash
git add spotify_mcp_mx/utils.py spotify_mcp_mx/spotify_types.py tests/test_utils.py
git commit -m "feat: add Spotify ID/URI normalisation and response TypedDicts"
```

---

### Task 3: Error classification

**Files:**
- Create: `spotify_mcp_mx/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SpotifyMCPErrorCode` (StrEnum-like `Enum`), `SpotifyMCPError(code, message, details=None, suggestion=None)` with `.from_spotify_exception()`, `convert_spotify_error(e: Exception) -> ToolError`, `MissingCredentialsError`, `TokenRefreshError`.

**Note on the two added codes:** `MISSING_CREDENTIALS = "missing_credentials"` and `TOKEN_REFRESH_FAILED = "token_refresh_failed"` are new in this server; the rest of the enum is ported verbatim.

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`:

```python
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from spotipy import SpotifyException

from spotify_mcp_mx.errors import (
    MissingCredentialsError,
    SpotifyMCPError,
    SpotifyMCPErrorCode,
    convert_spotify_error,
)


def _exc(status: int, msg: str = "boom", reason: str | None = None) -> SpotifyException:
    e = SpotifyException(status, -1, msg)
    e.reason = reason
    return e


def test_reason_beats_status_code() -> None:
    err = SpotifyMCPError.from_spotify_exception(_exc(404, "nope", reason="NO_ACTIVE_DEVICE"))
    assert err.code is SpotifyMCPErrorCode.NO_ACTIVE_DEVICE


def test_premium_required_from_reason() -> None:
    err = SpotifyMCPError.from_spotify_exception(_exc(403, "x", reason="PREMIUM_REQUIRED"))
    assert err.code is SpotifyMCPErrorCode.PREMIUM_REQUIRED


def test_quota_exceeded_from_reason() -> None:
    err = SpotifyMCPError.from_spotify_exception(_exc(429, "x", reason="QUOTA_EXCEEDED"))
    assert err.code is SpotifyMCPErrorCode.API_QUOTA_EXCEEDED


def test_rate_limit_carries_retry_after() -> None:
    e = _exc(429, "slow down")
    e.headers = {"Retry-After": "12"}
    err = SpotifyMCPError.from_spotify_exception(e)
    assert err.code is SpotifyMCPErrorCode.API_RATE_LIMITED
    assert err.details["retry_after"] == "12"
    assert err.suggestion is not None and "12" in err.suggestion


def test_server_error_maps_to_unavailable() -> None:
    err = SpotifyMCPError.from_spotify_exception(_exc(503))
    assert err.code is SpotifyMCPErrorCode.API_UNAVAILABLE


def test_reason_is_always_kept_in_details() -> None:
    err = SpotifyMCPError.from_spotify_exception(_exc(403, "x", reason="UNKNOWN_THING"))
    assert err.details["reason"] == "UNKNOWN_THING"


def test_message_format_is_exactly_the_reference_shape() -> None:
    err = SpotifyMCPError(
        SpotifyMCPErrorCode.NO_ACTIVE_DEVICE,
        "No active Spotify device found",
        {"reason": "NO_ACTIVE_DEVICE"},
        "Open Spotify on a device",
    )
    converted = convert_spotify_error(err)
    assert isinstance(converted, ToolError)
    assert str(converted) == (
        "No active Spotify device found — Open Spotify on a device "
        "(spotify reason: NO_ACTIVE_DEVICE) [no_active_device]"
    )


def test_missing_credentials_converts_to_tool_error() -> None:
    converted = convert_spotify_error(MissingCredentialsError("send your headers"))
    assert isinstance(converted, ToolError)
    assert "send your headers" in str(converted)
    assert "[missing_credentials]" in str(converted)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.errors'`

- [ ] **Step 3: Port the classification table**

Start from `REF_SPOTIFY/src/spotify_mcp/errors.py` and apply exactly these changes:

1. Add to `SpotifyMCPErrorCode`:
   ```python
   MISSING_CREDENTIALS = "missing_credentials"
   TOKEN_REFRESH_FAILED = "token_refresh_failed"  # nosec B105 - not a password
   ```
2. Add two exception classes above `convert_spotify_error`:
   ```python
   class MissingCredentialsError(Exception):
       """The request carried no usable Spotify credentials."""


   class TokenRefreshError(Exception):
       """Spotify rejected the refresh-token exchange."""
   ```
3. Replace the body of `convert_spotify_error` so it returns `ToolError`:
   ```python
   def convert_spotify_error(e: Exception) -> ToolError:
       """Convert any tool-layer exception into a ToolError with the standard message."""
       if isinstance(e, SpotifyException):
           return ToolError(_format_error(SpotifyMCPError.from_spotify_exception(e)))
       if isinstance(e, SpotifyMCPError):
           return ToolError(_format_error(e))
       if isinstance(e, MissingCredentialsError):
           return ToolError(
               _format_error(SpotifyMCPError(SpotifyMCPErrorCode.MISSING_CREDENTIALS, str(e)))
           )
       if isinstance(e, TokenRefreshError):
           return ToolError(
               _format_error(SpotifyMCPError(SpotifyMCPErrorCode.TOKEN_REFRESH_FAILED, str(e)))
           )
       if isinstance(e, ValueError):
           return ToolError(str(e))
       return ToolError(f"Unexpected error: {e}")
   ```
4. Add the import: `from mcp.server.mcpserver.exceptions import ToolError`.
5. Leave `_format_error` and `_classify` byte-for-byte as in the reference.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS, linters clean

- [ ] **Step 5: Commit**

```bash
git add spotify_mcp_mx/errors.py tests/test_errors.py
git commit -m "feat: port Spotify error classification onto ToolError"
```

---

### Task 4: Response models

**Files:**
- Create: `spotify_mcp_mx/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Track`, `Album`, `Artist`, `Playlist`, `PlaybackState`, `Device`, `UserProfile`, `SearchResults`, `QueueState`, `TrackList`, `ArtistInfo`, `AlbumInfo`, `PlaylistList`, `PlaylistTracks`, `SavedTracks`, `DeviceList`, `TopItems`, `RecentlyPlayed`, `ActionResult`.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:

```python
from __future__ import annotations

from spotify_mcp_mx.models import ActionResult, PlaylistTracks, Track, UserProfile


def test_track_requires_only_name_id_and_artist() -> None:
    t = Track(name="Idioteque", id="abc", artist="Radiohead")
    assert t.album is None
    assert t.added_at is None
    assert t.played_at is None


def test_user_profile_requires_only_id() -> None:
    # Spotify's restricted regime strips these fields rather than erroring,
    # so requiring any of them would turn a degraded response into a failure.
    profile = UserProfile(id="maksym")
    assert profile.display_name is None
    assert profile.email is None
    assert profile.country is None


def test_playlist_tracks_reports_returned_separately_from_total() -> None:
    page = PlaylistTracks(items=[], total=1200, limit=100, offset=0, returned=0)
    assert page.total == 1200
    assert page.returned == 0


def test_action_result_snapshot_is_optional() -> None:
    assert ActionResult(status="success", message="done").snapshot_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.models'`

- [ ] **Step 3: Write `spotify_mcp_mx/models.py`**

Copy the model class definitions from `REF_SPOTIFY/src/spotify_mcp/fastmcp_server.py` lines 88–277 — that is every `class X(BaseModel)` from `Track` through `ActionResult`. Field names, types and defaults must match exactly, because they define the tools' output schemas.

**Omit `RemovalConfirmation`** (it was the elicitation schema; elicitation is out of scope).

Add at the top:

```python
"""Pydantic response models. These are the tools' structured output schemas.

Field names, types and optionality mirror jamiew/spotify-mcp exactly so a client
written against that server sees the same shapes here.
"""

from __future__ import annotations

from pydantic import BaseModel
```

and an `__all__` listing all 19 model names.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS, linters clean

- [ ] **Step 5: Commit**

```bash
git add spotify_mcp_mx/models.py tests/test_models.py
git commit -m "feat: add Pydantic response models matching the reference schemas"
```

---

### Task 5: Parsing Spotify JSON into models

**Files:**
- Create: `spotify_mcp_mx/parsing.py`
- Test: `tests/test_parsing.py`, `tests/fixtures.py`

**Interfaces:**
- Consumes: `spotify_mcp_mx.models`, `spotify_mcp_mx.spotify_types`.
- Produces: `parse_track(item: TrackObject) -> Track`, `parse_artist(item: ArtistObject) -> Artist`, `parse_album(item: AlbumObject) -> Album`, `parse_playlist(item: PlaylistObject, *, tracks: list[Track] | None = None) -> Playlist`.

- [ ] **Step 1: Write the shared fixtures**

`tests/fixtures.py`:

```python
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
```

- [ ] **Step 2: Write the failing test**

`tests/test_parsing.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_parsing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.parsing'`

- [ ] **Step 4: Write `spotify_mcp_mx/parsing.py`**

```python
"""Spotify API payloads → response models.

spotipy returns untyped dicts. Everything the tools read passes through here so
missing optional fields degrade to None in one place rather than 25.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .models import Album, Artist, Playlist, Track

if TYPE_CHECKING:
    from .spotify_types import AlbumObject, ArtistObject, PlaylistObject, TrackObject

__all__ = ["parse_album", "parse_artist", "parse_playlist", "parse_track"]


def parse_track(item: TrackObject) -> Track:
    """Parse Spotify track data into a Track."""
    album_data = item.get("album") or {}
    artists = item.get("artists") or []
    return Track(
        name=item["name"],
        id=item["id"],
        artist=artists[0]["name"] if artists else "Unknown",
        artists=[a["name"] for a in artists],
        album=album_data.get("name"),
        album_id=album_data.get("id"),
        release_date=album_data.get("release_date"),
        duration_ms=item.get("duration_ms"),
        popularity=item.get("popularity"),
        external_urls=cast("dict[str, str] | None", item.get("external_urls")),
    )


def parse_artist(item: ArtistObject) -> Artist:
    """Parse Spotify artist data into an Artist."""
    followers = item.get("followers") or {}
    return Artist(
        name=item["name"],
        id=item["id"],
        genres=item.get("genres", []),
        popularity=item.get("popularity"),
        followers=followers.get("total"),
    )


def parse_album(item: AlbumObject) -> Album:
    """Parse Spotify album metadata into an Album (without its track list)."""
    artists = item.get("artists") or []
    return Album(
        name=item["name"],
        id=item["id"],
        artist=artists[0]["name"] if artists else "Unknown",
        artists=[a["name"] for a in artists],
        release_date=item.get("release_date"),
        release_date_precision=item.get("release_date_precision"),
        total_tracks=item.get("total_tracks"),
        album_type=item.get("album_type"),
        label=item.get("label"),
        genres=item.get("genres", []),
        popularity=item.get("popularity"),
        external_urls=cast("dict[str, str] | None", item.get("external_urls")),
    )


def parse_playlist(item: PlaylistObject, *, tracks: list[Track] | None = None) -> Playlist:
    """Parse Spotify playlist metadata into a Playlist."""
    owner = item.get("owner") or {}
    tracks_meta = item.get("tracks") or {}
    return Playlist(
        name=item["name"],
        id=item["id"],
        owner=owner.get("display_name"),
        description=item.get("description"),
        tracks=tracks,
        total_tracks=tracks_meta.get("total"),
        public=item.get("public"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_parsing.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS, linters clean

- [ ] **Step 6: Commit**

```bash
git add spotify_mcp_mx/parsing.py tests/test_parsing.py tests/fixtures.py
git commit -m "feat: parse Spotify payloads into response models"
```

---

### Task 6: Per-request authentication

**Files:**
- Create: `spotify_mcp_mx/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `spotify_mcp_mx.errors` (`MissingCredentialsError`, `TokenRefreshError`).
- Produces:
  - `CLIENT_ID_HEADER`, `CLIENT_SECRET_HEADER`, `REFRESH_TOKEN_HEADER: str`
  - `Credentials` — frozen dataclass with `client_id: str`, `client_secret: str`, `refresh_token: str`, `access_token: str | None`, and property `cache_scope: str` (the client id, or `""` for the bearer form)
  - `credentials_from_headers(headers: Mapping[str, str] | None) -> Credentials`
  - `access_token_for(creds: Credentials) -> str`
  - `spotify_for(headers: Mapping[str, str] | None) -> ContextManager[tuple[spotipy.Spotify, str]]` yielding `(client, cache_scope)`
  - `reset_token_cache() -> None` (test seam)
  - `RETRY_STATUS_CODES: tuple[int, ...]`

**Critical:** `spotify_for` performs blocking HTTP (the token exchange). It must only ever be entered from a worker thread — Task 8's `run_tool` is the only caller. The token cache is therefore touched from multiple threads and is guarded by a `threading.Lock`.

- [ ] **Step 1: Write the failing test**

`tests/test_auth.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.auth'`

- [ ] **Step 3: Write `spotify_mcp_mx/auth.py`**

```python
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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import requests
import spotipy
from requests.adapters import HTTPAdapter

from .errors import MissingCredentialsError, TokenRefreshError

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (16 tests), linters clean

- [ ] **Step 5: Commit**

```bash
git add spotify_mcp_mx/auth.py tests/test_auth.py
git commit -m "feat: per-request Spotify credentials with a bounded in-memory token cache"
```

---

### Task 7: Regime fallback, keyed per caller

**Files:**
- Create: `spotify_mcp_mx/spotify_api.py`
- Test: `tests/test_regime.py`

**Interfaces:**
- Consumes: `spotify_mcp_mx.utils` (`to_id`, `to_uri`).
- Produces, all taking `scope: str` as their first argument after the client:
  - `playlist_items(sp, scope, playlist_id, *, limit, offset) -> dict`
  - `create_playlist(sp, scope, name, description, public) -> dict`
  - `playlist_add_items(sp, scope, playlist_id, uris, position=None) -> dict`
  - `playlist_remove_items(sp, scope, playlist_id, uris) -> dict`
  - `playlist_reorder_items(sp, scope, playlist_id, *, range_start, insert_before, range_length=1, snapshot_id=None) -> dict`
  - `save_tracks(sp, scope, track_ids) -> None`
  - `remove_saved_tracks(sp, scope, track_ids) -> None`
  - `with_fallback(scope, family, restricted, legacy) -> T`
  - `reset_regime_memo() -> None` (test seam)

**Why `scope` exists:** the reference memoises "this family is on the legacy regime" in a process-global set. On a shared server two callers may be on different regimes, and a global memo lets the first caller pin every later caller to the wrong endpoint. The memo here is `dict[scope, set[family]]`.

- [ ] **Step 1: Write the failing test**

`tests/test_regime.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_regime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.spotify_api'`

- [ ] **Step 3: Write `spotify_mcp_mx/spotify_api.py`**

Port `REF_SPOTIFY/src/spotify_mcp/spotify_api.py` from the `# === Feb 2026 regime fallback ===` comment onwards (drop the whole `load_config` / `Client` / `SCOPES` section — this server has no module-level client). Apply these changes:

1. The memo becomes per-caller and bounded:

```python
# Endpoint families confirmed to need the legacy path, per Spotify app.
#
# The reference memoises this in a process-global set. That is correct for a
# single-user stdio server and wrong for a shared one: two callers may be on
# two different regimes, and a global memo would let the first caller pin every
# later caller to the wrong endpoint for the life of the process.
_LEGACY_FAMILIES: OrderedDict[str, set[str]] = OrderedDict()
_MEMO_LOCK = threading.Lock()

MAX_MEMOISED_SCOPES = 512
```

2. `with_fallback` gains `scope` as its first parameter:

```python
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
```

3. Every wrapper gains `scope` as its second parameter and passes it through. For example:

```python
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
```

Apply the same transformation to `create_playlist`, `playlist_add_items`, `playlist_remove_items`, `playlist_reorder_items`, `save_tracks` and `remove_saved_tracks`, keeping every path string, payload shape and family name exactly as the reference has them.

4. Imports needed at the top: `import logging`, `import threading`, `from collections import OrderedDict`, `from collections.abc import Callable`, `import spotipy`, `from spotipy import SpotifyException`, `from .utils import to_id, to_uri`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_regime.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (14 tests), linters clean

- [ ] **Step 5: Commit**

```bash
git add spotify_mcp_mx/spotify_api.py tests/test_regime.py
git commit -m "feat: regime fallback memoised per Spotify app, not process-wide"
```

---

### Task 8: Server instance and the tool-call harness

**Files:**
- Create: `spotify_mcp_mx/logging_utils.py`, `spotify_mcp_mx/server.py`
- Test: `tests/test_server_harness.py`

**Interfaces:**
- Consumes: `spotify_mcp_mx.auth` (`spotify_for`), `spotify_mcp_mx.errors` (`convert_spotify_error`).
- Produces:
  - `mcp: MCPServer`
  - `SPOTIFY_ICON: Icon`
  - `INSTRUCTIONS: str`
  - `run_tool(ctx: Context, fn: Callable[[spotipy.Spotify, str], T]) -> T` — **the harness every tool uses**
  - `log_tool_execution`, `log_pagination_info`

**This is the pattern every one of the 25 tools follows.** Tasks 9–12 apply it mechanically.

- [ ] **Step 1: Write the failing test**

`tests/test_server_harness.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from spotipy import SpotifyException

from spotify_mcp_mx.server import mcp, run_tool


class FakeCtx:
    def __init__(self, headers: dict[str, str] | None) -> None:
        self.headers = headers


HEADERS = {
    "X-Spotify-Client-Id": "id-1",
    "X-Spotify-Client-Secret": "s",
    "X-Spotify-Refresh-Token": "r",
}


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Replace spotify_for with a context manager yielding a recording double."""
    import contextlib

    class FakeSpotify:
        def current_user(self) -> dict[str, Any]:
            return {"id": "maksym"}

    @contextlib.contextmanager
    def fake_spotify_for(headers: Any) -> Any:
        from spotify_mcp_mx.auth import credentials_from_headers

        creds = credentials_from_headers(headers)
        yield FakeSpotify(), creds.cache_scope

    monkeypatch.setattr("spotify_mcp_mx.server.spotify_for", fake_spotify_for)
    return FakeSpotify


async def test_run_tool_passes_the_client_and_scope(patched_client: Any) -> None:
    seen: dict[str, Any] = {}

    def work(client: Any, scope: str) -> str:
        seen["scope"] = scope
        return str(client.current_user()["id"])

    assert await run_tool(FakeCtx(HEADERS), work) == "maksym"
    assert seen["scope"] == "id-1"


async def test_missing_credentials_surface_as_tool_error(patched_client: Any) -> None:
    with pytest.raises(ToolError) as excinfo:
        await run_tool(FakeCtx(None), lambda client, scope: "unreachable")
    assert "X-Spotify-Refresh-Token" in str(excinfo.value)
    assert "[missing_credentials]" in str(excinfo.value)


async def test_spotify_exceptions_are_classified(patched_client: Any) -> None:
    def work(client: Any, scope: str) -> str:
        exc = SpotifyException(404, -1, "nope")
        exc.reason = "NO_ACTIVE_DEVICE"
        raise exc

    with pytest.raises(ToolError) as excinfo:
        await run_tool(FakeCtx(HEADERS), work)
    assert "[no_active_device]" in str(excinfo.value)


async def test_validation_errors_surface_verbatim(patched_client: Any) -> None:
    def work(client: Any, scope: str) -> str:
        raise ValueError("action='seek' requires position_ms")

    with pytest.raises(ToolError) as excinfo:
        await run_tool(FakeCtx(HEADERS), work)
    assert str(excinfo.value) == "action='seek' requires position_ms"


async def test_server_carries_instructions_and_an_icon() -> None:
    assert mcp.instructions
    assert "search_music" in (mcp.instructions or "")
    assert mcp.icons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.server'`

- [ ] **Step 3: Write `spotify_mcp_mx/logging_utils.py`**

Copy `REF_SPOTIFY/src/spotify_mcp/logging_utils.py`, with one change to `_log_invocation` — the tool `ctx` must never be logged, because `ctx.headers` carries the caller's secret:

```python
def _log_invocation(tool_name: str, kwargs: dict[str, Any], start_time: float) -> None:
    # `ctx` carries the caller's credential headers, so it is dropped rather
    # than serialised into a log record.
    sanitized_kwargs = {k: v for k, v in kwargs.items() if k not in ("ctx", "password")}
    logger.info(
        f"🔧 Tool invoked: {tool_name}",
        extra={
            "tool_name": tool_name,
            "parameters": sanitized_kwargs,
            "timestamp": start_time,
        },
    )
```

Keep `log_tool_execution` and `log_pagination_info` otherwise identical.

- [ ] **Step 4: Write `spotify_mcp_mx/server.py`**

```python
"""The MCP server instance and the harness every tool call goes through."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, TypeVar

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import Icon

from . import __version__
from .auth import CLIENT_ID_HEADER, CLIENT_SECRET_HEADER, REFRESH_TOKEN_HEADER, spotify_for
from .errors import convert_spotify_error

if TYPE_CHECKING:
    from collections.abc import Callable

    import spotipy

__all__ = ["INSTRUCTIONS", "SPOTIFY_ICON", "mcp", "run_tool"]

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Guidance that applies to the whole surface lives here rather than in every
# tool description — it ships once per session instead of once per tool.
INSTRUCTIONS = f"""\
Spotify for the signed-in user. Tracks, albums, artists and playlists are accepted as
bare IDs or spotify: URIs anywhere.

Every request must carry the caller's own Spotify credentials in the
{CLIENT_ID_HEADER}, {CLIENT_SECRET_HEADER} and {REFRESH_TOKEN_HEADER} HTTP headers.
This server stores no credentials.

Start from search_music to turn names into IDs. get_playlist_tracks returns zero-based
positions, which reorder_playlist_tracks and remove_tracks_from_playlist need.

Playback tools need Spotify Premium and an open device; if none is active, call
list_devices then transfer_playback.

Spotify has withdrawn /recommendations, audio-features and related-artists from
third-party apps, so there is no recommendation endpoint to call. Build suggestions
from get_top_items and get_recently_played plus search_music instead.

Newly created playlists may read back as public even when created private; that is
Spotify's reporting, not a failed write.
"""

# Shared Spotify glyph, attached to the server and to every tool.
SPOTIFY_ICON = Icon(
    src=(
        "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdC"
        "b3g9IjAgMCAyNCAyNCI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTIiIGZpbGw9IiMxREI5NTQiLz48"
        "cGF0aCBmaWxsPSIjZmZmIiBkPSJNMTcgMTYuNmEuNy43IDAgMCAxLTEgLjI1Yy0yLjctMS42NS02LjEtMi0x"
        "MC4xLTEuMWEuNzUuNzUgMCAxIDEtLjMzLTEuNDZjNC40LTEgOC4yLS42IDExLjIgMS4yNS4zNS4yLjQ2LjY2"
        "LjIzIDEuMDZ6bTEuMy0yLjk1YS45NC45NCAwIDAgMS0xLjI5LjNjLTMuMS0xLjktNy44LTIuNDYtMTEuNDUt"
        "MS4zNWEuOTQuOTQgMCAxIDEtLjU1LTEuOGM0LjE4LTEuMjcgOS4zNi0uNjUgMTIuOTMgMS41NS40NC4yNy41"
        "OC44NS4zNiAxLjN6bS4xLTMuMDdDMTQuNyA4LjQgOC45IDguMiA1LjQzIDkuMjZhMS4xMiAxLjEyIDAgMSAx"
        "LS42NS0yLjE1QzguNzYgNS45IDE1LjE4IDYuMTMgMTkuNDUgOC42NmExLjEyIDEuMTIgMCAxIDEtMS4xNSAx"
        "LjkyeiIvPjwvc3ZnPg=="
    ),
    mime_type="image/svg+xml",
)

mcp = MCPServer(
    "Spotify MCP",
    title="Spotify",
    instructions=INSTRUCTIONS,
    website_url="https://github.com/maxim75/spotify-mcp-mx",
    icons=[SPOTIFY_ICON],
    version=__version__,
)


async def run_tool(ctx: Context, fn: Callable[[spotipy.Spotify, str], T]) -> T:
    """Run *fn* with a client built from this request's credentials.

    ``fn`` receives ``(client, cache_scope)`` and runs entirely on a worker
    thread, because everything it touches blocks: the token exchange, and
    spotipy's synchronous ``requests`` calls. A slow Spotify response must not
    stall the event loop and every other in-flight call with it.

    Headers are read here, on the event loop, and copied into the closure —
    ``ctx`` itself is never handed to the worker.
    """
    headers = dict(getattr(ctx, "headers", None) or {})

    def work() -> T:
        with spotify_for(headers) as (client, scope):
            return fn(client, scope)

    try:
        return await anyio.to_thread.run_sync(work)
    except Exception as exc:  # noqa: BLE001 - re-raised as a classified ToolError
        raise convert_spotify_error(exc) from None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_server_harness.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (5 tests), linters clean

- [ ] **Step 6: Commit**

```bash
git add spotify_mcp_mx/server.py spotify_mcp_mx/logging_utils.py tests/test_server_harness.py
git commit -m "feat: MCP server instance and the per-request tool harness"
```

---

## The porting transformation (Tasks 9–12)

Every one of the 25 tools is the same mechanical change from the reference. Read this once; Tasks 9–12 apply it.

**Reference form** (`REF_SPOTIFY/src/spotify_mcp/fastmcp_server.py`) — module-level client, sync function, camelCase annotations:

```python
@mcp.tool(
    title="Spotify Profile",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
def get_me() -> UserProfile:
    """Get the signed-in user's Spotify profile."""
    try:
        me = spotify_client.current_user() or {}
        return UserProfile(id=me["id"], display_name=me.get("display_name"), ...)
    except SpotifyException as e:
        raise convert_spotify_error(e) from e
```

**Ported form** — `ctx` parameter, async, work in a closure, snake_case annotations, no local try/except:

```python
@mcp.tool(
    title="Spotify Profile",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=True
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_me(ctx: Context) -> UserProfile:
    """Get the signed-in user's Spotify profile.

    Returns:
        UserProfile. email/country/product are unavailable on newer Spotify apps
        and come back empty rather than erroring.
    """

    def work(client: spotipy.Spotify, scope: str) -> UserProfile:
        me = client.current_user() or {}
        return UserProfile(
            id=me["id"],
            display_name=me.get("display_name"),
            email=me.get("email"),
            country=me.get("country"),
            product=me.get("product"),
            followers=(me.get("followers") or {}).get("total"),
        )

    return await run_tool(ctx, work)
```

The five rules:

1. Add `ctx: Context` as the **last** parameter. The SDK injects it by type annotation and excludes it from the input schema, so client-visible arguments are unchanged. Keep every other parameter name, type and default exactly as the reference has them.
2. Make the function `async`; move the body into `def work(client, scope) -> <ReturnType>` and `return await run_tool(ctx, work)`.
3. Replace `spotify_client` with `client`, and pass `scope` to any `spotify_api.*` helper.
4. Delete the local `try/except SpotifyException` — `run_tool` classifies everything, including the `ValueError`s raised for argument validation, which keep their exact messages.
5. Rename annotation fields to snake_case: `readOnlyHint` → `read_only_hint`, `destructiveHint` → `destructive_hint`, `idempotentHint` → `idempotent_hint`, `openWorldHint` → `open_world_hint`.

Every tool module starts with this header:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ..logging_utils import log_tool_execution
from ..models import ...            # only what this module returns
from ..server import SPOTIFY_ICON, mcp, run_tool

if TYPE_CHECKING:
    import spotipy
```

**Shared test doubles.** Tasks 9–12 all use one fake client. Create it once in Task 9.

---

### Task 9: Playback tools

**Files:**
- Create: `spotify_mcp_mx/tools/playback.py`, `tests/conftest.py`
- Modify: `spotify_mcp_mx/tools/__init__.py`
- Test: `tests/test_tools_playback.py`

**Interfaces:**
- Consumes: Task 8's `mcp`, `run_tool`, `SPOTIFY_ICON`; Task 4's models; Task 5's `parse_track`; Task 2's `to_uri`.
- Produces: tools `get_playback_state`, `control_playback`, `list_devices`, `transfer_playback`, `get_queue`, `add_to_queue`; and `tests/conftest.py` fixtures `fake_spotify` and `call_tool` used by Tasks 10–12.

- [ ] **Step 1: Write the shared conftest**

`tests/conftest.py`:

```python
"""Shared fakes. The Spotify client is mocked, so the suite is fully offline."""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

HEADERS = {
    "X-Spotify-Client-Id": "id-1",
    "X-Spotify-Client-Secret": "secret-1",
    "X-Spotify-Refresh-Token": "refresh-1",
}


class FakeSpotify:
    """Records every call and returns whatever was queued for that method."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses: dict[str, Any] = {}

    # Deliberately no explicitly named methods below: `queue`, `track`, `album`
    # and friends are all real Spotify method names, and defining any of them
    # here would shadow __getattr__ (which only fires when normal attribute
    # lookup fails) and break the tool that calls it.

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)

        def method(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            value = self.responses.get(name)
            if callable(value):
                return value(*args, **kwargs)
            return value

        return method

    def last_call(self, name: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        for called, args, kwargs in reversed(self.calls):
            if called == name:
                return args, kwargs
        raise AssertionError(f"{name} was never called. Calls: {[c[0] for c in self.calls]}")

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)


class FakeCtx:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = HEADERS if headers is None else headers
        self.progress: list[tuple[float, float | None]] = []
        self.messages: list[str] = []

    async def report_progress(self, progress: float, total: float | None = None) -> None:
        self.progress.append((progress, total))

    async def info(self, message: str) -> None:
        self.messages.append(message)


@pytest.fixture
def fake_spotify(monkeypatch: pytest.MonkeyPatch) -> FakeSpotify:
    """Patch the tool harness so every tool runs against a FakeSpotify."""
    client = FakeSpotify()

    @contextlib.contextmanager
    def fake_spotify_for(headers: Any) -> Any:
        from spotify_mcp_mx.auth import credentials_from_headers

        creds = credentials_from_headers(headers)
        yield client, creds.cache_scope

    monkeypatch.setattr("spotify_mcp_mx.server.spotify_for", fake_spotify_for)
    return client


@pytest.fixture
def ctx() -> FakeCtx:
    return FakeCtx()
```

- [ ] **Step 2: Write the failing test**

`tests/test_tools_playback.py`:

```python
from __future__ import annotations

import copy

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.playback import (
    add_to_queue,
    control_playback,
    get_playback_state,
    get_queue,
    list_devices,
    transfer_playback,
)
from tests.conftest import FakeCtx, FakeSpotify
from tests.fixtures import TRACK

PLAYBACK = {
    "is_playing": True,
    "item": TRACK,
    "device": {"name": "Study speaker", "volume_percent": 55},
    "shuffle_state": True,
    "repeat_state": "context",
    "progress_ms": 42_000,
}


async def test_get_playback_state_maps_every_field(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_playback"] = copy.deepcopy(PLAYBACK)
    state = await get_playback_state(ctx)
    assert state.is_playing is True
    assert state.track is not None and state.track.name == "Idioteque"
    assert state.device == "Study speaker"
    assert state.volume == 55
    assert state.shuffle is True
    assert state.repeat == "context"
    assert state.progress_ms == 42_000


async def test_get_playback_state_when_nothing_is_playing(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_playback"] = None
    state = await get_playback_state(ctx)
    assert state.is_playing is False
    assert state.track is None
    assert state.repeat == "off"


async def test_control_playback_play_with_track_ids_sends_uris(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_playback"] = copy.deepcopy(PLAYBACK)
    await control_playback("play", track_ids=["abc", "spotify:track:def"], ctx=ctx)
    _args, kwargs = fake_spotify.last_call("start_playback")
    assert kwargs["uris"] == ["spotify:track:abc", "spotify:track:def"]


async def test_control_playback_context_uri_beats_track_ids(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_playback"] = copy.deepcopy(PLAYBACK)
    await control_playback("play", track_ids=["abc"], context_uri="spotify:album:x", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("start_playback")
    assert kwargs["context_uri"] == "spotify:album:x"
    assert "uris" not in kwargs


@pytest.mark.parametrize(
    ("action", "method"),
    [("pause", "pause_playback"), ("next", "next_track"), ("previous", "previous_track")],
)
async def test_control_playback_simple_actions(
    fake_spotify: FakeSpotify, ctx: FakeCtx, action: str, method: str
) -> None:
    fake_spotify.responses["current_playback"] = copy.deepcopy(PLAYBACK)
    await control_playback(action, ctx=ctx)
    assert fake_spotify.called(method)


async def test_control_playback_seek_requires_position(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await control_playback("seek", ctx=ctx)
    assert str(excinfo.value) == "action='seek' requires position_ms"


async def test_control_playback_volume_requires_percent(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await control_playback("volume", ctx=ctx)
    assert str(excinfo.value) == "action='volume' requires volume_percent"


async def test_control_playback_shuffle_validates_state(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await control_playback("shuffle", state="maybe", ctx=ctx)
    assert str(excinfo.value) == "action='shuffle' requires state='on' or 'off'"


async def test_control_playback_repeat_validates_state(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError):
        await control_playback("repeat", state="sometimes", ctx=ctx)


async def test_control_playback_rejects_unknown_action(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await control_playback("teleport", ctx=ctx)
    assert str(excinfo.value) == "Invalid action: teleport"


async def test_list_devices(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["devices"] = {
        "devices": [
            {"id": "d1", "name": "Phone", "type": "Smartphone",
             "is_active": True, "volume_percent": 70}
        ]
    }
    result = await list_devices(ctx)
    assert len(result.devices) == 1
    assert result.devices[0].name == "Phone"
    assert result.devices[0].is_active is True


async def test_transfer_playback(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    result = await transfer_playback("d1", ctx=ctx)
    args, kwargs = fake_spotify.last_call("transfer_playback")
    assert args[0] == "d1"
    assert kwargs["force_play"] is True
    assert result.status == "success"


async def test_get_queue(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["queue"] = {
        "currently_playing": copy.deepcopy(TRACK),
        "queue": [copy.deepcopy(TRACK)],
    }
    state = await get_queue(ctx)
    assert state.currently_playing is not None
    assert len(state.queue) == 1


async def test_add_to_queue_builds_a_track_uri(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    await add_to_queue("abc", ctx=ctx)
    args, _kwargs = fake_spotify.last_call("add_to_queue")
    assert args[0] == "spotify:track:abc"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_playback.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.tools.playback'`

- [ ] **Step 4: Write `spotify_mcp_mx/tools/playback.py`**

Port these six tools from `REF_SPOTIFY/src/spotify_mcp/fastmcp_server.py`, applying the five transformation rules above. Source line ranges:

| Tool | Reference lines | Notes |
|---|---|---|
| `get_playback_state` | 434–453 | keep the `_playback_state(client)` helper, taking the client as a parameter |
| `control_playback` | 455–532 | keep every validation message verbatim; returns `_playback_state(client)` |
| `list_devices` | 535–566 | |
| `transfer_playback` | 568–592 | |
| `get_queue` | 724–753 | |
| `add_to_queue` | 697–722 | change the hardcoded `f"spotify:track:{track_id}"` to `to_uri("track", track_id)` so URIs and URLs are accepted, consistent with every other tool |

The module-private helper:

```python
def _playback_state(client: spotipy.Spotify) -> PlaybackState:
    """Read the current playback state into our model."""
    result = client.current_playback()
    device = (result or {}).get("device") or {}
    return PlaybackState(
        is_playing=result.get("is_playing", False) if result else False,
        track=parse_track(result["item"]) if result and result.get("item") else None,
        device=device.get("name"),
        volume=device.get("volume_percent"),
        shuffle=result.get("shuffle_state", False) if result else False,
        repeat=result.get("repeat_state", "off") if result else "off",
        progress_ms=result.get("progress_ms") if result else None,
    )
```

- [ ] **Step 5: Register the module**

`spotify_mcp_mx/tools/__init__.py`:

```python
"""Tool modules. Importing this package registers every tool on the server."""

from __future__ import annotations

from . import playback  # noqa: F401  - imported for its registration side effect

__all__ = ["playback"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_playback.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (16 tests), linters clean

- [ ] **Step 7: Commit**

```bash
git add spotify_mcp_mx/tools tests/conftest.py tests/test_tools_playback.py
git commit -m "feat: add the six playback tools"
```

---

### Task 10: Catalog tools

**Files:**
- Create: `spotify_mcp_mx/tools/catalog.py`
- Modify: `spotify_mcp_mx/tools/__init__.py`
- Test: `tests/test_tools_catalog.py`

**Interfaces:**
- Consumes: Task 8's harness, Task 5's `parse_track`/`parse_artist`/`parse_album`, Task 4's `SearchResults`, `TrackList`, `ArtistInfo`, `AlbumInfo`, `Track`.
- Produces: tools `search_music`, `get_track_info`, `get_artist_info`, `get_album_info`.

- [ ] **Step 1: Write the failing test**

`tests/test_tools_catalog.py`:

```python
from __future__ import annotations

import copy

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.catalog import (
    get_album_info,
    get_artist_info,
    get_track_info,
    search_music,
)
from tests.conftest import FakeCtx, FakeSpotify
from tests.fixtures import ALBUM, ARTIST, TRACK


async def test_search_music_composes_filter_syntax(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {"tracks": {"items": [], "total": 0}}
    await search_music("love", year="2024", genre="pop", artist="Prince", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("search")
    assert kwargs["q"] == "love artist:Prince year:2024 genre:pop"


async def test_search_music_year_range_uses_the_year_filter(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {"tracks": {"items": [], "total": 0}}
    await search_music("love", year_range="2020-2024", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("search")
    assert kwargs["q"] == "love year:2020-2024"


@pytest.mark.parametrize(("given", "sent"), [(0, 1), (-5, 1), (999, 50), (25, 25)])
async def test_search_music_clamps_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx, given: int, sent: int
) -> None:
    fake_spotify.responses["search"] = {"tracks": {"items": [], "total": 0}}
    await search_music("x", limit=given, ctx=ctx)
    _args, kwargs = fake_spotify.last_call("search")
    assert kwargs["limit"] == sent


async def test_search_music_returns_tracks_and_pagination(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {
        "tracks": {
            "items": [copy.deepcopy(TRACK), None],
            "total": 812,
            "limit": 10,
            "offset": 20,
            "next": "https://api.spotify.com/next",
            "previous": None,
        }
    }
    results = await search_music("radiohead", offset=20, ctx=ctx)
    assert len(results.items) == 1  # the null entry is skipped
    assert results.total == 812
    assert results.offset == 20
    assert results.next is not None


async def test_search_music_coerces_artists_into_track_shape(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["search"] = {
        "artists": {"items": [{"name": "Radiohead", "id": "abc"}], "total": 1}
    }
    results = await search_music("radiohead", qtype="artist", ctx=ctx)
    assert results.items[0].name == "Radiohead"
    assert results.items[0].artist == "Radiohead"


async def test_get_track_info_single_id_uses_the_single_endpoint(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["track"] = copy.deepcopy(TRACK)
    result = await get_track_info("6bMDnAdV1bhrbmwmuHRk9c", ctx=ctx)
    assert fake_spotify.called("track")
    assert not fake_spotify.called("tracks")
    assert len(result.tracks) == 1


async def test_get_track_info_batches_above_one_id(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["tracks"] = {"tracks": [copy.deepcopy(TRACK), None]}
    result = await get_track_info(["a", "b"], ctx=ctx)
    assert fake_spotify.called("tracks")
    assert len(result.tracks) == 1


async def test_get_track_info_rejects_more_than_fifty(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await get_track_info([f"id-{i}" for i in range(51)], ctx=ctx)
    assert str(excinfo.value) == "Maximum 50 track IDs per request (Spotify API limit)"


async def test_get_artist_info_truncates_to_ten_top_tracks(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["artist"] = copy.deepcopy(ARTIST)
    fake_spotify.responses["artist_top_tracks"] = {
        "tracks": [copy.deepcopy(TRACK) for _ in range(15)]
    }
    info = await get_artist_info("4Z8W4fKeB5YxbusRsdQVPb", ctx=ctx)
    assert info.artist.name == "Radiohead"
    assert len(info.top_tracks) == 10


async def test_get_album_info_backfills_the_album_on_each_track(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["album"] = copy.deepcopy(ALBUM)
    info = await get_album_info("6GjwtEZcfenmOf6l18N7T7", ctx=ctx)
    assert info.album.label == "XL Recordings"
    # Album track items carry no album of their own; it is filled from the parent.
    assert info.tracks[0].album == "Kid A"
    assert info.tracks[0].album_id == "6GjwtEZcfenmOf6l18N7T7"
    assert info.tracks[0].release_date == "2000-10-02"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.tools.catalog'`

- [ ] **Step 3: Write `spotify_mcp_mx/tools/catalog.py`**

Port these four tools, applying the five transformation rules. Source line ranges:

| Tool | Reference lines |
|---|---|
| `search_music` | 594–695 |
| `get_track_info` | 755–794 |
| `get_artist_info` | 796–831 |
| `get_album_info` | 1246–1302 |

Use `parse_artist` and `parse_album` from Task 5 in place of the reference's inline `Artist(...)` and `Album(...)` construction — the field mapping is identical.

- [ ] **Step 4: Register the module**

Add `catalog` to the import list and `__all__` in `spotify_mcp_mx/tools/__init__.py`:

```python
from . import catalog, playback  # noqa: F401  - imported for registration side effects

__all__ = ["catalog", "playback"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_catalog.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (14 tests), linters clean

- [ ] **Step 6: Commit**

```bash
git add spotify_mcp_mx/tools/catalog.py spotify_mcp_mx/tools/__init__.py tests/test_tools_catalog.py
git commit -m "feat: add the four catalog tools"
```

---

### Task 11: Library and history tools

**Files:**
- Create: `spotify_mcp_mx/tools/library.py`
- Modify: `spotify_mcp_mx/tools/__init__.py`
- Test: `tests/test_tools_library.py`

**Interfaces:**
- Consumes: Task 8's harness; Task 7's `save_tracks`, `remove_saved_tracks` (both take `scope`); Task 4's `UserProfile`, `SavedTracks`, `TopItems`, `RecentlyPlayed`, `ActionResult`.
- Produces: tools `get_me`, `get_saved_tracks`, `save_tracks`, `remove_saved_tracks`, `get_top_items`, `get_recently_played`.

**Naming note:** the tools `save_tracks` and `remove_saved_tracks` share their names with the `spotify_api` helpers they call. Import the module, not the names — `from .. import spotify_api` then `spotify_api.save_tracks(client, scope, track_ids)` — to avoid shadowing. This module also needs `from ..parsing import parse_artist, parse_track` and `from ..models import ActionResult, RecentlyPlayed, SavedTracks, TopItems, UserProfile`.

- [ ] **Step 1: Write the failing test**

`tests/test_tools_library.py`:

```python
from __future__ import annotations

import copy

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.library import (
    get_me,
    get_recently_played,
    get_saved_tracks,
    get_top_items,
    remove_saved_tracks,
    save_tracks,
)
from tests.conftest import FakeCtx, FakeSpotify
from tests.fixtures import ARTIST, TRACK


async def test_get_me_maps_the_profile(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["current_user"] = {
        "id": "maksym",
        "display_name": "Maksym",
        "followers": {"total": 12},
    }
    profile = await get_me(ctx)
    assert profile.id == "maksym"
    assert profile.display_name == "Maksym"
    assert profile.followers == 12


async def test_get_me_tolerates_a_stripped_profile(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    # The restricted regime returns id only; that must not be an error.
    fake_spotify.responses["current_user"] = {"id": "maksym"}
    profile = await get_me(ctx)
    assert profile.email is None
    assert profile.country is None
    assert profile.product is None


async def test_get_saved_tracks_populates_added_at(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_saved_tracks"] = {
        "items": [{"added_at": "2026-01-02T03:04:05Z", "track": copy.deepcopy(TRACK)}, None],
        "total": 900,
        "limit": 20,
        "offset": 0,
    }
    page = await get_saved_tracks(ctx=ctx)
    assert len(page.items) == 1
    assert page.items[0].added_at == "2026-01-02T03:04:05Z"
    assert page.total == 900


async def test_get_saved_tracks_clamps_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_saved_tracks"] = {"items": [], "total": 0}
    await get_saved_tracks(limit=500, ctx=ctx)
    _args, kwargs = fake_spotify.last_call("current_user_saved_tracks")
    assert kwargs["limit"] == 50


async def test_save_tracks_delegates_with_the_caller_scope(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.save_tracks",
        lambda client, scope, ids: seen.update(scope=scope, ids=ids),
    )
    result = await save_tracks(["abc"], ctx=ctx)
    assert seen["scope"] == "id-1"
    assert seen["ids"] == ["abc"]
    assert result.status == "success"


async def test_save_tracks_rejects_more_than_fifty(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await save_tracks([f"id-{i}" for i in range(51)], ctx=ctx)
    assert str(excinfo.value) == "Maximum 50 track IDs per request (Spotify API limit)"


async def test_remove_saved_tracks_rejects_more_than_fifty(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError):
        await remove_saved_tracks([f"id-{i}" for i in range(51)], ctx=ctx)


async def test_get_top_items_tracks(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["current_user_top_tracks"] = {"items": [copy.deepcopy(TRACK)]}
    result = await get_top_items(ctx=ctx)
    assert result.time_range == "medium_term"
    assert result.tracks is not None and len(result.tracks) == 1
    assert result.artists is None


async def test_get_top_items_artists(fake_spotify: FakeSpotify, ctx: FakeCtx) -> None:
    fake_spotify.responses["current_user_top_artists"] = {"items": [copy.deepcopy(ARTIST)]}
    result = await get_top_items(item_type="artists", ctx=ctx)
    assert result.artists is not None and result.artists[0].name == "Radiohead"
    assert result.tracks is None


async def test_get_top_items_validates_item_type(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await get_top_items(item_type="albums", ctx=ctx)
    assert str(excinfo.value) == "item_type must be 'tracks' or 'artists'"


async def test_get_top_items_validates_time_range(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await get_top_items(time_range="forever", ctx=ctx)
    assert str(excinfo.value) == (
        "time_range must be 'short_term', 'medium_term' or 'long_term'"
    )


async def test_get_recently_played_populates_played_at(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_recently_played"] = {
        "items": [{"played_at": "2026-08-30T10:00:00Z", "track": copy.deepcopy(TRACK)}]
    }
    result = await get_recently_played(ctx=ctx)
    assert result.items[0].played_at == "2026-08-30T10:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_library.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.tools.library'`

- [ ] **Step 3: Write `spotify_mcp_mx/tools/library.py`**

Port these six tools, applying the five transformation rules. Source line ranges:

| Tool | Reference lines | Notes |
|---|---|---|
| `get_me` | 389–432 | |
| `get_saved_tracks` | 1304–1347 | |
| `save_tracks` | 1349–1377 | calls `spotify_api.save_tracks(client, scope, track_ids)` |
| `remove_saved_tracks` | 1379–1407 | calls `spotify_api.remove_saved_tracks(client, scope, track_ids)` |
| `get_top_items` | 1472–1535 | use `parse_artist` for the artists branch |
| `get_recently_played` | 1437–1470 | |

- [ ] **Step 4: Register the module**

```python
from . import catalog, library, playback  # noqa: F401  - registration side effects

__all__ = ["catalog", "library", "playback"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_library.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (12 tests), linters clean

- [ ] **Step 6: Commit**

```bash
git add spotify_mcp_mx/tools/library.py spotify_mcp_mx/tools/__init__.py tests/test_tools_library.py
git commit -m "feat: add the six library and history tools"
```

---

### Task 12: Playlist tools

**Files:**
- Create: `spotify_mcp_mx/tools/playlists.py`
- Modify: `spotify_mcp_mx/tools/__init__.py`
- Test: `tests/test_tools_playlists.py`

**Interfaces:**
- Consumes: Task 8's harness; all of Task 7's playlist helpers (each taking `scope`); Task 4's `Playlist`, `PlaylistList`, `PlaylistTracks`, `ActionResult`; Task 5's `parse_playlist`, `parse_track`.
- Produces: tools `get_user_playlists`, `get_playlist_info`, `get_playlist_tracks`, `create_playlist`, `modify_playlist_details`, `add_tracks_to_playlist`, `remove_tracks_from_playlist`, `reorder_playlist_tracks`, `unfollow_playlist`.

**`get_playlist_tracks` is the one tool that is not a single `run_tool` closure.** It reports progress between pages, so the page loop lives in the async function and each page is its own `run_tool` call. Full implementation is given in Step 4 — do not try to derive it from the reference.

- [ ] **Step 1: Write the failing test**

`tests/test_tools_playlists.py`:

```python
from __future__ import annotations

import copy
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from spotify_mcp_mx.tools.playlists import (
    add_tracks_to_playlist,
    create_playlist,
    get_playlist_info,
    get_playlist_tracks,
    get_user_playlists,
    modify_playlist_details,
    remove_tracks_from_playlist,
    reorder_playlist_tracks,
    unfollow_playlist,
)
from tests.conftest import FakeCtx, FakeSpotify
from tests.fixtures import PLAYLIST, TRACK


async def test_get_user_playlists_maps_and_paginates(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_playlists"] = {
        "items": [copy.deepcopy(PLAYLIST)],
        "total": 62,
        "limit": 20,
        "offset": 0,
        "next": "https://api.spotify.com/next",
    }
    page = await get_user_playlists(ctx=ctx)
    assert page.items[0].name == "Late Night"
    assert page.items[0].owner == "maksym"
    assert page.total == 62
    assert page.next is not None


async def test_get_user_playlists_clamps_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["current_user_playlists"] = {"items": [], "total": 0}
    await get_user_playlists(limit=0, ctx=ctx)
    _args, kwargs = fake_spotify.last_call("current_user_playlists")
    assert kwargs["limit"] == 1


async def test_get_playlist_info_requests_only_metadata_fields(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    fake_spotify.responses["playlist"] = copy.deepcopy(PLAYLIST)
    info = await get_playlist_info("37i9dQZF1DX4sWSpwq3LiO", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("playlist")
    assert kwargs["fields"] == "id,name,description,owner,public,tracks.total"
    assert info.total_tracks == 148
    assert info.tracks is None


async def test_get_playlist_tracks_pages_and_reports_progress(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_spotify.responses["playlist"] = {"tracks": {"total": 150}}

    def pages(client: Any, scope: str, playlist_id: str, *, limit: int, offset: int) -> Any:
        remaining = max(0, 150 - offset)
        count = min(limit, remaining)
        return {
            "items": [{"item": copy.deepcopy(TRACK)} for _ in range(count)],
            "next": "more" if offset + count < 150 else None,
        }

    monkeypatch.setattr("spotify_mcp_mx.spotify_api.playlist_items", pages)

    result = await get_playlist_tracks("37i9", ctx=ctx)
    assert result.returned == 150
    assert result.total == 150
    assert len(result.items) == 150
    # One progress report per page: 100 then 150.
    assert ctx.progress == [(100.0, 150.0), (150.0, 150.0)]


async def test_get_playlist_tracks_reads_the_legacy_track_key(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_spotify.responses["playlist"] = {"tracks": {"total": 1}}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.playlist_items",
        lambda *a, **k: {"items": [{"track": copy.deepcopy(TRACK)}], "next": None},
    )
    result = await get_playlist_tracks("37i9", ctx=ctx)
    assert result.items[0].name == "Idioteque"


async def test_get_playlist_tracks_honours_limit(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_spotify.responses["playlist"] = {"tracks": {"total": 500}}
    seen: list[int] = []

    def pages(client: Any, scope: str, pid: str, *, limit: int, offset: int) -> Any:
        seen.append(limit)
        return {"items": [{"item": copy.deepcopy(TRACK)} for _ in range(limit)], "next": "m"}

    monkeypatch.setattr("spotify_mcp_mx.spotify_api.playlist_items", pages)
    result = await get_playlist_tracks("37i9", limit=30, ctx=ctx)
    assert result.returned == 30
    assert seen == [30]


async def test_create_playlist(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.create_playlist",
        lambda client, scope, name, description, public: {
            "id": "new1",
            "name": name,
            "description": description,
            "public": public,
            "owner": {"display_name": "maksym"},
        },
    )
    playlist = await create_playlist("Focus", description="deep work", public=False, ctx=ctx)
    assert playlist.id == "new1"
    assert playlist.name == "Focus"
    assert playlist.total_tracks == 0


async def test_modify_playlist_details_requires_a_field(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await modify_playlist_details("37i9", ctx=ctx)
    assert str(excinfo.value) == (
        "At least one of name, description, or public must be provided"
    )


async def test_modify_playlist_details_passes_fields_through(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    result = await modify_playlist_details("37i9", name="Renamed", ctx=ctx)
    _args, kwargs = fake_spotify.last_call("playlist_change_details")
    assert kwargs["name"] == "Renamed"
    assert result.status == "success"


async def test_add_tracks_normalises_to_uris(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.playlist_add_items",
        lambda client, scope, pid, uris: seen.update(uris=uris) or {"snapshot_id": "s1"},
    )
    result = await add_tracks_to_playlist("37i9", ["abc", "spotify:track:def"], ctx=ctx)
    assert seen["uris"] == ["spotify:track:abc", "spotify:track:def"]
    assert result.snapshot_id == "s1"


async def test_remove_tracks_removes_without_confirming(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Elicitation is out of scope; the destructive_hint annotation is what tells
    # clients to confirm. The tool itself must simply perform the removal.
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "spotify_mcp_mx.spotify_api.playlist_remove_items",
        lambda client, scope, pid, uris: seen.update(uris=uris) or {"snapshot_id": "s2"},
    )
    result = await remove_tracks_from_playlist("37i9", ["abc"], ctx=ctx)
    assert seen["uris"] == ["spotify:track:abc"]
    assert result.status == "success"
    assert result.snapshot_id == "s2"


async def test_reorder_validates_positions(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await reorder_playlist_tracks("37i9", range_start=-1, insert_before=3, ctx=ctx)
    assert str(excinfo.value) == "range_start and insert_before must be >= 0"


async def test_reorder_validates_range_length(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await reorder_playlist_tracks(
            "37i9", range_start=0, insert_before=3, range_length=0, ctx=ctx
        )
    assert str(excinfo.value) == "range_length must be >= 1"


async def test_reorder_passes_every_argument(
    fake_spotify: FakeSpotify, ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def reorder(client: Any, scope: str, pid: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return {"snapshot_id": "s3"}

    monkeypatch.setattr("spotify_mcp_mx.spotify_api.playlist_reorder_items", reorder)
    await reorder_playlist_tracks(
        "37i9", range_start=0, insert_before=10, range_length=3, snapshot_id="old", ctx=ctx
    )
    assert seen == {
        "range_start": 0,
        "insert_before": 10,
        "range_length": 3,
        "snapshot_id": "old",
    }


async def test_unfollow_playlist_normalises_the_id(
    fake_spotify: FakeSpotify, ctx: FakeCtx
) -> None:
    result = await unfollow_playlist("spotify:playlist:37i9", ctx=ctx)
    args, _kwargs = fake_spotify.last_call("current_user_unfollow_playlist")
    assert args[0] == "37i9"
    assert result.status == "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_playlists.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.tools.playlists'`

- [ ] **Step 3: Port the eight straightforward playlist tools**

This module needs more than the shared header. Use exactly this preamble:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from .. import spotify_api
from ..logging_utils import log_pagination_info, log_tool_execution
from ..models import ActionResult, Playlist, PlaylistList, PlaylistTracks, Track
from ..parsing import parse_playlist, parse_track
from ..server import SPOTIFY_ICON, mcp, run_tool
from ..utils import to_id, to_uri

if TYPE_CHECKING:
    import spotipy

logger = logging.getLogger(__name__)
```

**Import the `spotify_api` module, never its names.** Every call is written
`spotify_api.playlist_add_items(client, scope, ...)`. Binding the functions
directly (`from ..spotify_api import playlist_add_items`) would freeze the
reference at import time and break both the tests' monkeypatching and any
future wrapping.

Apply the five transformation rules. Source line ranges:

| Tool | Reference lines | Notes |
|---|---|---|
| `get_user_playlists` | 951–1008 | use `parse_playlist` |
| `get_playlist_info` | 833–874 | use `parse_playlist`; keep the `fields=` string exactly |
| `create_playlist` | 876–916 | `spotify_api.create_playlist(client, scope, ...)`; result keeps `tracks=[]`, `total_tracks=0` |
| `modify_playlist_details` | 1129–1179 | |
| `add_tracks_to_playlist` | 918–949 | `spotify_api.playlist_add_items(client, scope, ...)` |
| `remove_tracks_from_playlist` | 1070–1127 | **drop the elicitation block entirely** (the `ctx.session.check_client_capability` / `ctx.elicit` section) — keep only the `to_uri` normalisation, the `playlist_remove_items` call and the `ActionResult` |
| `reorder_playlist_tracks` | 1181–1244 | `spotify_api.playlist_reorder_items(client, scope, ...)` |
| `unfollow_playlist` | 1409–1435 | |

Keep `destructive_hint=True` on `remove_tracks_from_playlist`, `modify_playlist_details`, `reorder_playlist_tracks` and `unfollow_playlist`.

- [ ] **Step 4: Write `get_playlist_tracks` and its page loop**

```python
# Spotify's playlist-items endpoint caps a page at 100.
_PAGE_SIZE = 100

# Stop runaway pagination on a playlist that keeps reporting a next page.
_MAX_OFFSET = 10_000


@mcp.tool(
    title="Get Playlist Tracks",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=True
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_playlist_tracks(
    playlist_id: str,
    limit: int | None = None,
    offset: int = 0,
    ctx: Context | None = None,
) -> PlaylistTracks:
    """Get tracks from a playlist with full pagination support.

    Args:
        playlist_id: Playlist ID
        limit: Max tracks to return (None for all tracks, up to a 10,000 safety limit)
        offset: Number of tracks to skip for pagination (default 0)

    Returns:
        PlaylistTracks with 'items' (list of tracks), 'total', 'limit', 'offset'

    Note: Large playlists require pagination. Use limit/offset to get specific ranges:
    - Get first 100: limit=100, offset=0
    - Get next 100: limit=100, offset=100
    - Get all tracks: limit=None (use with caution on very large playlists)
    """
    if ctx is None:  # pragma: no cover - the SDK always injects a Context
        raise ValueError("get_playlist_tracks requires a request context")

    # Fetch the total up front so progress notifications have a denominator.
    def read_total(client: spotipy.Spotify, scope: str) -> int | None:
        info = client.playlist(playlist_id, fields="tracks.total")
        total: int | None = (info.get("tracks") or {}).get("total")
        return total

    total_tracks = await run_tool(ctx, read_total)

    tracks: list[Track] = []
    current_offset = offset
    remaining = limit

    while True:
        batch_limit = min(_PAGE_SIZE, remaining) if remaining else _PAGE_SIZE

        def read_page(
            client: spotipy.Spotify, scope: str, _at: int = current_offset, _n: int = batch_limit
        ) -> dict[str, Any]:
            page: dict[str, Any] = spotify_api.playlist_items(
                client, scope, playlist_id, limit=_n, offset=_at
            )
            return page or {}

        result = await run_tool(ctx, read_page)
        items = result.get("items") or []
        if not items:
            break

        # Restricted-regime entries key the track off `item`, legacy off `track`.
        batch = [
            parse_track(track)
            for entry in items
            if entry and (track := (entry.get("item") or entry.get("track")))
        ]
        tracks.extend(batch)

        await ctx.report_progress(progress=len(tracks), total=total_tracks)
        await ctx.info(f"Fetched {len(tracks)} tracks so far")

        if remaining:
            remaining -= len(batch)
            if remaining <= 0:
                break

        if len(items) < batch_limit or not result.get("next"):
            break

        current_offset += len(items)
        if current_offset > _MAX_OFFSET:
            logger.warning("Safety limit reached: stopping at offset %d", current_offset)
            break

    if total_tracks is None:
        total_tracks = len(tracks)

    log_pagination_info("get_playlist_tracks", total_tracks, limit, offset)

    return PlaylistTracks(
        items=tracks,
        total=total_tracks,
        limit=limit,
        offset=offset,
        returned=len(tracks),
    )
```

The `_at` and `_n` default arguments bind the loop variables at closure creation — without them every page would read the final values of `current_offset` and `batch_limit`.

- [ ] **Step 5: Register the module**

```python
from . import catalog, library, playback, playlists  # noqa: F401  - registration side effects

__all__ = ["catalog", "library", "playback", "playlists"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_playlists.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (16 tests), linters clean

- [ ] **Step 7: Verify all 25 tools are registered**

Run:

```bash
uv run python -c "
import asyncio, spotify_mcp_mx.tools
from spotify_mcp_mx.server import mcp
tools = asyncio.run(mcp.list_tools())
print(len(tools)); print(sorted(t.name for t in tools))
"
```

Expected: `25`, and the sorted list matches the spec's tool inventory.

- [ ] **Step 8: Commit**

```bash
git add spotify_mcp_mx/tools/playlists.py spotify_mcp_mx/tools/__init__.py tests/test_tools_playlists.py
git commit -m "feat: add the nine playlist tools"
```

---

### Task 13: ASGI app and entrypoint

**Files:**
- Create: `spotify_mcp_mx/app.py`, `spotify_mcp_mx/__main__.py`
- Test: `tests/test_server_http.py`

**Interfaces:**
- Consumes: Task 8's `mcp`, Task 12's fully registered tool set.
- Produces: `create_app(host: str | None = None) -> Starlette`, `default_host() -> str`, `default_port() -> int`, `main() -> None`.

- [ ] **Step 1: Write the failing test**

`tests/test_server_http.py`:

```python
from __future__ import annotations

import httpx
import pytest

from spotify_mcp_mx import __version__
from spotify_mcp_mx.app import create_app, default_host, default_port


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = create_app("0.0.0.0")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health_is_unauthenticated(client: httpx.AsyncClient) -> None:
    async with client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_root_names_the_required_headers(client: httpx.AsyncClient) -> None:
    async with client:
        response = await client.get("/")
    body = response.json()
    assert response.status_code == 200
    assert body["endpoints"]["streamable_http"] == "/mcp"
    assert body["endpoints"]["sse"] == "/sse"
    assert "X-Spotify-Client-Id" in body["authentication"]
    assert "X-Spotify-Refresh-Token" in body["authentication"]
    assert "stores no credentials" in body["authentication"]


def test_both_transports_are_mounted() -> None:
    paths = {getattr(route, "path", None) for route in create_app("0.0.0.0").routes}
    assert "/health" in paths
    assert "/" in paths
    assert any(p and p.startswith("/sse") for p in paths)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert default_host() == "0.0.0.0"
    assert default_port() == 6402


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")
    assert default_host() == "127.0.0.1"
    assert default_port() == 9000


async def test_tools_are_listed_over_the_streamable_transport() -> None:
    """End-to-end: a real MCP client over the real transport sees all 25 tools."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    import uvicorn

    config = uvicorn.Config(
        create_app("127.0.0.1"), host="127.0.0.1", port=6499, log_level="warning"
    )
    server = uvicorn.Server(config)

    import anyio

    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        while not server.started:
            await anyio.sleep(0.05)
        try:
            async with streamablehttp_client("http://127.0.0.1:6499/mcp") as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
            assert len(tools) == 25
            assert {"get_me", "search_music", "get_playlist_tracks"} <= {t.name for t in tools}
        finally:
            server.should_exit = True


async def test_a_tool_call_without_credentials_names_the_headers() -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    import anyio
    import uvicorn

    config = uvicorn.Config(
        create_app("127.0.0.1"), host="127.0.0.1", port=6498, log_level="warning"
    )
    server = uvicorn.Server(config)

    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        while not server.started:
            await anyio.sleep(0.05)
        try:
            async with streamablehttp_client("http://127.0.0.1:6498/mcp") as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    result = await session.call_tool("get_me", {})
            assert result.isError
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            assert "X-Spotify-Refresh-Token" in text
            assert "[missing_credentials]" in text
        finally:
            server.should_exit = True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.app'`

- [ ] **Step 3: Write `spotify_mcp_mx/app.py`**

```python
"""The ASGI application: both MCP transports plus a health check.

Routes:
    ``/mcp``        Streamable HTTP transport (current MCP standard)
    ``/sse``        Legacy SSE transport, with ``/messages/`` for client posts
    ``/health``     Unauthenticated liveness probe for Coolify
    ``/``           Short service description
"""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from . import tools as _tools  # noqa: F401  - imported to register all 25 tools
from .auth import CLIENT_ID_HEADER, CLIENT_SECRET_HEADER, REFRESH_TOKEN_HEADER
from .server import mcp

__all__ = ["create_app", "default_host", "default_port"]


def default_host() -> str:
    return os.environ.get("HOST", "0.0.0.0")


def default_port() -> int:
    return int(os.environ.get("PORT", "6402"))


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Liveness probe. Deliberately unauthenticated so Coolify can poll it."""
    return JSONResponse({"status": "ok", "version": __version__})


@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "name": "spotify-mcp-mx",
            "version": __version__,
            "description": "MCP server for the Spotify Web API.",
            "endpoints": {"streamable_http": "/mcp", "sse": "/sse", "health": "/health"},
            "authentication": (
                f"Send your own Spotify credentials in the {CLIENT_ID_HEADER}, "
                f"{CLIENT_SECRET_HEADER} and {REFRESH_TOKEN_HEADER} headers on every "
                "request. This server stores no credentials."
            ),
        }
    )


def create_app(host: str | None = None) -> Starlette:
    """Build the ASGI app serving both MCP transports from one process.

    ``streamable_http_app()`` owns the lifespan that runs the session manager,
    so it is the base app. The SSE routes are self-contained (each connection
    runs its own server loop, no lifespan needed), so they can simply be
    appended.

    ``host`` is passed to the SDK only so it can decide about DNS-rebinding
    protection: the SDK auto-enables a localhost-only Host/Origin allowlist when
    told it is serving loopback. Behind Coolify's proxy the request arrives with
    the public domain in Host, which such an allowlist would reject, so the
    default bind address of 0.0.0.0 correctly leaves it off.
    """
    host = host or default_host()

    # Stateless: no session pins a client to one worker, which matters because
    # the caller's credentials travel on every request anyway. Coolify can
    # restart or scale the container without breaking in-flight clients.
    app = mcp.streamable_http_app(stateless_http=True, host=host)

    mounted = {getattr(route, "path", None) for route in app.routes}
    for route in mcp.sse_app(host=host).routes:
        if getattr(route, "path", None) not in mounted:
            app.router.routes.append(route)

    return app
```

- [ ] **Step 4: Write `spotify_mcp_mx/__main__.py`**

```python
"""Run the MCP server under uvicorn."""

from __future__ import annotations

import logging

import uvicorn

from .app import create_app, default_host, default_port


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    host, port = default_host(), default_port()
    logging.getLogger(__name__).info(
        "Serving MCP on http://%s:%d/mcp (SSE at /sse)", host, port
    )
    uvicorn.run(create_app(host), host=host, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_server_http.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (8 tests), linters clean

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -m "not live"`
Expected: all tests pass

- [ ] **Step 7: Smoke-test the real server**

```bash
uv run python -m spotify_mcp_mx &
sleep 3 && curl -sf localhost:6402/health && curl -s localhost:6402/ | head -c 400
kill %1
```

Expected: `{"status": "ok", ...}` then the service description.

- [ ] **Step 8: Commit**

```bash
git add spotify_mcp_mx/app.py spotify_mcp_mx/__main__.py tests/test_server_http.py
git commit -m "feat: serve both MCP transports plus health and description routes"
```

---

### Task 14: Local authorization helper

**Files:**
- Create: `spotify_mcp_mx/authorize.py`
- Test: `tests/test_authorize.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SCOPES: list[str]`, `build_authorize_url(client_id, redirect_uri, state) -> str`, `exchange_code(client_id, client_secret, redirect_uri, code) -> str` (returns the refresh token), `main() -> None`.

This runs on the user's own machine, never on the server. It is the only place a browser OAuth flow appears, and it is excluded from the Docker image.

- [ ] **Step 1: Write the failing test**

`tests/test_authorize.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_authorize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spotify_mcp_mx.authorize'`

- [ ] **Step 3: Write `spotify_mcp_mx/authorize.py`**

```python
"""One-time local helper that mints a Spotify refresh token.

Run this on your own machine. It never runs on the server and is excluded from
the Docker image. It prints the three headers to paste into your MCP client and
writes nothing to disk.

    uv run python -m spotify_mcp_mx.authorize
"""

from __future__ import annotations

import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from typing import Any

import requests

__all__ = ["SCOPES", "build_authorize_url", "exchange_code", "main"]

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"  # nosec B105 - a URL, not a secret

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888"

# The same 16 scopes the reference server requests, so the minted token can
# drive every one of the 25 tools.
SCOPES = [
    # Playback
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-modify-playback-state",
    "app-remote-control",
    "streaming",
    # Playlists
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    # Library
    "user-library-read",
    "user-library-modify",
    # History
    "user-read-playback-position",
    "user-top-read",
    "user-read-recently-played",
    # Profile
    "user-read-private",
    "user-read-email",
]


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Spotify consent URL requesting every scope the tools need."""
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "scope": " ".join(SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    """Swap an authorization code for a long-lived refresh token."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=15,
    )
    payload: dict[str, Any] = response.json()
    if response.status_code != 200 or "refresh_token" not in payload:
        detail = payload.get("error_description") or payload.get("error") or "unknown error"
        sys.exit(f"Spotify rejected the authorization code ({response.status_code}): {detail}")
    return str(payload["refresh_token"])


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = (query.get("code") or [None])[0]
        _CallbackHandler.state = (query.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authorized. You can close this tab and return to the terminal.")

    def log_message(self, format: str, *args: Any) -> None:
        pass  # keep the terminal clean


def main() -> None:
    print("Create an app at https://developer.spotify.com/dashboard and add")
    print(f"redirect URI {DEFAULT_REDIRECT_URI} to it, then paste its credentials here.\n")

    client_id = input("Client ID: ").strip()
    client_secret = input("Client secret: ").strip()
    redirect_uri = input(f"Redirect URI [{DEFAULT_REDIRECT_URI}]: ").strip() or (
        DEFAULT_REDIRECT_URI
    )
    if not client_id or not client_secret:
        sys.exit("Client ID and secret are both required.")

    state = secrets.token_urlsafe(16)
    port = urllib.parse.urlparse(redirect_uri).port or 8888
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    url = build_authorize_url(client_id, redirect_uri, state)
    print("\nOpening your browser to approve access…")
    print(f"If it does not open, visit:\n{url}\n")
    webbrowser.open(url)

    thread.join(timeout=300)
    server.server_close()

    if _CallbackHandler.code is None:
        sys.exit("No authorization code received. Did the redirect URI match exactly?")
    if _CallbackHandler.state != state:
        sys.exit("State mismatch — aborting rather than trusting the callback.")

    refresh_token = exchange_code(
        client_id, client_secret, redirect_uri, _CallbackHandler.code
    )

    print("\nDone. Add these headers to your MCP client:\n")
    print(f"  X-Spotify-Client-Id:     {client_id}")
    print(f"  X-Spotify-Client-Secret: {client_secret}")
    print(f"  X-Spotify-Refresh-Token: {refresh_token}")
    print("\nThey are not saved anywhere — copy them now.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_authorize.py -v && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: PASS (4 tests), linters clean

- [ ] **Step 5: Commit**

```bash
git add spotify_mcp_mx/authorize.py tests/test_authorize.py
git commit -m "feat: add the local one-time refresh-token helper"
```

---

### Task 15: Container and Coolify deployment

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `DEPLOYMENT.md`

**Interfaces:**
- Consumes: Task 13's `python -m spotify_mcp_mx` entrypoint and `/health` route.
- Produces: a container listening on 6402 with a working healthcheck.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1

# ---- build ----------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Resolve dependencies from the lockfile first, in their own layer, so edits to
# application code do not invalidate the (slow) dependency install.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY spotify_mcp_mx ./spotify_mcp_mx
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime --------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=6402

RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app spotify_mcp_mx ./spotify_mcp_mx

# The local OAuth helper never runs on the server, so it is not shipped.
RUN rm -f ./spotify_mcp_mx/authorize.py

USER app
EXPOSE 6402

# Python-only healthcheck; the slim image ships no curl or wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/health\").read()"]

CMD ["python", "-m", "spotify_mcp_mx"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.venv/
__pycache__/
*.py[oc]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.git/
.env
tests/
docs/
*.md
!README.md
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
# Deployment target: Coolify (Docker Compose resource).
#
# There are deliberately NO secrets here. Each caller sends their own Spotify
# credentials in request headers, so the server holds none of its own.

services:
  spotify-mcp-mx:
    build:
      context: .
      dockerfile: Dockerfile
    image: spotify-mcp-mx:latest
    restart: unless-stopped
    environment:
      HOST: 0.0.0.0
      PORT: 6402
    ports:
      - "6402:6402"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - import urllib.request;urllib.request.urlopen("http://127.0.0.1:6402/health").read()
      interval: 30s
      timeout: 5s
      start_period: 10s
      retries: 3
```

- [ ] **Step 4: Write `.env.example`**

```bash
# The running server needs NO secrets: callers send their own Spotify
# credentials in request headers on every call. Do not set credentials here
# expecting the server to use them — it will not.

# Bind address and port (defaults shown).
HOST=0.0.0.0
PORT=6402

# Used ONLY by the opt-in live tests, which skip themselves when unset:
#   SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... SPOTIFY_REFRESH_TOKEN=... \
#     uv run pytest -m live
# Mint a refresh token with: uv run python -m spotify_mcp_mx.authorize
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REFRESH_TOKEN=
```

- [ ] **Step 5: Write `DEPLOYMENT.md`**

Adapt `REF_TFNSW/DEPLOYMENT.md`, substituting: service name `spotify-mcp-mx`, port `6402`, and the three Spotify headers in place of `X-API-Key`. Keep all five sections — *Setup*, *Why there are no secrets*, *Scaling and restarts*, *A note on Host header checks*, *Updating* — and these specifics:

- Coolify: **New Resource → Docker Compose**, pointed at this repository.
- Set no environment secrets; there are none.
- Assign a domain to the `spotify-mcp-mx` service on port **6402**.
- Health check path `/health`, port `6402`, deliberately unauthenticated.
- Verify with `curl -sf https://your-domain/health`.
- Note that rotating credentials is a client-side change needing no redeploy.
- Note the endpoint is publicly reachable by design: a caller without valid Spotify credentials just gets errors from Spotify, and there is no quota of the operator's to spend. Traefik basic-auth or an IP allowlist can front it if desired.
- Note that per-caller access-token caching is in-memory and derived, so a redeploy costs one extra token exchange per caller and nothing else.

- [ ] **Step 6: Build the image and verify the container serves health**

```bash
docker compose build
docker compose up -d
sleep 8
curl -sf localhost:6402/health && echo && curl -s localhost:6402/ | head -c 300
docker compose down
```

Expected: `{"status": "ok", "version": "0.1.0"}`, then the service description naming the three headers.

- [ ] **Step 7: Verify the helper is absent from the image**

```bash
docker compose build -q && docker run --rm --entrypoint python spotify-mcp-mx:latest \
  -c "import pathlib; print(pathlib.Path('/app/spotify_mcp_mx/authorize.py').exists())"
```

Expected: `False`

- [ ] **Step 8: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml .env.example DEPLOYMENT.md
git commit -m "feat: containerise and document the Coolify deployment"
```

---

### Task 16: README and tool-metadata parity test

**Files:**
- Create: `README.md`, `tests/test_tool_metadata.py`

**Interfaces:**
- Consumes: the 25 registered tools from Task 12.
- Produces: a README whose tool table is enforced by a test.

- [ ] **Step 1: Write the failing test**

`tests/test_tool_metadata.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

import spotify_mcp_mx.tools  # noqa: F401  - registers every tool
from spotify_mcp_mx.server import mcp

README = Path(__file__).resolve().parent.parent / "README.md"

EXPECTED = {
    "get_me",
    "search_music",
    "get_track_info",
    "get_artist_info",
    "get_album_info",
    "get_playback_state",
    "control_playback",
    "list_devices",
    "transfer_playback",
    "get_queue",
    "add_to_queue",
    "get_user_playlists",
    "get_playlist_info",
    "get_playlist_tracks",
    "create_playlist",
    "modify_playlist_details",
    "add_tracks_to_playlist",
    "remove_tracks_from_playlist",
    "reorder_playlist_tracks",
    "unfollow_playlist",
    "get_saved_tracks",
    "save_tracks",
    "remove_saved_tracks",
    "get_top_items",
    "get_recently_played",
}


async def _tools() -> list:
    return await mcp.list_tools()


async def test_exactly_the_expected_tools_are_registered() -> None:
    names = {tool.name for tool in await _tools()}
    assert names == EXPECTED


async def test_every_tool_has_a_title_icon_and_annotations() -> None:
    for tool in await _tools():
        assert tool.title, f"{tool.name} has no title"
        assert tool.icons, f"{tool.name} has no icon"
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.open_world_hint is True, f"{tool.name} is not open-world"


async def test_every_tool_has_a_description_and_output_schema() -> None:
    for tool in await _tools():
        assert tool.description, f"{tool.name} has no description"
        assert tool.outputSchema, f"{tool.name} has no structured output schema"


async def test_ctx_is_not_exposed_as_a_tool_argument() -> None:
    """The SDK injects Context by annotation; it must never reach the wire schema."""
    for tool in await _tools():
        properties = (tool.inputSchema or {}).get("properties", {})
        assert "ctx" not in properties, f"{tool.name} exposes ctx as an argument"


async def test_destructive_tools_are_marked_destructive() -> None:
    destructive = {
        "remove_tracks_from_playlist",
        "modify_playlist_details",
        "reorder_playlist_tracks",
        "unfollow_playlist",
        "remove_saved_tracks",
    }
    by_name = {tool.name: tool for tool in await _tools()}
    for name in destructive:
        assert by_name[name].annotations.destructive_hint is True, f"{name} not destructive"


async def test_readme_tool_table_matches_the_registered_tools() -> None:
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", README.read_text(), re.MULTILINE))
    assert documented == EXPECTED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tool_metadata.py -v`
Expected: FAIL — README does not exist

- [ ] **Step 3: Write `README.md`**

Model it on `REF_TFNSW/README.md`. It must contain:

1. **Title and one-paragraph description**, naming both references.
2. **Authentication** — the three headers, that the server stores no credentials, that each call builds a client and drops it, that connections are pooled process-wide while credentials never are, and the `Authorization: Bearer` fallback described as testing-only. Include the minting command:
   ```bash
   uv run python -m spotify_mcp_mx.authorize
   ```
3. **Endpoints** table: `/mcp`, `/sse` + `/messages/`, `/health`, `/`. Note `0.0.0.0:6402` and the `HOST`/`PORT` overrides.
4. **Connecting a client**:
   - Claude Code:
     ```bash
     claude mcp add --transport http spotify https://your-host/mcp \
       --header "X-Spotify-Client-Id: YOUR_ID" \
       --header "X-Spotify-Client-Secret: YOUR_SECRET" \
       --header "X-Spotify-Refresh-Token: YOUR_TOKEN"
     ```
   - Claude Desktop: explain its native connector UI has no custom-header field, so it needs `mcp-remote`, with a full `mcpServers` JSON block using `--header "Name:${VAR}"` (no space after the colon) and an `env` block.
5. **Tools** — a table with exactly 25 rows in the format `| \`tool_name\` | What it does |`. The parity test parses this format, so it must match. Use the descriptions from the spec's tool inventory.
6. **Notes** — Premium is required for playback; IDs, `spotify:` URIs and `open.spotify.com` URLs are interchangeable; `get_playlist_tracks` positions are zero-based; batch limits (50 track IDs, 100 playlist adds); Spotify has withdrawn `/recommendations`, audio-features and related-artists.
7. **Running it** — `docker compose up --build -d`, `uv sync`, `uv run python -m spotify_mcp_mx`, `uv run pytest`, and the live-test command.
8. **Layout** table mapping each module to its role.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tool_metadata.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -m "not live" && uv run ruff check . && uv run mypy spotify_mcp_mx`
Expected: everything passes

- [ ] **Step 6: Commit**

```bash
git add README.md tests/test_tool_metadata.py
git commit -m "docs: add README with a tool table enforced by tests"
```

---

### Task 17: Live tests and CI

**Files:**
- Create: `tests/test_live.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: everything above.
- Produces: an opt-in live suite and a CI pipeline.

- [ ] **Step 1: Write `tests/test_live.py`**

```python
"""Smoke tests against the real Spotify API.

Opt-in: these skip themselves unless all three SPOTIFY_* variables are set, so
the default suite stays offline and CI is green without credentials.

    SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... SPOTIFY_REFRESH_TOKEN=... \
      uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN),
        reason="set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN",
    ),
]

HEADERS = {
    "X-Spotify-Client-Id": CLIENT_ID,
    "X-Spotify-Client-Secret": CLIENT_SECRET,
    "X-Spotify-Refresh-Token": REFRESH_TOKEN,
}


class LiveCtx:
    headers = HEADERS


async def test_real_token_exchange_and_profile() -> None:
    from spotify_mcp_mx.tools.library import get_me

    profile = await get_me(LiveCtx())
    assert profile.id


async def test_real_search_returns_tracks() -> None:
    from spotify_mcp_mx.tools.catalog import search_music

    results = await search_music("radiohead", limit=5, ctx=LiveCtx())
    assert results.items
    assert results.total > 0


async def test_second_call_reuses_the_cached_access_token() -> None:
    from spotify_mcp_mx.auth import _TOKEN_CACHE, reset_token_cache
    from spotify_mcp_mx.tools.library import get_me

    reset_token_cache()
    await get_me(LiveCtx())
    assert len(_TOKEN_CACHE) == 1
    await get_me(LiveCtx())
    assert len(_TOKEN_CACHE) == 1
```

- [ ] **Step 2: Verify the live tests skip cleanly without credentials**

Run: `env -u SPOTIFY_CLIENT_ID -u SPOTIFY_CLIENT_SECRET -u SPOTIFY_REFRESH_TOKEN uv run pytest -m live -v`
Expected: 3 skipped, 0 failed

- [ ] **Step 3: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
  pull_request:
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run mypy spotify_mcp_mx
      - run: uv run pytest -m "not live"

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build the image
        run: docker build -t spotify-mcp-mx:ci .
      - name: Start the container
        run: docker run -d --name mcp -p 6402:6402 spotify-mcp-mx:ci
      - name: Wait for /health
        run: |
          for i in $(seq 1 30); do
            if curl -sf localhost:6402/health; then echo; exit 0; fi
            sleep 2
          done
          echo "health check never came up"; docker logs mcp; exit 1
      - name: Assert all 25 tools are listed
        run: |
          uvx --from mcp python - <<'PY'
          import anyio
          from mcp import ClientSession
          from mcp.client.streamable_http import streamablehttp_client

          async def main() -> None:
              async with streamablehttp_client("http://localhost:6402/mcp") as (r, w, _):
                  async with ClientSession(r, w) as session:
                      await session.initialize()
                      tools = (await session.list_tools()).tools
              assert len(tools) == 25, f"expected 25 tools, got {len(tools)}"
              print(f"{len(tools)} tools listed")

          anyio.run(main)
          PY
      - name: Container logs on failure
        if: failure()
        run: docker logs mcp

  live:
    if: github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen
      # Skips itself when the secrets are absent, so this job is green without
      # them. Fork pull requests never receive secrets, so they always skip.
      - run: uv run pytest -m live
        env:
          SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
          SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
          SPOTIFY_REFRESH_TOKEN: ${{ secrets.SPOTIFY_REFRESH_TOKEN }}
```

- [ ] **Step 4: Run the full verification one last time**

```bash
uv run ruff check . && uv run mypy spotify_mcp_mx && uv run pytest -m "not live"
```

Expected: all clean, all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_live.py .github/workflows/ci.yml
git commit -m "ci: add lint, offline, docker and opt-in live jobs"
```

---

## Verification checklist

Run before declaring the work complete. Every line must be observed, not assumed.

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run mypy spotify_mcp_mx` exits 0
- [ ] `uv run pytest -m "not live"` — all pass
- [ ] `uv run pytest -m live` without credentials — all skip, none fail
- [ ] The server lists exactly **25** tools over the real streamable transport
- [ ] No tool exposes `ctx` in its input schema
- [ ] A tool call with no credential headers returns an error naming `X-Spotify-Refresh-Token` and carrying `[missing_credentials]`
- [ ] `grep -rn "SpotifyOAuth" spotify_mcp_mx/` returns nothing — no code path can write a `.cache` file
- [ ] `docker compose up --build -d` then `curl -sf localhost:6402/health` succeeds
- [ ] `authorize.py` is absent from the built image
- [ ] The README tool table has 25 rows and the parity test passes
