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
