"""Tool modules. Importing this package registers every tool on the server."""

from __future__ import annotations

from . import catalog, library, playback  # noqa: F401  - registration side effects

__all__ = ["catalog", "library", "playback"]
