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
