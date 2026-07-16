"""Lightweight in-process plugin manager for built-in metadata providers."""

from __future__ import annotations

from collections.abc import Sequence

from musicvault.models.interfaces.metadata import MetadataProvider


class PluginManager:
    """Holds explicitly registered built-in providers (no entry-point
    discovery yet — Phase 6 wires Chromaprint-style explicit construction
    in :class:`~musicvault.core.container.Container`)."""

    def __init__(self, metadata_providers: Sequence[MetadataProvider] = ()) -> None:
        self._metadata_providers = list(metadata_providers)

    def get_metadata_providers(self) -> list[MetadataProvider]:
        """Return providers sorted by priority (lower = higher priority)."""
        return sorted(self._metadata_providers, key=lambda p: p.priority)
