from __future__ import annotations

import spotify_mcp_mx


def test_version_is_a_dotted_string() -> None:
    assert isinstance(spotify_mcp_mx.__version__, str)
    assert spotify_mcp_mx.__version__.count(".") == 2
