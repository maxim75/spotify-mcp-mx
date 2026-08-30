# Remote Spotify MCP Server — Design

**Date:** 2026-08-30
**Status:** Approved for planning

## Purpose

A remotely hosted MCP server that exposes the Spotify Web API over JSON-RPC, so
that one running instance serves many users, each with their own Spotify
credentials. The server itself holds no Spotify credentials.

Two existing servers define the target:

- [`jamiew/spotify-mcp`](https://github.com/jamiew/spotify-mcp) fixes **what**
  the server exposes: tool names, arguments, response models and error strings.
- [`maxim75/tfnsw_trip_planner_mcp`](https://github.com/maxim75/tfnsw_trip_planner_mcp)
  fixes **how** it is built, configured, deployed to Coolify and tested.

The two sit on different MCP SDK generations. This server follows the
deployment reference: `mcp` 2.x (`mcp.server.mcpserver.MCPServer`), not the
`mcp<2` `FastMCP` the Spotify reference is pinned to.

## Scope

**In:** the 25 tools, their arguments, response models, titles, annotations,
icon and server instructions; per-request authentication; both HTTP transports;
Docker/Coolify deployment; the test suite.

**Out:** the 6 `spotify://` resources, the 5 prompts, and the elicitation
confirmation on `remove_tracks_from_playlist`. Resources and prompts are
omitted because resource handlers cannot reliably reach the per-request
headers this server's auth model depends on. Elicitation is omitted because it
requires stateful HTTP sessions, which would force sticky sessions at the
proxy and break in-flight clients on every redeploy — a direct conflict with
the stateless deployment shape inherited from the TfNSW reference.
`remove_tracks_from_playlist` therefore performs the removal directly; its
`destructive_hint` annotation still tells clients to confirm.

## 1. Authentication

### The constraint

Every one of the 25 tools is user-scoped — playback, playlists, library,
history. Spotify's Client Credentials flow reaches none of them; they all
require an Authorization Code user token. An access token expires after one
hour. A refresh token issued through the client-secret flow is stable
indefinitely, whereas a PKCE refresh token rotates on every use and therefore
cannot live in a static client header.

### The model

Three headers, read per request, never persisted:

```
X-Spotify-Client-Id:      <Spotify app client id>
X-Spotify-Client-Secret:  <Spotify app client secret>
X-Spotify-Refresh-Token:  <long-lived refresh token>
```

A fallback for quick testing: `Authorization: Bearer <access token>` on its
own, used directly with no exchange. When both are present the three-header
form wins.

Header lookup is case-insensitive. A `Bearer ` scheme prefix on the
`Authorization` value is stripped. Blank values are treated as absent.

### Per-call lifecycle

Each tool call independently:

1. reads credentials from `ctx.headers` (`Context.headers` exists in mcp 2.x
   and is populated by the HTTP transports; it is `None` under stdio);
2. resolves an access token (cache hit, or a refresh exchange);
3. builds `spotipy.Spotify(auth=<token>, requests_session=<pooled session>)`;
4. runs the call and discards the client.

Clients are never shared between callers. This mirrors `client_for` in the
TfNSW reference and exists for the same reason.

### Token exchange

A direct `POST https://accounts.spotify.com/api/token` with
`grant_type=refresh_token`, HTTP Basic auth from the client id and secret.

`spotipy.oauth2.SpotifyOAuth` is deliberately **not** used: its default cache
handler writes a `.cache` token file to disk, which is exactly the credential
storage this server must not do. Passing `auth=<token>` to `spotipy.Spotify`
bypasses all of it.

### Access-token cache

In-memory only, to save a ~150ms token round-trip per call.

- Key: `sha256(client_id + "\0" + refresh_token)` — a hash, so no raw secret
  is held as a dict key.
- Value: `(access_token, expires_at)`, where `expires_at` is Spotify's
  `expires_in` minus a 60-second skew.
- Bounded: LRU, 512 entries, so it cannot grow without limit.
- Expired entries are evicted on access.
- Nothing from it is ever logged.

The cache is purely derived. Losing it on redeploy costs one extra round-trip
per caller and nothing else.

### Connection pooling

Process-wide, via the `_SharedPoolAdapter` pattern from the TfNSW reference: a
`requests.adapters.HTTPAdapter` subclass whose `close()` is a no-op, mounted
into each per-call session. This is safe because a connection pool is keyed by
host, not by credential — it holds sockets to `api.spotify.com` and nothing
about who is calling. The access token lives in the per-call session's headers
and never touches the shared pool.

### Failure modes

`MissingCredentialsError` names the exact headers required and never echoes a
supplied value. A failed refresh exchange raises `token_refresh_failed`
carrying Spotify's `error`/`error_description` but never the credentials.

## 2. Multi-tenancy correction to the regime fallback

The Spotify reference handles Spotify's February 2026 restricted/legacy regime
split in `spotify_api.py`: try the restricted request shape, fall back to the
legacy one on a 400/404/405/410, and remember the answer in a **process-global
set** (`_legacy_families`).

That is correct for a single-user stdio server and wrong for a shared one. Two
callers using two different Spotify apps may be on two different regimes; a
global memo lets the first caller pin every later caller to the wrong endpoint
for the life of the process.

**Correction:** key the memo by client id — `dict[client_id, set[family]]`,
bounded (LRU, 512 client ids) — so each caller's app learns its own regime
independently. Under the `Authorization: Bearer` fallback, where no client id
is known, the memo key is the empty string; those callers share one bucket,
which is acceptable because that path is documented as testing-only.

Everything else about the fallback is preserved: the same three endpoint
families (`playlist-items`, `create-playlist`, `library-write`) spanning the
same seven operations, the same request shapes, and the same rule that the
legacy answer is memoised only once
it actually succeeds, so a genuine not-found (which fails both ways) never
pins the wrong regime.

## 3. Response format parity

### Models

The same Pydantic models, field for field, with the same optionality, so the
generated output schemas match the reference:

`Track`, `Album`, `Artist`, `Playlist`, `PlaybackState`, `Device`,
`UserProfile`, `SearchResults`, `QueueState`, `TrackList`, `ArtistInfo`,
`AlbumInfo`, `PlaylistList`, `PlaylistTracks`, `SavedTracks`, `DeviceList`,
`TopItems`, `RecentlyPlayed`, `ActionResult`.

`RemovalConfirmation` is dropped along with elicitation.

Every field of `UserProfile` except `id` stays optional: Spotify's restricted
regime strips them rather than erroring, so requiring them would turn a
degraded response into a hard failure.

### The `ctx` parameter

Every tool in the reference reads a module-level client. Here there is no such
client: credentials arrive per request, so **every tool takes a
`ctx: Context` parameter** in order to reach `ctx.headers`.

This does not break argument parity. The SDK injects `Context` by type
annotation and excludes it from the tool's generated input schema, so the
arguments a client sees and sends are unchanged. `ctx` is therefore omitted
from the signatures in the inventory table below; read it as present on all 25.

### Retry policy

The per-call `spotipy.Spotify` is constructed with
`status_forcelist=(500, 502, 503, 504)`, preserving the reference's deliberate
choice to retry transient server errors but **never** a 429. Since July 2026
Spotify counts quota per developer account, so retrying a `QUOTA_EXCEEDED` 429
burns the caller's whole pool; it is surfaced instead, for the caller to back
off.

### Metadata

Same tool names, arguments, defaults, docstrings, titles, `ToolAnnotations`
and the inline Spotify SVG icon, plus the same server `INSTRUCTIONS` block.

mcp 2.x renamed the annotation and icon fields to snake_case
(`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`,
`mime_type`) from 1.x's camelCase. The serialised wire format is unchanged, so
this is a source-level rename only and annotation parity holds.

### Errors

`errors.py` is ported with its classification table intact: the
`SpotifyMCPErrorCode` enum, the reason-keyed cases (`NO_ACTIVE_DEVICE`,
`PREMIUM_REQUIRED`, `QUOTA_EXCEEDED`) checked before the status-code cases, the
401/403/404/429/5xx mapping, and the `Retry-After` extraction.

The model-facing string keeps the reference's exact shape:

```
<message> — <suggestion> (spotify reason: <reason>) [<error_code>]
```

One change: raised as `mcp.server.mcpserver.exceptions.ToolError` rather than
`ValueError`, which is the correct idiom in mcp 2.x. The wire-visible text is
identical.

Two codes are added for this server's auth model:

- `missing_credentials` — no usable credentials in the request headers
- `token_refresh_failed` — the refresh exchange was rejected

Argument-validation failures inside tools (`action='seek' requires
position_ms`, `Maximum 50 track IDs per request`, and so on) keep their exact
messages and are raised as `ToolError` too.

## 4. Concurrency

`spotipy` is blocking `requests`. Every Spotify call is wrapped in
`anyio.to_thread.run_sync`, as the TfNSW reference does, so one slow Spotify
response cannot stall every other in-flight request on a shared instance.

`get_playlist_tracks` is already `async` in the reference because it awaits
progress notifications between pages; its per-page fetches move onto worker
threads while the `await ctx.report_progress(...)` / `await ctx.info(...)`
calls stay on the event loop.

## 5. Module layout

The reference keeps 25 tools, all models and all parsing in a single 1783-line
module. This server splits them, so each unit is small enough to test and edit
in isolation:

```
spotify_mcp_mx/
  __init__.py     __version__
  __main__.py     uvicorn entrypoint
  app.py          Starlette app: /mcp, /sse, /health, /
  server.py       MCPServer instance, INSTRUCTIONS, SPOTIFY_ICON
  auth.py         header extraction, token exchange, cache, per-call client
  errors.py       classification table → ToolError
  models.py       the response models
  parsing.py      parse_track / parse_artist / parse_album / parse_playlist
  spotify_api.py  regime fallback, keyed by client id
  logging_utils.py  log_tool_execution, log_pagination_info
  tools/
    __init__.py   imports the submodules so registration happens on import
    playback.py   get_playback_state, control_playback, list_devices,
                  transfer_playback, get_queue, add_to_queue
    catalog.py    search_music, get_track_info, get_artist_info, get_album_info
    playlists.py  get_user_playlists, get_playlist_info, get_playlist_tracks,
                  create_playlist, modify_playlist_details,
                  add_tracks_to_playlist, remove_tracks_from_playlist,
                  reorder_playlist_tracks, unfollow_playlist
    library.py    get_me, get_saved_tracks, save_tracks, remove_saved_tracks,
                  get_top_items, get_recently_played
  authorize.py    local one-time OAuth helper (excluded from the image)
```

Import direction is `tools → server → (models, auth, errors, parsing)`, with
`app.py` importing `server` and then `tools`. No cycles.

`spotify_types.py` (TypedDicts describing the subset of Spotify response
fields the code reads) is ported as-is to keep mypy strict passing.

Note: `playlists.py` carries 9 tools rather than the 8 stated during
brainstorming — `unfollow_playlist` belongs with the playlist group.

### `authorize.py`

A local CLI, not a server feature, and excluded from the Docker image. It runs
the Authorization Code flow on the user's own machine against their own
Spotify app (loopback redirect, all 16 scopes from the reference's `SCOPES`
list) and prints the three headers ready to paste into a client config. It
writes no file unless asked.

## 6. Transports and endpoints

Identical to the TfNSW reference:

| Path | Purpose |
|---|---|
| `/mcp` | Streamable HTTP, `stateless_http=True` |
| `/sse`, `/messages/` | Legacy SSE transport |
| `/health` | Unauthenticated liveness probe |
| `/` | Service description naming the required headers |

`create_app(host)` builds the streamable-HTTP app as the base (it owns the
lifespan running the session manager) and appends the SSE routes, skipping any
path already mounted.

`host` is passed to the SDK only so it can decide about DNS-rebinding
protection: the SDK auto-enables a localhost-only Host/Origin allowlist when
told it is serving loopback. Binding `0.0.0.0` correctly leaves it off, which
matters because requests arriving through Coolify's Traefik carry the public
domain in `Host`.

Bind address and port come from `HOST` (default `0.0.0.0`) and `PORT`
(default **6402** — 6401 is assumed taken by the TfNSW server on the same
host).

## 7. Deployment

- **Dockerfile** — multi-stage, `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
  builder, `python:3.12-slim` runtime. Locked dependencies install in their own
  layer before application code, so a code-only change rebuilds in seconds.
  Non-root uid 10001. Python-only `HEALTHCHECK` (the slim image ships no curl).
- **docker-compose.yml** — no secrets, because there are none. `HOST`/`PORT`
  only.
- **.env.example** — states explicitly that the running server needs no
  secrets, and that the `SPOTIFY_*` variables it lists are used *only* by the
  opt-in live tests and the local `authorize` helper.
- **DEPLOYMENT.md** — Coolify Docker Compose resource, domain assignment to
  port 6402, `/health` check, why there are no environment secrets, why the
  endpoint being publicly reachable is acceptable (a caller without valid
  Spotify credentials gets errors from Spotify, and no quota of the operator's
  is at risk), and the note on Host-header checks.
- **README.md** — authentication, endpoints, the 25-tool table, client
  connection recipes (Claude Code `--header`; `mcp-remote` for Claude Desktop,
  which has no custom-header field in its native connector UI), and local
  development.

## 8. Testing

Test-driven: each unit's tests are written before its implementation. The
default suite is fully offline — `spotipy` and the token endpoint are mocked,
no credentials needed, nothing leaves the machine.

| File | Covers |
|---|---|
| `conftest.py` | fake spotipy client, fake token endpoint, in-memory MCP client over the streamable transport |
| `test_auth.py` | header parsing (case-insensitivity, blank, `Bearer` prefix, precedence); refresh exchange; cache hit, expiry, eviction and **isolation between callers**; no secret in any error string or log record |
| `test_tools.py` | all 25 tools: argument mapping, response models, pagination, the `limit` clamps, the 50/100-item guards |
| `test_parsing.py` | `parse_track`/artist/album against real-shaped fixtures, including null entries and missing-album cases |
| `test_errors.py` | the classification table and exact message-format parity with the reference |
| `test_regime.py` | restricted→legacy fallback, memo-only-on-success, and **per-client-id isolation** |
| `test_server_http.py` | `/health`, `/`, tool listing over HTTP, missing-header error |
| `test_tool_metadata.py` | the README table matches the registered tools; every tool has a title, icon and behaviour annotations |
| `test_live.py` | marked `live`, self-skipping unless the `SPOTIFY_*` env vars are set |

Lint and types: `ruff` plus `mypy` strict, taking the stricter of the two
references' configurations.

### CI

GitHub Actions on every push and pull request: ruff, mypy, the offline suite,
and a Docker job that builds the image, waits for `/health`, and asserts the
running container lists all 25 tools. Live tests run on `main` and manual
dispatch, skipping themselves when the repository secrets are absent so CI is
green without them.

## 9. Security notes

- No credential is ever written to disk, and `SpotifyOAuth`'s cache-file path
  is bypassed entirely.
- The ported `log_tool_execution` decorator logs tool kwargs. Credentials
  travel in headers, not kwargs, so nothing sensitive is in scope — but the
  decorator must also exclude the `ctx` argument from what it logs, since
  `ctx.headers` carries the caller's secret.
- Error messages name headers, never values.
- The access-token cache is keyed by hash, bounded, and never logged.
- The endpoint is publicly reachable by design; the operator can put
  Traefik basic-auth or an IP allowlist in front of it if they want it private.

## 10. Tool inventory

All 25, with the signatures to reproduce exactly.

| Tool | Signature | Returns |
|---|---|---|
| `get_me` | `()` | `UserProfile` |
| `get_playback_state` | `()` | `PlaybackState` |
| `control_playback` | `(action, track_ids=None, context_uri=None, position_ms=None, volume_percent=None, state=None, device_id=None)` | `PlaybackState` |
| `list_devices` | `()` | `DeviceList` |
| `transfer_playback` | `(device_id, play=True)` | `ActionResult` |
| `get_queue` | `()` | `QueueState` |
| `add_to_queue` | `(track_id)` | `ActionResult` |
| `search_music` | `(query, qtype="track", limit=10, offset=0, year=None, year_range=None, genre=None, artist=None, album=None)` | `SearchResults` |
| `get_track_info` | `(track_ids: str \| list[str])` | `TrackList` |
| `get_artist_info` | `(artist_id)` | `ArtistInfo` |
| `get_album_info` | `(album_id)` | `AlbumInfo` |
| `get_user_playlists` | `(limit=20, offset=0)` | `PlaylistList` |
| `get_playlist_info` | `(playlist_id)` | `Playlist` |
| `get_playlist_tracks` | `(playlist_id, limit=None, offset=0)` | `PlaylistTracks` |
| `create_playlist` | `(name, description="", public=True)` | `Playlist` |
| `modify_playlist_details` | `(playlist_id, name=None, description=None, public=None)` | `ActionResult` |
| `add_tracks_to_playlist` | `(playlist_id, track_uris)` | `ActionResult` |
| `remove_tracks_from_playlist` | `(playlist_id, track_uris)` | `ActionResult` |
| `reorder_playlist_tracks` | `(playlist_id, range_start, insert_before, range_length=1, snapshot_id=None)` | `ActionResult` |
| `unfollow_playlist` | `(playlist_id)` | `ActionResult` |
| `get_saved_tracks` | `(limit=20, offset=0)` | `SavedTracks` |
| `save_tracks` | `(track_ids)` | `ActionResult` |
| `remove_saved_tracks` | `(track_ids)` | `ActionResult` |
| `get_top_items` | `(item_type="tracks", time_range="medium_term", limit=20)` | `TopItems` |
| `get_recently_played` | `(limit=20)` | `RecentlyPlayed` |

Behavioural details to preserve:

- IDs, `spotify:` URIs and `open.spotify.com` URLs are interchangeable
  everywhere, via the ported `to_id` / `to_uri` helpers.
- `search_music` composes Spotify filter syntax (`artist:`, `album:`, `year:`,
  `genre:`) onto the query, clamps `limit` to 1–50, and coerces non-track
  result types into `Track` shape so the response model is uniform.
- `get_playlist_tracks` pages at 100 per request with a 10,000-offset safety
  stop, reads `item` or `track` from each entry depending on regime, fetches
  the total up front as a progress denominator, and reports progress per page.
- `get_track_info` uses the batch endpoint above one ID (50 tracks, 1 call)
  and rejects more than 50.
- `save_tracks` / `remove_saved_tracks` reject more than 50 IDs.
- `get_album_info` back-fills each album track's missing `album` reference from
  the parent album before parsing.
- `get_artist_info` truncates to the top 10 tracks.
- `get_saved_tracks` populates `added_at`; `get_recently_played` populates
  `played_at`.
- `modify_playlist_details` rejects a call with no field supplied.
- `reorder_playlist_tracks` validates non-negative positions and
  `range_length >= 1`.

## Open assumptions

Stated rather than asked, and cheap to change:

1. Port **6402**, on the assumption 6401 is taken by the TfNSW server.
2. Package/module name `spotify_mcp_mx`, matching the repository name.
3. Header names `X-Spotify-Client-Id` / `-Client-Secret` / `-Refresh-Token`.
