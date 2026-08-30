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


async def test_ctx_none_surfaces_as_a_classified_tool_error(patched_client: Any) -> None:
    """A caller passing no ctx at all (rather than a ctx with empty headers)
    must get the same classified error, not a raw MissingCredentialsError."""
    with pytest.raises(ToolError) as excinfo:
        await run_tool(None, lambda client, scope: "unreachable")
    assert "[missing_credentials]" in str(excinfo.value)


class RequestlessCtx:
    """Mimics the real SDK: ``Context.headers`` is a property reaching into
    request-scoped state, and raises ValueError when there is no active
    request rather than returning ``None`` or an empty mapping."""

    @property
    def headers(self) -> dict[str, str]:
        raise ValueError("Context is not available outside of a request")


async def test_ctx_headers_property_failure_surfaces_as_missing_credentials(
    patched_client: Any,
) -> None:
    """The ValueError from a real SDK Context used outside a request must be
    classified as missing credentials, not leak as a bare, uncoded ValueError
    indistinguishable from a tool's own argument-validation failure."""
    with pytest.raises(ToolError) as excinfo:
        await run_tool(RequestlessCtx(), lambda client, scope: "unreachable")  # type: ignore[arg-type]
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
