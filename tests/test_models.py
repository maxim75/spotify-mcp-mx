from __future__ import annotations

from spotify_mcp_mx.models import ActionResult, PlaylistTracks, Track, UserProfile


def test_track_requires_only_name_id_and_artist() -> None:
    t = Track(name="Idioteque", id="abc", artist="Radiohead")
    assert t.album is None
    assert t.added_at is None
    assert t.played_at is None


def test_user_profile_requires_only_id() -> None:
    # Spotify's restricted regime strips these fields rather than erroring,
    # so requiring any of them would turn a degraded response into a failure.
    profile = UserProfile(id="maksym")
    assert profile.display_name is None
    assert profile.email is None
    assert profile.country is None


def test_playlist_tracks_reports_returned_separately_from_total() -> None:
    page = PlaylistTracks(items=[], total=1200, limit=100, offset=0, returned=0)
    assert page.total == 1200
    assert page.returned == 0


def test_action_result_snapshot_is_optional() -> None:
    assert ActionResult(status="success", message="done").snapshot_id is None
