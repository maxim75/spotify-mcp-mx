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
