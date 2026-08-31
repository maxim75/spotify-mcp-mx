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
        codes = query.get("code")
        states = query.get("state")
        _CallbackHandler.code = codes[0] if codes else None
        _CallbackHandler.state = states[0] if states else None
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
