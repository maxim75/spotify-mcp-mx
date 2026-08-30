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
    import anyio
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    config = uvicorn.Config(
        create_app("127.0.0.1"), host="127.0.0.1", port=6499, log_level="warning"
    )
    server = uvicorn.Server(config)

    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        while not server.started:
            await anyio.sleep(0.05)
        try:
            async with streamable_http_client("http://127.0.0.1:6499/mcp") as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
            assert len(tools) == 25
            assert {"get_me", "search_music", "get_playlist_tracks"} <= {t.name for t in tools}
        finally:
            server.should_exit = True


async def test_a_tool_call_without_credentials_names_the_headers() -> None:
    import anyio
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    config = uvicorn.Config(
        create_app("127.0.0.1"), host="127.0.0.1", port=6498, log_level="warning"
    )
    server = uvicorn.Server(config)

    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        while not server.started:
            await anyio.sleep(0.05)
        try:
            async with streamable_http_client("http://127.0.0.1:6498/mcp") as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    result = await session.call_tool("get_me", {})
            assert result.is_error
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            assert "X-Spotify-Refresh-Token" in text
            assert "[missing_credentials]" in text
        finally:
            server.should_exit = True
