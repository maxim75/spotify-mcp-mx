# Spotify MCP Server

An [MCP](https://modelcontextprotocol.io) server exposing the Spotify Web API to
LLM clients, built on [`spotipy`](https://spotipy.readthedocs.io) and ported from
[jamiew/spotify-mcp](https://github.com/jamiew/spotify-mcp), whose tool shapes and
field names it deliberately mirrors so a client written against that server sees
the same responses here.

Twenty-five tools cover search, playback control, devices, the queue, playlists,
the saved-tracks library, and listening history.

## Authentication

**The server stores no credentials.** Every caller supplies their own Spotify
app credentials and refresh token on every request:

```
X-Spotify-Client-Id: <your app's client id>
X-Spotify-Client-Secret: <your app's client secret>
X-Spotify-Refresh-Token: <a refresh token for the signed-in user>
```

A request without these gets an error naming the missing headers rather than a
silent failure. Each tool call builds a `spotipy.Spotify` client from that
request's credentials and drops it as soon as the call returns, so one caller's
token can never serve another's request.

HTTP **connections** are nevertheless pooled process-wide, which saves a TCP and
TLS handshake on every call. The split is deliberate: a connection pool is keyed
by host, not by credential, so it can be shared safely, whereas the access token
is held on the per-call `spotipy.Spotify` **instance** and attached fresh to the
headers of every request it makes — so the client (and the token it carries)
must be per-call, even though the underlying connections are process-wide.
Credentials are per-call; connections are process-wide.

An `Authorization: Bearer <access token>` header is also accepted, as a
**testing-only** fallback — Spotify access tokens expire after 3600 seconds, so
it is not a substitute for the three-header form in any real client.

Mint a refresh token from your own machine:

```bash
uv run python -m spotify_mcp_mx.authorize
```

This opens a browser to Spotify's consent screen, requests every scope the
tools need, and prints the three headers to paste into your client. It never
runs on the server, is excluded from the Docker image, and writes nothing to
disk.

## Endpoints

| Path | Purpose |
|---|---|
| `/mcp` | Streamable HTTP transport — use this |
| `/sse`, `/messages/` | Legacy SSE transport, for clients that need it |
| `/health` | Unauthenticated liveness probe |
| `/` | Service description |

Listens on `0.0.0.0:6402`; override with the `HOST` and `PORT` environment
variables.

## Connecting a client

### Claude Code

Header support is built in:

```bash
claude mcp add --transport http spotify https://your-host/mcp \
  --header "X-Spotify-Client-Id: YOUR_ID" \
  --header "X-Spotify-Client-Secret: YOUR_SECRET" \
  --header "X-Spotify-Refresh-Token: YOUR_TOKEN"
```

### Claude Desktop

Claude Desktop's (and claude.ai's) native **"Add custom connector"** UI accepts a
URL and OAuth credentials only — it has **no field for a custom header**, so it
cannot be used with this server directly. Connect through the
[`mcp-remote`](https://github.com/geelen/mcp-remote) bridge instead (needs Node):

```json
{
  "mcpServers": {
    "spotify": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://your-host/mcp",
        "--transport", "http-only",
        "--header", "X-Spotify-Client-Id:${SPOTIFY_CLIENT_ID}",
        "--header", "X-Spotify-Client-Secret:${SPOTIFY_CLIENT_SECRET}",
        "--header", "X-Spotify-Refresh-Token:${SPOTIFY_REFRESH_TOKEN}"
      ],
      "env": {
        "SPOTIFY_CLIENT_ID": "YOUR_ID",
        "SPOTIFY_CLIENT_SECRET": "YOUR_SECRET",
        "SPOTIFY_REFRESH_TOKEN": "YOUR_TOKEN"
      }
    }
  }
}
```

`mcp-remote` needs `Name:value` with **no space** after the colon. Config lives
at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, or
`%APPDATA%\Claude\claude_desktop_config.json` on Windows. Restart the app after
editing.

## Tools

IDs, `spotify:type:id` URIs and `open.spotify.com` URLs are interchangeable
everywhere a track, album, artist or playlist reference is accepted. Start from
`search_music` to turn names into IDs.

| Tool | What it does |
|---|---|
| `get_me` | Get the signed-in user's Spotify profile |
| `search_music` | Search Spotify for tracks, albums, artists, or playlists |
| `get_track_info` | Get detailed information about one or more tracks (up to 50) |
| `get_artist_info` | Get an artist's details and top tracks |
| `get_album_info` | Get an album's details and its tracks |
| `get_playback_state` | Get the current playback state: track, device, progress, shuffle and repeat |
| `control_playback` | Play, pause, skip, seek, set volume, shuffle or repeat |
| `list_devices` | List the user's available Spotify Connect devices |
| `transfer_playback` | Move playback to a different device |
| `get_queue` | Get the currently playing track and the upcoming queue |
| `add_to_queue` | Add a track to the playback queue |
| `get_user_playlists` | Get the signed-in user's playlists |
| `get_playlist_info` | Get a playlist's metadata, without its tracks |
| `get_playlist_tracks` | Get a playlist's tracks, paginated |
| `create_playlist` | Create a new, empty playlist |
| `modify_playlist_details` | Change a playlist's name, description and/or public visibility |
| `add_tracks_to_playlist` | Add tracks to a playlist (up to 100) |
| `remove_tracks_from_playlist` | Remove tracks from a playlist |
| `reorder_playlist_tracks` | Reorder a range of tracks within a playlist |
| `unfollow_playlist` | Unfollow a playlist — how Spotify deletes one you own |
| `get_saved_tracks` | Get the user's saved (Liked Songs) tracks |
| `save_tracks` | Save (like) tracks to the user's library |
| `remove_saved_tracks` | Remove tracks from the user's saved tracks |
| `get_top_items` | Get the user's top artists or tracks over a time range |
| `get_recently_played` | Get recently played tracks, most recent first |

## Notes

- **Playback control needs Spotify Premium and an active device.** If nothing
  is active, call `list_devices` then `transfer_playback` before
  `control_playback`.
- **Positions are zero-based.** `get_playlist_tracks` returns zero-based
  positions, and `reorder_playlist_tracks` / `remove_tracks_from_playlist`
  expect them back in that form.
- **Batch limits.** Up to 50 track IDs per lookup (`get_track_info`) or library
  write (`save_tracks`, `remove_saved_tracks`); up to 100 tracks per
  `add_tracks_to_playlist` call.
- **No recommendations endpoint.** Spotify has withdrawn `/recommendations`,
  audio-features and related-artists from third-party apps. There is nothing
  here that calls them; build suggestions from `get_top_items` and
  `get_recently_played` plus `search_music` instead.
- A newly created playlist may read back as public even when created private —
  that is Spotify's own reporting, not a failed write.

## Running it

### Docker (how it is deployed)

```bash
docker compose up --build -d
```

```bash
curl -sf localhost:6402/health
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the Coolify setup.

### Local development

```bash
uv sync
```

```bash
uv run python -m spotify_mcp_mx
```

### Tests

The default suite is fully offline — the Spotify client is mocked, so no
credentials are needed and no request leaves the machine:

```bash
uv run pytest
```

Smoke tests against the real API are opt-in and skip themselves unless
credentials are present:

```bash
SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... SPOTIFY_REFRESH_TOKEN=... \
  uv run pytest -m live
```

## Layout

| File | Role |
|---|---|
| `server.py` | The `MCPServer` instance, shared icon/instructions, and the `run_tool` harness every tool call goes through |
| `auth.py` | Header extraction, per-request token exchange and caching, and the process-wide connection pool |
| `app.py` | ASGI app wiring both transports plus `/health` and `/` |
| `authorize.py` | Local-only helper that mints a refresh token |
| `tools/catalog.py` | Search, tracks, artists and albums |
| `tools/playback.py` | Playback state, transport controls, devices and queue |
| `tools/playlists.py` | Browse, create, edit membership and ordering, unfollow |
| `tools/library.py` | Profile, saved tracks, top items, recently played |
| `models.py` | Pydantic response models — the tools' structured output schemas |
| `parsing.py` | Spotify API payloads → the models above |
| `spotify_api.py` | Falls back between Spotify's February 2026 "restricted" and "full/legacy" API regimes |
| `spotify_types.py` | `TypedDict`s for the subset of Spotify's response shapes the tools read |
| `errors.py` | Spotify/spotipy exceptions → classified `ToolError`s |
| `logging_utils.py` | Per-call timing and pagination logging |
| `utils.py` | ID / URI / URL normalisation |
