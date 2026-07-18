"""Lightweight in-process plugin manager for built-in providers."""

from __future__ import annotations

from collections.abc import Sequence

from musicvault.models.interfaces.artwork import ArtworkProvider
from musicvault.models.interfaces.media_server import MediaServerPlugin
from musicvault.models.interfaces.metadata import MetadataProvider


class PluginManager:
    """Holds explicitly registered built-in providers (no entry-point
    discovery yet — Phase 6 wires Chromaprint-style explicit construction
    in :class:`~musicvault.core.container.Container`; Phase 11 adds
    artwork providers; Phase 15 adds media-server plugins the same way).
    """

    def __init__(
        self,
        metadata_providers: Sequence[MetadataProvider] = (),
        artwork_providers: Sequence[ArtworkProvider] = (),
        media_server_plugins: Sequence[MediaServerPlugin] = (),
    ) -> None:
        self._metadata_providers = list(metadata_providers)
        self._artwork_providers = list(artwork_providers)
        self._media_server_plugins = list(media_server_plugins)

    def get_metadata_providers(self) -> list[MetadataProvider]:
        """Return providers sorted by priority (lower = higher priority)."""
        return sorted(self._metadata_providers, key=lambda p: p.priority)

    def get_artwork_providers(self) -> list[ArtworkProvider]:
        """Return artwork providers sorted by priority (lower = higher)."""
        return sorted(self._artwork_providers, key=lambda p: p.priority)

    def get_media_servers(self) -> list[MediaServerPlugin]:
        """Return registered media-server plugins (stable registration order)."""
        return list(self._media_server_plugins)
