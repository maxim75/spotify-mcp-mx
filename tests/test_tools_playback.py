from __future__ import annotations

import copy
from typing import TYPE_CHECKING

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
from tests.fixtures import TRACK

if TYPE_CHECKING:
    from tests.conftest import FakeCtx, FakeSpotify

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
