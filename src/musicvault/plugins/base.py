"""Minimal Plugin protocol shared by built-in providers."""

from __future__ import annotations

from typing import Protocol


class Plugin(Protocol):
    """Marker protocol for discoverable MusicVault plugins."""

    plugin_id: str
