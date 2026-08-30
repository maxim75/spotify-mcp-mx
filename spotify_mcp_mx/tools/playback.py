"""Playback control tools: state, transport controls, devices and queue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import Context  # noqa: TC002 - the SDK injects by runtime type
from mcp.types import ToolAnnotations

from ..logging_utils import log_tool_execution
from ..models import ActionResult, Device, DeviceList, PlaybackState, QueueState
from ..parsing import parse_track
from ..server import SPOTIFY_ICON, mcp, run_tool
from ..utils import to_uri

if TYPE_CHECKING:
    import spotipy


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


@mcp.tool(
    title="Now Playing",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_playback_state(ctx: Context | None = None) -> PlaybackState:
    """Get the current playback state: track, device, progress, shuffle and repeat.

    Returns:
        PlaybackState (is_playing is False when nothing is playing)
    """

    def work(client: spotipy.Spotify, scope: str) -> PlaybackState:
        return _playback_state(client)

    return await run_tool(ctx, work)


@mcp.tool(
    title="Control Playback",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def control_playback(
    action: str,
    track_ids: list[str] | None = None,
    context_uri: str | None = None,
    position_ms: int | None = None,
    volume_percent: int | None = None,
    state: str | None = None,
    device_id: str | None = None,
    ctx: Context | None = None,
) -> PlaybackState:
    """Control Spotify playback. Requires Premium and an active device.

    Args:
        action: 'play', 'pause', 'next', 'previous', 'seek', 'volume', 'shuffle' or 'repeat'
        track_ids: Tracks to play (action='play'; ignored when context_uri is set)
        context_uri: Album/playlist/artist URI to play (action='play')
        position_ms: Position in milliseconds (required for action='seek')
        volume_percent: Volume 0-100 (required for action='volume')
        state: 'on'/'off' for shuffle; 'track'/'context'/'off' for repeat
        device_id: Target device (default: the currently active one)

    Returns:
        PlaybackState after the action
    """

    def work(client: spotipy.Spotify, scope: str) -> PlaybackState:
        if action == "play":
            if context_uri:
                client.start_playback(device_id=device_id, context_uri=context_uri)
            elif track_ids:
                client.start_playback(
                    device_id=device_id, uris=[to_uri("track", t) for t in track_ids]
                )
            else:
                client.start_playback(device_id=device_id)
        elif action == "pause":
            client.pause_playback(device_id=device_id)
        elif action == "next":
            client.next_track(device_id=device_id)
        elif action == "previous":
            client.previous_track(device_id=device_id)
        elif action == "seek":
            if position_ms is None:
                raise ValueError("action='seek' requires position_ms")
            client.seek_track(position_ms, device_id=device_id)
        elif action == "volume":
            if volume_percent is None:
                raise ValueError("action='volume' requires volume_percent")
            client.volume(volume_percent, device_id=device_id)
        elif action == "shuffle":
            if state not in ("on", "off"):
                raise ValueError("action='shuffle' requires state='on' or 'off'")
            client.shuffle(state == "on", device_id=device_id)
        elif action == "repeat":
            if state not in ("track", "context", "off"):
                raise ValueError("action='repeat' requires state='track', 'context' or 'off'")
            client.repeat(state, device_id=device_id)
        else:
            raise ValueError(f"Invalid action: {action}")

        return _playback_state(client)

    return await run_tool(ctx, work)


@mcp.tool(
    title="Available Devices",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def list_devices(ctx: Context | None = None) -> DeviceList:
    """List the user's available Spotify devices.

    Returns:
        DeviceList; use transfer_playback with a device id to make one active
    """

    def work(client: spotipy.Spotify, scope: str) -> DeviceList:
        result = client.devices() or {}
        return DeviceList(
            devices=[
                Device(
                    id=d.get("id"),
                    name=d["name"],
                    type=d.get("type"),
                    is_active=d.get("is_active", False),
                    volume_percent=d.get("volume_percent"),
                )
                for d in result.get("devices", [])
            ]
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Switch Device",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def transfer_playback(
    device_id: str, play: bool = True, ctx: Context | None = None
) -> ActionResult:
    """Move playback to a different device (see list_devices).

    Args:
        device_id: Target device ID
        play: Start playing after the transfer (default True)
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        client.transfer_playback(device_id, force_play=play)
        return ActionResult(status="success", message="Playback transferred")

    return await run_tool(ctx, work)


@mcp.tool(
    title="Get Queue",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def get_queue(ctx: Context | None = None) -> QueueState:
    """Get the current playback queue.

    Returns:
        Currently playing track and queue of upcoming tracks
    """

    def work(client: spotipy.Spotify, scope: str) -> QueueState:
        result = client.queue()

        queue_tracks = []
        if result.get("queue"):
            queue_tracks = [parse_track(item) for item in result["queue"]]

        return QueueState(
            currently_playing=(
                parse_track(result["currently_playing"])
                if result.get("currently_playing")
                else None
            ),
            queue=queue_tracks,
        )

    return await run_tool(ctx, work)


@mcp.tool(
    title="Add to Queue",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
    icons=[SPOTIFY_ICON],
)
@log_tool_execution
async def add_to_queue(track_id: str, ctx: Context | None = None) -> ActionResult:
    """Add a track to the playback queue.

    Args:
        track_id: Spotify track ID to add to queue
    Returns:
        Status and message
    """

    def work(client: spotipy.Spotify, scope: str) -> ActionResult:
        client.add_to_queue(to_uri("track", track_id))
        return ActionResult(status="success", message="Added track to queue")

    return await run_tool(ctx, work)
